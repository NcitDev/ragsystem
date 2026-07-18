use anyhow::{bail, Context};
use reqwest::{Method, StatusCode};
use serde_json::Value;

#[derive(Clone)]
pub struct ApiClient {
    base_url: String,
    token: Option<String>,
    http: reqwest::Client,
}

impl ApiClient {
    pub fn new(base_url: impl Into<String>, token: Option<String>) -> anyhow::Result<Self> {
        let base_url = base_url.into().trim_end_matches('/').to_owned();
        let parsed = reqwest::Url::parse(&base_url).context("invalid daemon base URL")?;
        if !matches!(parsed.scheme(), "http" | "https") {
            bail!("daemon base URL must use HTTP or HTTPS");
        }
        if !parsed.username().is_empty() || parsed.password().is_some() {
            bail!("daemon base URL must not contain credentials");
        }
        if parsed.query().is_some() || parsed.fragment().is_some() {
            bail!("daemon base URL must not contain a query or fragment");
        }
        if parsed.scheme() == "http" {
            let is_loopback = parsed.host_str().is_some_and(|host| {
                let host = host
                    .strip_prefix('[')
                    .and_then(|value| value.strip_suffix(']'))
                    .unwrap_or(host);
                host.eq_ignore_ascii_case("localhost")
                    || host
                        .parse::<std::net::IpAddr>()
                        .is_ok_and(|address| address.is_loopback())
            });
            if !is_loopback {
                bail!("refusing plaintext HTTP daemon URL outside loopback; use HTTPS");
            }
        }
        Ok(Self {
            base_url,
            token,
            http: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(120))
                .build()?,
        })
    }

    pub async fn get(&self, path: &str) -> anyhow::Result<Value> {
        self.request(Method::GET, path, None).await
    }

    pub async fn post(&self, path: &str, body: Value) -> anyhow::Result<Value> {
        self.request(Method::POST, path, Some(body)).await
    }

    /// POST with an operation-specific timeout (Python parity: 600s index-type
    /// commands, 300s smart-search/ask, 180s understand, 60s search/list).
    pub async fn post_with_timeout(
        &self,
        path: &str,
        body: Value,
        timeout_secs: u64,
    ) -> anyhow::Result<Value> {
        self.request_with_timeout(Method::POST, path, Some(body), Some(timeout_secs))
            .await
    }

    pub async fn request(
        &self,
        method: Method,
        path: &str,
        body: Option<Value>,
    ) -> anyhow::Result<Value> {
        self.request_with_timeout(method, path, body, None).await
    }

    async fn request_with_timeout(
        &self,
        method: Method,
        path: &str,
        body: Option<Value>,
        timeout_secs: Option<u64>,
    ) -> anyhow::Result<Value> {
        let url = format!("{}{}", self.base_url, normalized_path(path));
        let mut request = self.http.request(method, url);
        if let Some(seconds) = timeout_secs {
            request = request.timeout(std::time::Duration::from_secs(seconds));
        }
        if let Some(token) = &self.token {
            request = request.bearer_auth(token);
        }
        if let Some(body) = body {
            request = request.json(&body);
        }
        let mut response = request.send().await.context("daemon request failed")?;
        let status = response.status();
        const MAX_RESPONSE_BYTES: usize = 16 * 1024 * 1024;
        let mut bytes = Vec::new();
        while let Some(chunk) = response
            .chunk()
            .await
            .context("failed to read daemon response")?
        {
            if bytes.len().saturating_add(chunk.len()) > MAX_RESPONSE_BYTES {
                bail!("daemon response exceeded {MAX_RESPONSE_BYTES} bytes");
            }
            bytes.extend_from_slice(&chunk);
        }
        if status == StatusCode::NO_CONTENT {
            return Ok(Value::Null);
        }
        let value: Value = serde_json::from_slice(&bytes)
            .with_context(|| format!("daemon returned non-JSON response with status {status}"))?;
        if !status.is_success() {
            let message = value
                .get("error")
                .or_else(|| value.get("detail"))
                .and_then(Value::as_str)
                .unwrap_or("daemon request failed");
            bail!("{message} ({status})");
        }
        Ok(value)
    }
}

fn normalized_path(path: &str) -> String {
    if path.starts_with('/') {
        path.to_owned()
    } else {
        format!("/{path}")
    }
}

#[cfg(test)]
mod tests {
    use super::{normalized_path, ApiClient};

    #[test]
    fn paths_are_normalized_once() {
        assert_eq!(normalized_path("status"), "/status");
        assert_eq!(normalized_path("/status"), "/status");
    }

    #[test]
    fn plaintext_daemon_urls_are_limited_to_loopback() {
        assert!(ApiClient::new("http://127.0.0.1:7890", None).is_ok());
        assert!(ApiClient::new("http://[::1]:7890", None).is_ok());
        assert!(ApiClient::new("https://rag.example.com", None).is_ok());
        assert!(ApiClient::new("http://rag.example.com", Some("secret".to_owned())).is_err());
        assert!(ApiClient::new("ftp://127.0.0.1:7890", None).is_err());
        assert!(ApiClient::new("https://user:pass@rag.example.com", None).is_err());
        assert!(ApiClient::new("https://rag.example.com?token=secret", None).is_err());
    }
}
