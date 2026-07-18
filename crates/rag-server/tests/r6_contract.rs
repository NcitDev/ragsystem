use axum::body::{to_bytes, Body};
use http::{header, Request, StatusCode};
use serde_json::Value;
use tower::ServiceExt;

fn materialize_python_fixture() -> tempfile::TempDir {
    let temp = tempfile::tempdir().expect("temporary Python fixture home");
    let home = temp.path();
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/rust-compat/r1/python-rag-home");
    std::fs::copy(source.join("config.toml"), home.join("config.toml"))
        .expect("copy fixture config");
    std::fs::copy(source.join("token"), home.join("token")).expect("copy fixture token");
    for (name, sql) in [
        (
            "repos.db",
            include_str!("../../../tests/rust-compat/r1/repos.sql"),
        ),
        (
            "rag.db",
            include_str!("../../../tests/rust-compat/r1/rag.sql"),
        ),
    ] {
        rusqlite::Connection::open(home.join(name))
            .and_then(|connection| connection.execute_batch(sql))
            .unwrap_or_else(|error| panic!("materialize {name}: {error}"));
    }
    temp
}

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

#[tokio::test]
async fn live_search_reads_a_copied_python_created_database() {
    let fixture = materialize_python_fixture();
    let app = rag_server::router_with_state(
        rag_server::ServerState::new(None).with_rag_home(fixture.path()),
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
    let index_value: Value =
        serde_json::from_slice(&to_bytes(index.into_body(), usize::MAX).await.unwrap()).unwrap();
    assert_eq!(index_value["index_mode"], "lexical_only");
    assert_eq!(index_value["dense_indexed"], false);

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
