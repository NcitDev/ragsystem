use std::fs;
use std::path::{Path, PathBuf};

use rag_config::{
    get_or_create_token, load_env_files, load_settings, parse_bearer, verify_bearer_header,
    RagPaths,
};

fn fixture_home() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/rust-compat/r1/python-rag-home")
}

fn copy_dir(src: &Path, dst: &Path) {
    fs::create_dir_all(dst).expect("create fixture copy");
    for entry in fs::read_dir(src).expect("read fixture dir") {
        let entry = entry.expect("fixture entry");
        let ty = entry.file_type().expect("fixture type");
        let to = dst.join(entry.file_name());
        if ty.is_dir() {
            copy_dir(&entry.path(), &to);
        } else {
            fs::copy(entry.path(), to).expect("copy fixture file");
        }
    }
}

#[test]
fn loads_packaged_defaults_deep_merged_with_python_user_toml() {
    let temp = tempfile::tempdir().expect("tempdir");
    let rag_home = temp.path().join("rag-home");
    copy_dir(&fixture_home(), &rag_home);
    let paths = RagPaths::from_home(&rag_home);

    let settings = load_settings(&paths).expect("settings load");

    assert_eq!(settings.server.host, "192.168.1.10");
    assert_eq!(settings.server.port, 8080);
    assert_eq!(settings.embeddings.dim, 2560);
    assert_eq!(settings.index.retrieval_top_k, 7);
    assert_eq!(settings.qdrant.url, "http://127.0.0.1:6333");
    assert_eq!(settings.qdrant.code_collection, "code_chunks");
    assert_eq!(settings.retrieval_agent.model, "Gemini 3.5 Flash (High)");
}

#[test]
fn token_reader_preserves_existing_python_token_and_auth_rules() {
    let temp = tempfile::tempdir().expect("tempdir");
    let rag_home = temp.path().join("rag-home");
    copy_dir(&fixture_home(), &rag_home);
    let paths = RagPaths::from_home(&rag_home);

    let token = get_or_create_token(&paths).expect("token");

    assert_eq!(token, "python-created-token");
    assert_eq!(
        parse_bearer("Bearer python-created-token"),
        Some("python-created-token")
    );
    assert_eq!(
        parse_bearer("BEARER a token with spaces"),
        Some("a token with spaces")
    );
    assert!(verify_bearer_header(
        Some("bearer python-created-token"),
        &token
    ));
    assert!(!verify_bearer_header(Some("Bearer wrong"), &token));
}

#[test]
fn token_creation_uses_explicit_home_not_real_dot_rag() {
    let temp = tempfile::tempdir().expect("tempdir");
    let paths = RagPaths::from_home(temp.path().join("isolated-rag-home"));

    let token = get_or_create_token(&paths).expect("token");

    assert_eq!(token.len(), 43);
    assert_eq!(
        fs::read_to_string(paths.token_path).expect("read token"),
        token
    );
}

#[test]
fn dotenv_loading_keeps_existing_env_and_uses_user_then_project_files() {
    let temp = tempfile::tempdir().expect("tempdir");
    let rag_home = temp.path().join("rag-home");
    let project = temp.path().join("project").join("nested");
    fs::create_dir_all(&rag_home).expect("rag home");
    fs::create_dir_all(&project).expect("project");
    fs::write(
        rag_home.join(".env"),
        "RAG_R1_USER_ONLY=user\nRAG_R1_SHARED=user\n",
    )
    .expect("write user env");
    fs::write(
        temp.path().join("project").join(".env"),
        "RAG_R1_PROJECT_ONLY=project\nRAG_R1_SHARED=project\n",
    )
    .expect("write project env");
    std::env::remove_var("RAG_R1_USER_ONLY");
    std::env::remove_var("RAG_R1_PROJECT_ONLY");
    std::env::remove_var("RAG_R1_SHARED");

    let loaded = load_env_files(&RagPaths::from_home(&rag_home), &project).expect("load env");

    assert_eq!(loaded.len(), 2);
    assert_eq!(std::env::var("RAG_R1_USER_ONLY").as_deref(), Ok("user"));
    assert_eq!(
        std::env::var("RAG_R1_PROJECT_ONLY").as_deref(),
        Ok("project")
    );
    assert_eq!(std::env::var("RAG_R1_SHARED").as_deref(), Ok("user"));
}
