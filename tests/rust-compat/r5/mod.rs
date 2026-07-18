use std::{
    fs,
    net::SocketAddr,
    sync::{Arc, Mutex},
    time::Duration,
};

use axum::{extract::State, routing::post, Json, Router};
use http::StatusCode;
use rag_agent::{
    anthropic_ask_generator, anthropic_planner, fallback_plan, gemini_ask_generator,
    gemini_planner, grounded_search_query, ollama_ask_generator, ollama_planner,
    openai_ask_generator, openai_planner, AskGenerator, AskSnippet, CacheEvent, GenerationError,
    Planner, TtlCache,
};
use serde_json::{json, Value};
use tokio::{net::TcpListener, sync::Mutex as AsyncMutex};

#[derive(Clone, Default)]
struct CaptureState {
    requests: Arc<AsyncMutex<Vec<(String, Value)>>>,
}

async fn spawn(router: Router) -> String {
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let addr: SocketAddr = listener.local_addr().expect("addr");
    tokio::spawn(async move {
        axum::serve(listener, router).await.expect("serve");
    });
    format!("http://{addr}")
}

fn planner_response_json(answer: &str) -> Value {
    json!({
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "mock",
        "system_fingerprint": null,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": answer
            }
            ,
            "logprobs": null,
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2
        }
    })
}

fn anthropic_response_json(answer: &str) -> Value {
    json!({
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "model": "claude",
        "content": [{
            "type": "text",
            "text": answer
        }],
        "stop_reason": "end_turn",
        "stop_sequence": null,
        "usage": {"input_tokens": 1, "output_tokens": 1}
    })
}

fn gemini_response_json(answer: &str) -> Value {
    json!({
        "responseId": "resp_1",
        "candidates": [{
            "content": {
                "role": "model",
                "parts": [{
                    "text": answer
                }]
            },
            "finishReason": "STOP"
        }],
        "modelVersion": "mock",
        "usageMetadata": {
            "promptTokenCount": 1,
            "candidatesTokenCount": 1,
            "totalTokenCount": 2
        }
    })
}

fn ollama_response_json(answer: &str) -> Value {
    json!({
        "model": "mock",
        "created_at": "2025-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": answer},
        "done": true,
        "done_reason": "stop"
    })
}

fn collect_strings(value: &Value, output: &mut String) {
    match value {
        Value::String(text) => {
            if !output.is_empty() {
                output.push('\n');
            }
            output.push_str(text);
        }
        Value::Array(items) => {
            for item in items {
                collect_strings(item, output);
            }
        }
        Value::Object(map) => {
            for item in map.values() {
                collect_strings(item, output);
            }
        }
        _ => {}
    }
}

fn request_text(value: &Value) -> String {
    let mut output = String::new();
    collect_strings(value, &mut output);
    output
}

async fn openai_chat(
    State(state): State<CaptureState>,
    Json(body): Json<Value>,
) -> impl axum::response::IntoResponse {
    state
        .requests
        .lock()
        .await
        .push(("openai".to_owned(), body.clone()));
    let content = request_text(&body);
    let answer = if content.contains("Code snippets:") {
        json!({
            "answer": "Use [1].",
            "citations": [{"file_path": "src/lib.rs", "lines": "1-3", "name": "Thing", "score": 0.91}],
            "insufficient_context": false
        })
    } else {
        json!({
            "queries": ["payment retry"],
            "filters": {"language": "rust", "patterns": "repository", "evil": "drop"},
            "strategy": "filtered",
            "top_k": 500
        })
    };
    (
        StatusCode::OK,
        Json(planner_response_json(&answer.to_string())),
    )
}

async fn anthropic_messages(
    State(state): State<CaptureState>,
    Json(body): Json<Value>,
) -> impl axum::response::IntoResponse {
    state
        .requests
        .lock()
        .await
        .push(("anthropic".to_owned(), body.clone()));
    let content = request_text(&body);
    let answer = if content.contains("Code snippets:") {
        json!({
            "answer": "The context is not enough.",
            "citations": [],
            "insufficient_context": true
        })
    } else {
        json!({
            "queries": ["auth flow"],
            "filters": {"language": "kotlin", "patterns": ["repository", "invalid"]},
            "strategy": "graph_walk",
            "top_k": 17
        })
    };
    (
        StatusCode::OK,
        Json(anthropic_response_json(&answer.to_string())),
    )
}

