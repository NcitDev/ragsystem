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
    assert_eq!(settings.embeddings.dim, 4096);
    assert_eq!(settings.index.retrieval_top_k, 7);
    assert_eq!(settings.qdrant.url, "http://127.0.0.1:6333");
    assert_eq!(settings.qdrant.code_collection, "code_chunks");
    assert_eq!(settings.retrieval_agent.model, "Gemini 3.5 Flash (High)");
}

/// Replica of `OllamaClient::model_is_present` (`crates/rag-services/src/
/// ollama.rs`). `rag-config` sits below `rag-services` in the workspace graph
/// and cannot depend on it, so the matching rule is mirrored here — keep the
/// two in step.
fn model_is_present(configured: &str, served_tags: &[&str]) -> bool {
    let short = configured
        .rsplit('/')
        .next()
        .unwrap_or(configured)
        .to_ascii_lowercase();
    served_tags
        .iter()
        .any(|tag| tag.to_ascii_lowercase().contains(&short))
}

/// A fresh install must work without editing `~/.rag/config.toml`.
///
/// The packaged default used to ship the HuggingFace repo name
/// `Qwen/Qwen3-Embedding-4B`. `model_is_present` keeps only the segment after
/// the last `/` — `qwen3-embedding-4b` — which no served Ollama tag contains,
/// so `health()` returned false and `/health` reported `ollama: unavailable`
/// while Ollama was running perfectly. Reintroducing a HF-style name (or
/// desyncing `dim` from the shipped tag) must fail here.
#[test]
fn packaged_default_embedding_model_is_an_ollama_tag_not_a_huggingface_path() {
    // No config.toml in this home: exactly what a fresh install resolves.
    let temp = tempfile::tempdir().expect("tempdir");
    let paths = RagPaths::from_home(temp.path().join("fresh-rag-home"));

    let settings = load_settings(&paths).expect("packaged defaults load");
    let model = settings.embeddings.model.clone();

    assert!(
        !model.contains('/'),
        "embeddings.model {model:?} looks like a HuggingFace repo path; it must \
         be a tag as printed by `ollama list`"
    );
    assert!(
        !model.is_empty() && model == model.to_ascii_lowercase(),
        "embeddings.model {model:?} is not a lowercase Ollama tag"
    );

    // The daemon's availability probe, run against a realistic `ollama list`
    // for a user who followed the documented `ollama pull qwen3-embedding`.
    let served = ["qwen3-embedding:latest", "qwen3:8b"];
    assert!(
        model_is_present(&model, &served),
        "packaged embeddings.model {model:?} is not matched by the served tags \
         {served:?}; /health would report `ollama: unavailable` on a fresh \
         install that followed the documented pull"
    );
    // Guard the guard: the rule really does reject the old HF-style name.
    assert!(
        !model_is_present("Qwen/Qwen3-Embedding-4B", &served),
        "model_is_present replica no longer matches rag-services"
    );

    // Qdrant collections are created with `dim` at the first index, so a
    // mismatch corrupts an index instead of erroring. Changing the shipped tag
    // requires stating the width it returns.
    let expected_dim = match model.as_str() {
        "qwen3-embedding:latest" | "qwen3-embedding:8b" => 4096,
        "qwen3-embedding:4b" => 2560,
        "qwen3-embedding:0.6b" => 1024,
        other => panic!(
            "no known vector width for packaged embeddings.model {other:?}; \
             verify it with `curl -s localhost:11434/api/embed -d \
             '{{\"model\":\"{other}\",\"input\":\"x\"}}' | jq \
             '.embeddings[0]|length'` and record it here"
        ),
    };
    assert_eq!(
        settings.embeddings.dim, expected_dim,
        "embeddings.dim must match the width {model:?} actually returns"
    );
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
