use axum::body::{to_bytes, Body};
use http::{header, Request, StatusCode};
use serde_json::Value;
use tower::ServiceExt;

#[tokio::test]
async fn every_captured_python_route_exists_in_rust() {
    let contract: Value =
        serde_json::from_str(include_str!("../../../tests/contracts/openapi.json")).unwrap();
    for (path, operations) in contract["paths"].as_object().unwrap() {
        for method in operations.as_object().unwrap().keys() {
            if !matches!(method.as_str(), "get" | "post") {
                continue;
            }
            let uri = path.replace("{job_id}", "missing-job");
            let mut request = Request::builder()
                .method(method.to_ascii_uppercase().parse::<http::Method>().unwrap())
                .uri(uri)
                .header(header::HOST, "127.0.0.1:7891");
            let body = if method == "post" {
                request = request.header(header::CONTENT_TYPE, "application/json");
                Body::from("{}")
            } else {
                Body::empty()
            };
            let response = rag_server::router()
                .oneshot(request.body(body).unwrap())
                .await
                .unwrap();
            assert_ne!(
                response.status(),
                StatusCode::NOT_FOUND,
                "missing {method} {path}"
            );
            assert_ne!(
                response.status(),
                StatusCode::METHOD_NOT_ALLOWED,
                "wrong method {method} {path}"
            );
        }
    }
}

#[tokio::test]
async fn dashboard_is_embedded_in_the_binary() {
    let response = rag_server::router()
        .oneshot(
            Request::builder()
                .uri("/")
                .header(header::HOST, "localhost:7891")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response.headers()[header::CONTENT_TYPE],
        "text/html; charset=utf-8"
    );
}

/// Copy the checked-in fixture home into a temp dir. Serving a request against
/// it appends to `logs/daemon.jsonl` (and SQLite may drop sidecar files), which
/// would leave the fixture — and the working tree — dirty after every run.
fn fixture_rag_home() -> tempfile::TempDir {
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/rust-compat/r1/python-rag-home");
    let temp = tempfile::tempdir().expect("tempdir");
    copy_tree(&source, temp.path());
    temp
}

fn copy_tree(from: &std::path::Path, to: &std::path::Path) {
    std::fs::create_dir_all(to).expect("create fixture dir");
    for entry in std::fs::read_dir(from).expect("read fixture dir") {
        let entry = entry.expect("fixture entry");
        let target = to.join(entry.file_name());
        if entry.file_type().expect("fixture file type").is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), &target).expect("copy fixture file");
        }
    }
}

/// `/stack` must carry an `ast_index` service card: the external `ast-index`
/// CLI backs every symbol-exact route, and when it is missing those routes
/// return empty results instead of failing — so the dashboards have to say so.
#[tokio::test]
async fn stack_reports_the_external_ast_index_cli() {
    let rag_home = tempfile::tempdir().unwrap();
    let app = rag_server::router_with_state(
        rag_server::ServerState::new(None).with_rag_home(rag_home.path()),
    );
    let response = app
        .oneshot(
            Request::builder()
                .uri("/stack")
                .header(header::HOST, "localhost:7891")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let value: Value =
        serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap()).unwrap();
    for card in ["ollama", "docker", "qdrant", "ast_index"] {
        assert!(value.get(card).is_some(), "missing {card} card");
    }
    let ast_index = &value["ast_index"];
    assert_eq!(ast_index["name"], "AST-INDEX");
    assert!(["ok", "warn"].contains(&ast_index["state"].as_str().unwrap()));
    assert!(!ast_index["headline"].as_str().unwrap().is_empty());
    if ast_index["state"] == "warn" {
        assert!(ast_index["hint"].as_str().unwrap().contains("ast-index"));
    }
}

#[tokio::test]
async fn live_search_reads_a_copied_python_created_database() {
    // Held for the whole test: dropping it deletes the copied home.
    let rag_home = fixture_rag_home();
    let app = rag_server::router_with_state(
        rag_server::ServerState::new(None).with_rag_home(rag_home.path()),
    );
    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/search")
                .header(header::HOST, "localhost:7891")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(
                    r#"{"query":"require auth","repo":"fixture","top_k":5}"#,
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let value: Value =
        serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap()).unwrap();
    assert_eq!(value["total"], 1);
    assert_eq!(value["results"][0]["file_path"], "src/rag/server.py");
    assert_eq!(value["results"][0]["name"], "require_auth");
}

#[tokio::test]
async fn rust_index_then_named_repo_search_needs_no_python() {
    let temp = tempfile::tempdir().unwrap();
    let repo = temp.path().join("repo");
    let rag_home = temp.path().join("rag-home");
    std::fs::create_dir_all(&repo).unwrap();
    std::fs::write(
        repo.join("auth.rs"),
        "pub fn verify_bearer(token: &str) -> bool { !token.is_empty() }",
    )
    .unwrap();
    let app =
        rag_server::router_with_state(rag_server::ServerState::new(None).with_rag_home(&rag_home));
    let index = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/index")
                .header(header::HOST, "localhost:7891")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(format!(
                    r#"{{"repo_path":{},"repo_name":"sample","collection":"repo_sample","full":true}}"#,
                    serde_json::to_string(&repo).unwrap()
                )))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(index.status(), StatusCode::OK);

    let search = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/search")
                .header(header::HOST, "localhost:7891")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(
                    r#"{"query":"verify bearer","repo":"sample","top_k":5}"#,
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(search.status(), StatusCode::OK);
    let value: Value =
        serde_json::from_slice(&to_bytes(search.into_body(), usize::MAX).await.unwrap()).unwrap();
    assert!(value["total"].as_u64().unwrap() >= 1);
    assert_eq!(value["results"][0]["file_path"], "auth.rs");

    for (path, body) in [
        (
            "/smart-search",
            r#"{"question":"where is verify_bearer","repo":"sample"}"#,
        ),
        (
            "/project-understand",
            r#"{"query":"bearer auth","repo":"sample"}"#,
        ),
        (
            "/graph/affected",
            r#"{"repo":"sample","files":["auth.rs"]}"#,
        ),
        (
            "/enumerate",
            r#"{"repo":"sample","filters":{"language":"rust"},"limit":20}"#,
        ),
    ] {
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri(path)
                    .header(header::HOST, "localhost:7891")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(body))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK, "failed {path}");
    }

    std::fs::write(
        repo.join("README.md"),
        "Bearer tokens protect every API request.",
    )
    .unwrap();
    let docs_index = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/index/docs")
                .header(header::HOST, "localhost:7891")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(format!(
                    r#"{{"docs_path":{},"full":true}}"#,
                    serde_json::to_string(&repo).unwrap()
                )))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(docs_index.status(), StatusCode::OK);
    let docs_search = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/docs-search")
                .header(header::HOST, "localhost:7891")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(r#"{"query":"bearer tokens"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(docs_search.status(), StatusCode::OK);
    let value: Value =
        serde_json::from_slice(&to_bytes(docs_search.into_body(), usize::MAX).await.unwrap())
            .unwrap();
    assert!(value["total"].as_u64().unwrap() >= 1);
}