async fn gemini_generate(
    State(state): State<CaptureState>,
    axum::extract::OriginalUri(uri): axum::extract::OriginalUri,
    Json(body): Json<Value>,
) -> impl axum::response::IntoResponse {
    state
        .requests
        .lock()
        .await
        .push((format!("gemini:{}", uri.path()), body.clone()));
    let content = request_text(&body);
    let answer = if content.contains("Code snippets:") {
        json!({
            "answer": "INSUFFICIENT_CONTEXT",
            "citations": [],
            "insufficient_context": true
        })
    } else {
        json!({
            "queries": ["cache invalidation"],
            "filters": {"language": ["rust", "python"], "complexity_cyclomatic": 42},
            "strategy": "global",
            "top_k": 10
        })
    };
    (
        StatusCode::OK,
        Json(gemini_response_json(&answer.to_string())),
    )
}

async fn ollama_chat(
    State(state): State<CaptureState>,
    Json(body): Json<Value>,
) -> impl axum::response::IntoResponse {
    state
        .requests
        .lock()
        .await
        .push(("ollama".to_owned(), body.clone()));
    let content = request_text(&body);
    let answer = if content.contains("Code snippets:") {
        json!({
            "answer": "No relevant code found.",
            "citations": [],
            "insufficient_context": true
        })
    } else {
        json!({
            "queries": ["search indexing"],
            "filters": {"language": "rust", "chunk_type": ["function", "property"], "noise": "drop"},
            "strategy": "hybrid",
            "top_k": 11
        })
    };
    (
        StatusCode::OK,
        Json(ollama_response_json(&answer.to_string())),
    )
}

async fn openai_router(state: CaptureState) -> Router {
    Router::new().fallback(post(openai_chat)).with_state(state)
}

async fn anthropic_router(state: CaptureState) -> Router {
    Router::new()
        .fallback(post(anthropic_messages))
        .with_state(state)
}

async fn gemini_router(state: CaptureState) -> Router {
    Router::new()
        .fallback(post(gemini_generate))
        .with_state(state)
}

async fn ollama_router(state: CaptureState) -> Router {
    Router::new().fallback(post(ollama_chat)).with_state(state)
}

#[tokio::test]
async fn planner_adapters_sanitize_and_ground_queries() {
    let state = CaptureState::default();
    let base_url = spawn(openai_router(state.clone()).await).await;
    let planner =
        openai_planner("sk-test-secret", Some(&base_url), "gpt-4o-mini").expect("planner");
    let plan = planner
        .plan_search("find the payment retry path")
        .await
        .expect("plan");
    assert_eq!(plan.strategy, rag_contracts::SearchStrategy::Hybrid);
    assert_eq!(plan.top_k, 200);
    assert_eq!(plan.filters["language"], "rust");
    assert_eq!(plan.filters["patterns"], "repository");
    assert!(!plan.filters.contains_key("evil"));
    assert!(plan.queries.iter().any(|query| query.contains("payment")));

    let symbols = vec!["PaymentRetryManager".to_owned()];
    let grounded = grounded_search_query(
        "find the payment retry path",
        &fallback_plan("find the payment retry path"),
        &symbols,
    );
    assert!(grounded.contains("PaymentRetryManager"));
    assert_ne!(grounded, "find the payment retry path");

    let calls = state.requests.lock().await;
    assert!(!calls.is_empty());
}

