//! External service clients for the Rust migration R2 milestone.
//!
//! The Python runtime currently uses Ollama for embeddings and Qdrant for dense
//! vector storage. This crate keeps those dependencies as explicit HTTP clients
//! with bounded timeouts, retry budgets, batching, and cancellation-safe APIs.
//!
//! Embedded Qdrant compatibility is intentionally not implemented by reading the
//! Python client's local-mode data directory. The Rust migration preserves the
//! user-facing embedded mode by managing a loopback Qdrant server process whose
//! storage path is configured by the application; callers should use
//! [`qdrant::EmbeddedQdrantMode`] to document that choice at the API boundary.

pub mod ollama;
pub mod qdrant;

use std::{net::IpAddr, time::Duration};

use thiserror::Error;

/// Shared retry settings for external service calls.
#[derive(Debug, Clone)]
pub struct RetryPolicy {
    /// Maximum request attempts, including the first one.
    pub max_attempts: usize,
    /// Maximum total wall-clock time spent retrying one logical operation.
    pub budget: Duration,
    /// Initial exponential backoff delay.
    pub initial_backoff: Duration,
    /// Maximum backoff delay between attempts.
    pub max_backoff: Duration,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            max_attempts: 3,
            budget: Duration::from_secs(90),
            initial_backoff: Duration::from_millis(200),
            max_backoff: Duration::from_secs(8),
        }
    }
}

impl RetryPolicy {
    fn validate(&self) -> Result<(), ServiceError> {
        if self.max_attempts == 0 {
            return Err(ServiceError::InvalidConfig(
                "retry max_attempts must be at least 1".to_owned(),
            ));
        }
        if self.budget.is_zero() {
            return Err(ServiceError::InvalidConfig(
                "retry budget must be greater than zero".to_owned(),
            ));
        }
        Ok(())
    }
}

/// Errors returned by external service clients.
#[derive(Debug, Error)]
pub enum ServiceError {
    /// Configuration was invalid before a request was attempted.
    #[error("invalid service configuration: {0}")]
    InvalidConfig(String),
    /// Request construction failed.
    #[error("invalid request: {0}")]
    InvalidRequest(String),
    /// The remote service returned a non-success status.
    #[error("{service} returned HTTP {status}: {body}")]
    HttpStatus {
        /// Service name.
        service: &'static str,
        /// HTTP status code.
        status: http::StatusCode,
        /// Truncated response body.
        body: String,
    },
    /// HTTP transport or JSON error.
    #[error("{service} request failed: {source}")]
    Transport {
        /// Service name.
        service: &'static str,
        /// Source error.
        #[source]
        source: reqwest::Error,
    },
    /// JSON decoding failed after a bounded response was read.
    #[error("{service} returned invalid JSON: {source}")]
    Json {
        /// Service name.
        service: &'static str,
        /// JSON parser error.
        #[source]
        source: serde_json::Error,
    },
    /// A remote response exceeded the client-side memory budget.
    #[error("{service} response exceeded the {limit_bytes}-byte limit")]
    ResponseTooLarge {
        /// Service name.
        service: &'static str,
        /// Configured response limit.
        limit_bytes: usize,
    },
    /// A retry budget was exhausted.
    #[error("{service} retry budget exhausted after {attempts} attempt(s): {last_error}")]
    RetryBudget {
        /// Service name.
        service: &'static str,
        /// Attempts made.
        attempts: usize,
        /// Last observed error.
        last_error: String,
    },
    /// A service response was structurally valid JSON but violated the contract.
    #[error("{service} contract violation: {message}")]
    Contract {
        /// Service name.
        service: &'static str,
        /// Contract error detail.
        message: String,
    },
    /// The requested model was not present in Ollama tags.
    #[error("Ollama model '{model}' not found; available models: {available}")]
    ModelUnavailable {
        /// Requested model.
        model: String,
        /// Comma-separated model names.
        available: String,
    },
}

fn trim_base_url(value: &str, field: &str) -> Result<String, ServiceError> {
    let trimmed = value.trim().trim_end_matches('/').to_owned();
    if !(trimmed.starts_with("http://") || trimmed.starts_with("https://")) {
        return Err(ServiceError::InvalidConfig(format!(
            "{field} must start with http:// or https://"
        )));
    }
    Ok(trimmed)
}

fn validate_service_transport(base_url: &str, field: &str) -> Result<(), ServiceError> {
    let url = reqwest::Url::parse(base_url)
        .map_err(|error| ServiceError::InvalidConfig(format!("{field} is invalid: {error}")))?;
    if !url.username().is_empty() || url.password().is_some() {
        return Err(ServiceError::InvalidConfig(format!(
            "{field} must not contain credentials"
        )));
    }
    if url.query().is_some() || url.fragment().is_some() {
        return Err(ServiceError::InvalidConfig(format!(
            "{field} must not contain a query or fragment"
        )));
    }
    if url.scheme() == "https" {
        return url
            .host_str()
            .map(|_| ())
            .ok_or_else(|| ServiceError::InvalidConfig(format!("{field} must contain a host")));
    }
    if url.scheme() != "http" {
        return Err(ServiceError::InvalidConfig(format!(
            "{field} must use https://, or http:// for a loopback service"
        )));
    }
    let is_loopback = match url.host_str() {
        Some("localhost") => true,
        Some(host) => host
            .parse::<IpAddr>()
            .map(|address| address.is_loopback())
            .unwrap_or(false),
        None => false,
    };
    if is_loopback {
        Ok(())
    } else {
        Err(ServiceError::InvalidConfig(format!(
            "remote {field} must use https:// so indexed content is not sent in plaintext"
        )))
    }
}

