use std::fs;
use std::path::{Path, PathBuf};

use rag_config::RagPaths;
use rag_storage::{
    state_file_for, EventEntry, EventRing, IndexState, RagDatabase, RepoInfo, RepoRegistry,
    StorageError,
};
use serde_json::json;

fn fixture_home() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/rust-compat/r1/python-rag-home")
}

fn fixture_state() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/rust-compat/r1/python-state.json")
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
fn reads_python_repo_registry_read_only() {
    let temp = tempfile::tempdir().expect("tempdir");
    let rag_home = temp.path().join("rag-home");
    copy_dir(&fixture_home(), &rag_home);
    let registry = RepoRegistry::open(&RagPaths::from_home(&rag_home)).expect("open registry");

    let repos = registry.list_repos().expect("list repos");
    let repo = registry.get("fixture").expect("get repo").expect("repo");

    assert_eq!(repos, vec![repo.clone()]);
    assert_eq!(repo.collection, "repo_fixture");
    assert_eq!(repo.chunks_count, 2);
}

#[test]
fn reads_python_index_state_without_migrating_or_writing() {
    let temp = tempfile::tempdir().expect("tempdir");
    let paths = RagPaths::from_home(temp.path().join("rag-home"));
    let repo = temp.path().join("repo");
    fs::create_dir_all(&repo).expect("repo dir");
    let state_path = state_file_for(&paths, &repo);
    fs::create_dir_all(state_path.parent().expect("state parent")).expect("state dir");
    fs::copy(fixture_state(), &state_path).expect("copy state");

    let state = IndexState::load(&paths, &repo).expect("load state");

    assert_eq!(state.last_commit, "abc123fixture");
    assert_eq!(
        state.file_hashes.get("src/lib.rs").map(String::as_str),
        Some("1111222233334444")
    );
}

#[test]
fn reads_python_rag_db_schema_and_rows() {
    let temp = tempfile::tempdir().expect("tempdir");
    let rag_home = temp.path().join("rag-home");
    copy_dir(&fixture_home(), &rag_home);
    let db = RagDatabase::open(&RagPaths::from_home(&rag_home)).expect("open db");

    let tables = db.table_names().expect("tables");
    let queries = db.recent_queries(10).expect("queries");
    let chunks = db.code_chunks("repo_fixture", 10).expect("chunks");

    assert_eq!(db.user_version().expect("version"), 0);
    assert!(tables.contains(&"query_log".to_owned()));
    assert!(tables.contains(&"code_index".to_owned()));
    assert_eq!(queries[0].query, "require_auth token");
    assert_eq!(chunks[0].name, "require_auth");
    assert_eq!(chunks[0].file_path, "src/rag/server.py");
}

#[test]
fn refuses_newer_sqlite_schema_version() {
    let temp = tempfile::tempdir().expect("tempdir");
    let db_path = temp.path().join("future.db");
    {
        let conn = rusqlite::Connection::open(&db_path).expect("create db");
        conn.pragma_update(None, "user_version", 999)
            .expect("set version");
    }

    let error = match RagDatabase::open_path(&db_path) {
        Ok(_) => panic!("future schema should be refused"),
        Err(error) => error,
    };

    assert!(matches!(
        error,
        StorageError::UnsupportedSchemaVersion {
            found: 999,
            supported: 0
        }
    ));
}

#[test]
fn event_ring_trims_and_filters_like_python_recent_events() {
    let mut ring = EventRing::new(3);
    for i in 0..5 {
        ring.push(EventEntry {
            ts: f64::from(i),
            event: format!("event_{i}"),
            fields: [("path".to_owned(), json!(format!("file_{i}.rs")))].into(),
        });
    }

    let recent = ring.recent(2, 0.0);
    let after = ring.recent(10, 3.0);

    assert_eq!(
        recent
            .iter()
            .map(|event| event.event.as_str())
            .collect::<Vec<_>>(),
        vec!["event_3", "event_4"]
    );
    assert_eq!(
        after
            .iter()
            .map(|event| event.event.as_str())
            .collect::<Vec<_>>(),
        vec!["event_4"]
    );
}

#[test]
fn writable_registry_preserves_the_python_schema() {
    let temp = tempfile::tempdir().expect("temp home");
    let paths = RagPaths::from_home(temp.path());
    let registry = RepoRegistry::open_writable(&paths).expect("writable registry");
    registry
        .upsert(&RepoInfo {
            name: "fixture".to_owned(),
            path: "/tmp/fixture".to_owned(),
            collection: "repo_fixture".to_owned(),
            last_indexed: Some("now".to_owned()),
            chunks_count: 3,
        })
        .expect("upsert repository");
    assert_eq!(registry.get("fixture").unwrap().unwrap().chunks_count, 3);
}