#[tokio::test]
async fn ask_generation_returns_citations_and_handles_insufficient_context() {
    let state = CaptureState::default();
    let openai_base = spawn(openai_router(state.clone()).await).await;
    let ollama_base = spawn(ollama_router(state.clone()).await).await;

    let asker = openai_ask_generator("sk-test", Some(&openai_base), "mock").expect("asker");

    let answer = asker
        .answer(
            "What does this snippet do?",
            &[AskSnippet {
                file_path: "src/lib.rs".to_owned(),
                lines: "1-3".to_owned(),
                name: "Thing".to_owned(),
                language: "rust".to_owned(),
                code: "fn thing() {}".to_owned(),
                score: 0.9,
            }],
        )
        .await
        .expect("answer");
    assert!(!answer.insufficient_context);
    assert_eq!(answer.citations.len(), 1);
    assert_eq!(answer.citations[0].file_path, "src/lib.rs");

    let ollama = ollama_ask_generator("unused", Some(&ollama_base), "mock").expect("ollama");
    let insufficient = ollama
        .answer(
            "What does this snippet do?",
            &[AskSnippet {
                file_path: "src/lib.rs".to_owned(),
                lines: "1-3".to_owned(),
                name: "Thing".to_owned(),
                language: "rust".to_owned(),
                code: "fn thing() {}".to_owned(),
                score: 0.9,
            }],
        )
        .await
        .expect("answer");
    assert!(insufficient.insufficient_context);
    assert!(insufficient.citations.is_empty());
}

#[tokio::test]
async fn provider_variants_cover_all_backends() {
    let state = CaptureState::default();

    let openai_base = spawn(openai_router(state.clone()).await).await;
    let anthropic_base = spawn(anthropic_router(state.clone()).await).await;
    let gemini_base = spawn(gemini_router(state.clone()).await).await;
    let ollama_base = spawn(ollama_router(state.clone()).await).await;

    let planners: Vec<(&str, Box<dyn Planner>)> = vec![
        (
            "openai",
            openai_planner("sk-test", Some(&openai_base), "gpt-4o-mini").expect("openai"),
        ),
        (
            "anthropic",
            anthropic_planner("claude-test", Some(&anthropic_base), "claude-3-5-sonnet")
                .expect("anthropic"),
        ),
        (
            "gemini",
            gemini_planner("gemini-test", Some(&gemini_base), "gemini-2.0-flash").expect("gemini"),
        ),
        (
            "ollama",
            ollama_planner("ollama-test", Some(&ollama_base), "mock").expect("ollama"),
        ),
    ];

    for (name, planner) in planners {
        let plan = planner
            .plan_search("find the auth service")
            .await
            .unwrap_or_else(|error| {
                panic!("{name}: {error:?}");
            });
        assert!(!plan.queries.is_empty());
        assert!(plan.top_k <= 200);
    }
}

#[test]
fn anthropic_response_fixture_deserializes() {
    let value = anthropic_response_json("hello world");
    let parsed: rig::providers::anthropic::completion::CompletionResponse =
        serde_json::from_value(value).expect("anthropic fixture");
    assert_eq!(parsed.role, "assistant");
    assert_eq!(parsed.content.len(), 1);

    let structured = json!({
        "answer": "The context is not enough.",
        "citations": [],
        "insufficient_context": true
    });
    let structured_value = anthropic_response_json(&structured.to_string());
    let parsed: rig::providers::anthropic::completion::CompletionResponse =
        serde_json::from_value(structured_value).expect("structured anthropic fixture");
    assert_eq!(parsed.content.len(), 1);
}

#[tokio::test]
async fn ask_generator_variants_cover_all_backends() {
    let state = CaptureState::default();

    let openai_base = spawn(openai_router(state.clone()).await).await;
    let anthropic_base = spawn(anthropic_router(state.clone()).await).await;
    let gemini_base = spawn(gemini_router(state.clone()).await).await;
    let ollama_base = spawn(ollama_router(state.clone()).await).await;

    let generators: Vec<(&str, Box<dyn AskGenerator>)> = vec![
        (
            "openai",
            openai_ask_generator("sk-test", Some(&openai_base), "gpt-4o-mini").expect("openai"),
        ),
        (
            "anthropic",
            anthropic_ask_generator("claude-test", Some(&anthropic_base), "claude-3-5-sonnet")
                .expect("anthropic"),
        ),
        (
            "gemini",
            gemini_ask_generator("gemini-test", Some(&gemini_base), "gemini-2.0-flash")
                .expect("gemini"),
        ),
        (
            "ollama",
            ollama_ask_generator("ollama-test", Some(&ollama_base), "mock").expect("ollama"),
        ),
    ];

    let snippets = [AskSnippet {
        file_path: "src/lib.rs".to_owned(),
        lines: "1-3".to_owned(),
        name: "Thing".to_owned(),
        language: "rust".to_owned(),
        code: "fn thing() {}".to_owned(),
        score: 0.9,
    }];

    let mut observed_insufficient = 0;
    for (name, generator) in generators {
        let answer = generator
            .answer("What does this snippet do?", &snippets)
            .await
            .unwrap_or_else(|error| panic!("{name}: {error:?}"));
        if answer.insufficient_context {
            observed_insufficient += 1;
            assert!(answer.citations.is_empty());
        } else {
            assert_eq!(answer.citations.len(), 1);
        }
    }
    assert!(observed_insufficient >= 2);
}