fn truncate_body(body: &str) -> String {
    const LIMIT: usize = 2048;
    if body.len() <= LIMIT {
        body.to_owned()
    } else {
        let boundary = body
            .char_indices()
            .map(|(index, _)| index)
            .take_while(|index| *index <= LIMIT)
            .last()
            .unwrap_or_default();
        format!("{}...", &body[..boundary])
    }
}

async fn read_or_status<T: serde::de::DeserializeOwned>(
    service: &'static str,
    mut response: reqwest::Response,
) -> Result<T, ServiceError> {
    const MAX_RESPONSE_BYTES: usize = 64 * 1024 * 1024;
    let status = response.status();
    let mut bytes = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|source| ServiceError::Transport { service, source })?
    {
        if bytes.len().saturating_add(chunk.len()) > MAX_RESPONSE_BYTES {
            return Err(ServiceError::ResponseTooLarge {
                service,
                limit_bytes: MAX_RESPONSE_BYTES,
            });
        }
        bytes.extend_from_slice(&chunk);
    }
    if status.is_success() {
        serde_json::from_slice::<T>(&bytes).map_err(|source| ServiceError::Json { service, source })
    } else {
        let body = String::from_utf8_lossy(&bytes);
        Err(ServiceError::HttpStatus {
            service,
            status,
            body: truncate_body(body.as_ref()),
        })
    }
}

fn is_retryable(error: &ServiceError) -> bool {
    match error {
        ServiceError::Transport { source, .. } => {
            source.is_timeout() || source.is_connect() || source.is_request()
        }
        ServiceError::HttpStatus { status, .. } => {
            status.is_server_error() || *status == http::StatusCode::TOO_MANY_REQUESTS
        }
        _ => false,
    }
}

async fn retry_async<T, Fut, F>(
    service: &'static str,
    policy: &RetryPolicy,
    mut operation: F,
) -> Result<T, ServiceError>
where
    Fut: std::future::Future<Output = Result<T, ServiceError>>,
    F: FnMut() -> Fut,
{
    policy.validate()?;
    let started = tokio::time::Instant::now();
    let mut attempt = 0usize;
    let mut backoff = policy.initial_backoff;
    loop {
        attempt += 1;
        let remaining = policy
            .budget
            .checked_sub(started.elapsed())
            .unwrap_or_default();
        if remaining.is_zero() {
            return Err(ServiceError::RetryBudget {
                service,
                attempts: attempt.saturating_sub(1),
                last_error: "retry wall-clock budget elapsed".to_owned(),
            });
        }
        let outcome = match tokio::time::timeout(remaining, operation()).await {
            Ok(outcome) => outcome,
            Err(_) => {
                return Err(ServiceError::RetryBudget {
                    service,
                    attempts: attempt,
                    last_error: "operation exceeded the retry wall-clock budget".to_owned(),
                });
            }
        };
        match outcome {
            Ok(value) => return Ok(value),
            Err(error) if attempt < policy.max_attempts && is_retryable(&error) => {
                let last_error = error.to_string();
                let elapsed = started.elapsed();
                let remaining = policy.budget.checked_sub(elapsed).unwrap_or_default();
                if remaining.is_zero() || remaining <= backoff {
                    return Err(ServiceError::RetryBudget {
                        service,
                        attempts: attempt,
                        last_error,
                    });
                }
                tokio::time::sleep(backoff).await;
                backoff = std::cmp::min(backoff.saturating_mul(2), policy.max_backoff);
            }
            Err(error) => return Err(error),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{retry_async, truncate_body, RetryPolicy, ServiceError};
    use std::time::Duration;

    #[test]
    fn unicode_error_body_truncation_never_splits_a_code_point() {
        let body = "é".repeat(2_000);
        let truncated = truncate_body(&body);
        assert!(truncated.ends_with("..."));
        assert!(truncated.len() <= 2051);
    }

    #[tokio::test]
    async fn retry_budget_is_a_hard_wall_clock_limit_for_one_hung_attempt() {
        let policy = RetryPolicy {
            max_attempts: 3,
            budget: Duration::from_millis(25),
            initial_backoff: Duration::from_millis(1),
            max_backoff: Duration::from_millis(2),
        };
        let started = tokio::time::Instant::now();
        let error = retry_async("test", &policy, || async {
            tokio::time::sleep(Duration::from_secs(1)).await;
            Ok::<(), ServiceError>(())
        })
        .await
        .expect_err("hung operation must time out");

        assert!(matches!(
            error,
            ServiceError::RetryBudget { attempts: 1, .. }
        ));
        assert!(started.elapsed() < Duration::from_millis(250));
    }
}
