use std::collections::BTreeMap;

use rag_index::{
    chunker::{language_config, ChunkType},
    diff_index_state, discover_files, file_hash, file_hash_bounded,
    graph::GraphRelation,
    lexical::CodeDocument,
    AstGraph, GraphNode, IndexState, LexicalIndex, VocabRecord,
};
use tempfile::tempdir;

#[test]
fn discovery_hash_and_diff_are_deterministic() {
    let repo = tempdir().expect("temp repo");
    // Python `_discover_files` does NOT consult .gitignore — it indexes
    // tracked files under gitignored paths (verified against a real
    // Python-produced state.json that includes .idea/fileTemplates).
    // Only `skip_dirs` and the extension filter exclude files.
    std::fs::write(repo.path().join(".gitignore"), "ignored/\n").expect("gitignore");
    std::fs::create_dir(repo.path().join("src")).expect("src dir");
    std::fs::create_dir(repo.path().join("ignored")).expect("ignored dir");
    std::fs::create_dir(repo.path().join(".venv")).expect("skip dir");
    std::fs::write(
        repo.path().join("src/lib.py"),
        "def live():\n    return 1\n",
    )
    .expect("source");
    std::fs::write(repo.path().join("ignored/drop.py"), "def drop(): pass\n").expect("ignored");
    std::fs::write(repo.path().join(".venv/skipped.py"), "def skip(): pass\n").expect("skipped");

    let files = discover_files(repo.path(), Some(&[".py"]), &[".venv"]).expect("discover");
    let rels: Vec<_> = files
        .iter()
        .map(|path| {
            path.strip_prefix(repo.path())
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/")
        })
        .collect();
    assert_eq!(rels, vec!["ignored/drop.py", "src/lib.py"]);

    let lib_file = files
        .iter()
        .find(|path| path.ends_with("src/lib.py"))
        .expect("lib file discovered");
    let mut current = BTreeMap::new();
    current.insert("src/lib.py".to_owned(), file_hash(lib_file).expect("hash"));
    let previous = IndexState {
        last_commit: "old".to_owned(),
        file_hashes: BTreeMap::from([
            ("src/lib.py".to_owned(), "different".to_owned()),
            ("src/deleted.py".to_owned(), "gone".to_owned()),
        ]),
    };
    let diff = diff_index_state(&previous, &current);
    assert_eq!(diff.changed, vec!["src/lib.py"]);
    assert_eq!(diff.deleted, vec!["src/deleted.py"]);
}

#[test]
fn bounded_hash_refuses_oversized_source_files() {
    let repo = tempdir().expect("temp repo");
    let path = repo.path().join("large.rs");
    std::fs::write(&path, b"123456").expect("large fixture");

    let error = file_hash_bounded(&path, 5).expect_err("limit must be enforced");
    assert!(error.to_string().contains("5-byte limit"));
}

#[cfg(unix)]
#[test]
fn discovery_never_follows_source_symlinks_outside_the_repository() {
    use std::os::unix::fs::symlink;

    let repo = tempdir().expect("temp repo");
    let outside = tempdir().expect("outside dir");
    let secret = outside.path().join("secret.rs");
    std::fs::write(&secret, "const API_KEY: &str = \"secret\";").expect("secret fixture");
    symlink(&secret, repo.path().join("linked.rs")).expect("source symlink");
    std::fs::write(repo.path().join("safe.rs"), "fn safe() {}").expect("safe source");

    let files = discover_files(repo.path(), Some(&[".rs"]), &[]).expect("discover");
    assert_eq!(files, vec![repo.path().join("safe.rs")]);
    assert!(rag_index::read_file_bounded(repo.path().join("linked.rs"), 1024).is_err());
}

#[test]
fn tree_sitter_chunks_preserve_python_contract_shape() {
    let source = include_str!("fixtures/sample.py");
    let chunks = rag_index::chunk_code(source, "src/sample.py", Some("python"), 8192);
    assert!(chunks
        .iter()
        .any(|chunk| chunk.chunk_type == ChunkType::FileSummary));
    let class = chunks
        .iter()
        .find(|chunk| chunk.chunk_type == ChunkType::ClassDeclaration && chunk.name == "Greeter")
        .expect("class chunk");
    assert_eq!(class.start_line, 4);
    assert!(class.metadata.contains_key("name_line"));

    let method = chunks
        .iter()
        .find(|chunk| chunk.chunk_type == ChunkType::Method && chunk.name == "hello")
        .expect("method chunk");
    assert_eq!(method.parent_name, "Greeter");
    assert!(method
        .content
        .starts_with("# File: src/sample.py\n# Class: Greeter\n# Language: python"));
    assert_eq!(method.chunk_id().len(), 16);
    assert_eq!(method.content_hash().len(), 16);
}