#[test]
fn secrets_are_redacted_from_errors() {
    let err =
        GenerationError::provider("openai", "Bearer sk-secret-12345 token=abc123 api_key=xyz");
    let rendered = err.to_string();
    assert!(!rendered.contains("sk-secret-12345"));
    assert!(!rendered.contains("abc123"));
    assert!(rendered.contains("<redacted>"));
}

#[test]
fn ttl_cache_invalidates_and_emits_hooks() {
    let events = Arc::new(Mutex::new(Vec::new()));
    let cache = TtlCache::new(Duration::from_millis(20)).with_hook({
        let events = Arc::clone(&events);
        move |key: &String, value: &usize, event| {
            events
                .lock()
                .expect("events")
                .push((key.clone(), *value, event));
        }
    });

    cache.insert("alpha".to_owned(), 1);
    assert_eq!(cache.get(&"alpha".to_owned()), Some(1));
    cache.insert("alpha".to_owned(), 2);
    assert_eq!(cache.invalidate(&"alpha".to_owned()), Some(2));

    cache.insert("beta".to_owned(), 3);
    std::thread::sleep(Duration::from_millis(30));
    assert_eq!(cache.get(&"beta".to_owned()), None);

    cache.insert("gamma".to_owned(), 4);
    cache.clear();

    let events = events.lock().expect("events");
    assert!(events
        .iter()
        .any(|(_, _, event)| *event == CacheEvent::Replaced));
    assert!(events
        .iter()
        .any(|(_, _, event)| *event == CacheEvent::Invalidated));
    assert!(events
        .iter()
        .any(|(_, _, event)| *event == CacheEvent::Expired));
    assert!(events
        .iter()
        .any(|(_, _, event)| *event == CacheEvent::Cleared));
}

#[cfg(unix)]
#[tokio::test]
async fn agy_timeout_cleans_up_process_tree() {
    use std::os::unix::fs::PermissionsExt;

    let temp_dir = std::env::temp_dir().join(format!("rag-agent-agy-{}", std::process::id()));
    let _ = fs::create_dir_all(&temp_dir);
    let script = temp_dir.join("agy");
    let pid_file = temp_dir.join("child.pid");
    fs::write(
        &script,
        format!(
            "#!/bin/sh\nsleep 30 &\nchild=$!\necho $child > \"{}\"\nwait $child\n",
            pid_file.display()
        ),
    )
    .expect("script");
    let mut perms = fs::metadata(&script).expect("metadata").permissions();
    perms.set_mode(0o755);
    fs::set_permissions(&script, perms).expect("permissions");

    let planner = rag_agent::AgyPlanner::new("mock-model")
        .with_executable(script.display().to_string())
        .with_timeout(Duration::from_millis(500));

    let err = planner.plan_search("find auth").await.expect_err("timeout");
    assert!(matches!(err, rag_agent::PlannerError::Timeout));

    let child_pid = fs::read_to_string(&pid_file).expect("pid file");
    let child_pid = child_pid.trim().parse::<i32>().expect("pid");
    let probe = std::process::Command::new("kill")
        .arg("-0")
        .arg(child_pid.to_string())
        .status()
        .expect("kill probe");
    assert!(
        !probe.success(),
        "background child should be gone after timeout"
    );
}