#[test]
fn tree_sitter_chunks_cover_dart_with_the_rust_grammar() {
    let source = include_str!("fixtures/sample.dart");
    let chunks = rag_index::chunk_code(source, "src/sample.dart", Some("dart"), 8192);
    assert!(chunks
        .iter()
        .any(|chunk| chunk.chunk_type == ChunkType::FileSummary));
    let class = chunks
        .iter()
        .find(|chunk| chunk.chunk_type == ChunkType::ClassDeclaration && chunk.name == "Greeter")
        .expect("dart class chunk");
    assert!(class.content.contains("class Greeter"));
    let method = chunks
        .iter()
        .find(|chunk| chunk.chunk_type == ChunkType::Method && chunk.name == "hello")
        .expect("dart method chunk");
    assert_eq!(method.parent_name, "Greeter");
    assert!(method.content.contains("String hello(String name)"));
}

#[test]
fn maintained_rust_grammar_contracts_are_explicit_and_dart_is_blocked() {
    for language in [
        "python",
        "java",
        "kotlin",
        "typescript",
        "javascript",
        "go",
        "rust",
        "c",
        "cpp",
        "dart",
    ] {
        let config = language_config(language).expect("language config");
        assert!(
            config.available_in_rust,
            "{language} should be backed by a Rust grammar"
        );
        assert!(!config.extensions.is_empty());
    }
    let dart = language_config("dart").expect("dart config");
    assert!(dart.available_in_rust);
    assert!(dart.parity_note.contains("maintained"));

    let report: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/dart-parity.json")).expect("json report");
    assert_eq!(report["rust_status"], "resolved");
}

#[test]
fn lexical_sqlite_mirror_supports_upsert_search_and_delete() {
    let mut index = LexicalIndex::in_memory().expect("index");
    let docs = vec![CodeDocument {
        chunk_id: "chunk-a".to_owned(),
        collection: "code_chunks".to_owned(),
        file_path: "src/sample.py".to_owned(),
        name: "build_message".to_owned(),
        parent_name: String::new(),
        chunk_type: "function".to_owned(),
        language: "python".to_owned(),
        start_line: 8,
        end_line: 9,
        code: "def build_message(name):\n    return Greeter().hello(name)".to_owned(),
    }];
    assert_eq!(index.upsert_code_chunks(&docs).expect("upsert"), 1);
    let hits = index
        .search_code_chunks("build_message Greeter", Some("code_chunks"), 5)
        .expect("search");
    assert_eq!(hits[0].chunk_id, "chunk-a");
    assert_eq!(hits[0].lines, "8-9");
    assert!(hits[0].citation.contains("src/sample.py:8-9"));

    let replacement = vec![CodeDocument {
        chunk_id: "chunk-b".to_owned(),
        collection: "code_chunks".to_owned(),
        file_path: "src/sample.py".to_owned(),
        name: "render_message".to_owned(),
        parent_name: String::new(),
        chunk_type: "function".to_owned(),
        language: "python".to_owned(),
        start_line: 20,
        end_line: 22,
        code: "def render_message(name):\n    return name".to_owned(),
    }];
    assert_eq!(
        index
            .replace_code_chunks_for_file("code_chunks", "src/sample.py", &replacement)
            .expect("replace"),
        1
    );
    assert!(index
        .search_code_chunks("build_message", Some("code_chunks"), 5)
        .expect("old chunk removed")
        .is_empty());
    assert_eq!(
        index
            .search_code_chunks("render_message", Some("code_chunks"), 5)
            .expect("replacement searchable")[0]
            .chunk_id,
        "chunk-b"
    );

    index
        .delete_code_chunks_by_file("code_chunks", "src/sample.py")
        .expect("delete");
    assert!(index
        .search_code_chunks("build_message", Some("code_chunks"), 5)
        .expect("search after delete")
        .is_empty());
}

#[test]
fn graph_and_vocab_records_are_stable_json_contracts() {
    let mut graph = AstGraph::default();
    graph.upsert_node(GraphNode {
        id: "src/sample.py:build_message".to_owned(),
        file_path: "src/sample.py".to_owned(),
        name: "build_message".to_owned(),
        parent_name: String::new(),
        chunk_type: "function".to_owned(),
        language: "python".to_owned(),
        patterns: vec![],
        domains: vec![],
    });
    graph.upsert_node(GraphNode {
        id: "src/sample.py:Greeter.hello".to_owned(),
        file_path: "src/sample.py".to_owned(),
        name: "hello".to_owned(),
        parent_name: "Greeter".to_owned(),
        chunk_type: "method".to_owned(),
        language: "python".to_owned(),
        patterns: vec![],
        domains: vec![],
    });
    graph.add_edge(
        "src/sample.py:build_message",
        "src/sample.py:Greeter.hello",
        GraphRelation::Calls,
    );

    assert_eq!(
        graph.callees("src/sample.py:build_message"),
        vec!["src/sample.py:Greeter.hello"]
    );
    let encoded = serde_json::to_string(&graph).expect("graph json");
    assert!(encoded.contains("\"relation\":\"calls\""));

    let vocab = VocabRecord::new("repo", "src/sample.py", "Greeter builds greeting messages.");
    assert_eq!(vocab.chunk_id, "repo:vocab:src/sample.py");
    assert_eq!(vocab.name, "sample");
    assert_eq!(vocab.chunk_type, "vocab_summary");
    assert_eq!(vocab.content_hash.len(), 16);
}
