//! Port of Python `chunker._detect_kotlin_java_coroutines` and its helpers:
//! cheap text-level enrichment producing string-typed flags suitable for the
//! Qdrant KEYWORD payload indexes. Kotlin and Java are covered (the languages
//! the current deployment indexes); other languages keep chunker metadata.

use std::collections::BTreeMap;
use std::sync::OnceLock;

use regex::Regex;
use serde_json::{json, Value};

use crate::chunker::Chunk;

const KOTLIN_COROUTINE_BUILDERS: [&str; 12] = [
    "launch",
    "async",
    "withContext",
    "runBlocking",
    "coroutineScope",
    "supervisorScope",
    "flow {",
    ".collect",
    "delay(",
    "awaitAll",
    "asFlow",
    "channelFlow",
];

const JAVA_ASYNC_BUILDERS: [&str; 8] = [
    "CompletableFuture",
    "ExecutorService",
    "Executors.",
    "submit(",
    "supplyAsync",
    "runAsync",
    "thenApply",
    "thenCompose",
];

fn regex_cached(cell: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    cell.get_or_init(|| Regex::new(pattern).expect("static enrichment regex"))
}

macro_rules! static_regex {
    ($pattern:expr) => {{
        static CELL: OnceLock<Regex> = OnceLock::new();
        regex_cached(&CELL, $pattern)
    }};
}

/// Enrich a chunk in place, mirroring Python `Chunk.enrich_metadata`:
/// `patterns.py` analysis for Python sources, coroutine/DI detection for
/// Kotlin/Java. Uses `source_text` (raw parseable code) like Python.
pub fn enrich_chunk_metadata(
    chunk: &mut Chunk,
    test_files: Option<&std::collections::BTreeSet<String>>,
) {
    let source = if chunk.source_text.is_empty() {
        chunk.content.clone()
    } else {
        chunk.source_text.clone()
    };
    if source.is_empty() {
        return;
    }
    let language = chunk.language.as_str();
    if language == "python" {
        let enriched =
            crate::enrich_python::detect_python_patterns(&source, &chunk.name, test_files);
        for (key, value) in enriched {
            chunk.metadata.insert(key, value);
        }
        return;
    }
    if language != "kotlin" && language != "java" {
        return;
    }
    let enriched = detect_kotlin_java(&source, language);
    for (key, value) in enriched {
        if key == "inherits_from" {
            if let (Some(existing), Some(new_values)) = (
                chunk
                    .metadata
                    .get("inherits_from")
                    .and_then(Value::as_array)
                    .cloned(),
                value.as_array(),
            ) {
                let mut merged: Vec<Value> = existing;
                for item in new_values {
                    if !merged.contains(item) {
                        merged.push(item.clone());
                    }
                }
                chunk.metadata.insert(key, Value::Array(merged));
                continue;
            }
        }
        chunk.metadata.insert(key, value);
    }
}

/// Strip `//` line comments and `/* */` block comments without a full parse.
fn strip_line_comments(text: &str) -> String {
    let mut out_lines = Vec::new();
    let mut in_block = false;
    for raw_line in text.split('\n') {
        let mut line = raw_line.to_owned();
        if in_block {
            if let Some(end) = line.find("*/") {
                line = line[end + 2..].to_owned();
                in_block = false;
            } else {
                continue;
            }
        }
        while let Some(start) = line.find("/*") {
            if let Some(end) = line[start + 2..].find("*/") {
                let absolute_end = start + 2 + end;
                line = format!("{}{}", &line[..start], &line[absolute_end + 2..]);
            } else {
                line = line[..start].to_owned();
                in_block = true;
                break;
            }
        }
        if let Some(slash) = line.find("//") {
            line = line[..slash].to_owned();
        }
        out_lines.push(line);
    }
    out_lines.join("\n")
}

fn detect_kotlin_java(content: &str, language: &str) -> BTreeMap<String, Value> {
    let mut meta = BTreeMap::new();
    let cleaned = strip_line_comments(content);
    let head: String = cleaned.chars().take(300).collect();

    if cleaned.contains("@Provides") {
        meta.insert("is_di_provider".to_owned(), json!("true"));
        let provides_kt = static_regex!(r"@Provides[\s\S]*?fun\s+\w+\s*\([^)]*\)\s*:\s*([A-Z]\w+)");
        let provides_java = static_regex!(
            r"@Provides[\s\S]*?(?:public|protected|private)?\s+([A-Z]\w+)\s+\w+\s*\("
        );
        let mut provides: Vec<String> = provides_kt
            .captures_iter(&cleaned)
            .chain(provides_java.captures_iter(&cleaned))
            .filter_map(|capture| capture.get(1).map(|m| m.as_str().to_owned()))
            .collect();
        provides.sort();
        provides.dedup();
        if !provides.is_empty() {
            meta.insert("provides".to_owned(), json!(provides));
        }
    }

    if cleaned.contains("@Inject") {
        meta.insert("is_di_consumer".to_owned(), json!("true"));
        let injects_kt = static_regex!(r"@Inject\s+(?:lateinit\s+)?var\s+\w+\s*:\s*([A-Z]\w+)");
        let injects_ctor = static_regex!(r"(?s)@Inject\s+constructor\s*\((.*?)\)");
        let ctor_types = static_regex!(r":\s*([A-Z]\w+)");
        let mut deps: Vec<String> = injects_kt
            .captures_iter(&cleaned)
            .filter_map(|capture| capture.get(1).map(|m| m.as_str().to_owned()))
            .collect();
        for ctor in injects_ctor.captures_iter(&cleaned) {
            if let Some(args) = ctor.get(1) {
                deps.extend(
                    ctor_types
                        .captures_iter(args.as_str())
                        .filter_map(|capture| capture.get(1).map(|m| m.as_str().to_owned())),
                );
            }
        }
        deps.sort();
        deps.dedup();
        if !deps.is_empty() {
            meta.insert("injects".to_owned(), json!(deps));
        }
    }

    if language == "kotlin" {
        if head.contains("suspend fun ") || head.trim_start().starts_with("suspend ") {
            meta.insert("is_suspend".to_owned(), json!("true"));
        }
        if KOTLIN_COROUTINE_BUILDERS
            .iter()
            .any(|builder| cleaned.contains(builder))
            || cleaned.contains("callbackFlow")
        {
            meta.insert("uses_coroutines".to_owned(), json!("true"));
        }
        if cleaned.contains("Flow<") {
            meta.insert("uses_flow".to_owned(), json!("true"));
        }
        if cleaned.contains("@Singleton") || cleaned.contains("javax.inject.Singleton") {
            meta.insert("is_singleton".to_owned(), json!("true"));
        }
        for line in cleaned.split('\n').take(5) {
            let stripped = line.trim_start();
            if stripped.starts_with("object ") && !stripped.starts_with("object {") {
                meta.insert("is_singleton".to_owned(), json!("true"));
                meta.insert("is_kotlin_object".to_owned(), json!("true"));
                break;
            }
        }
        if head.contains("sealed class ") || head.contains("sealed interface ") {
            meta.insert("is_sealed".to_owned(), json!("true"));
        }
        if head.contains("data class ") {
            meta.insert("is_data_class".to_owned(), json!("true"));
        }
        if head.trim_start().starts_with("interface ") || head.contains("\ninterface ") {
            meta.insert("is_interface".to_owned(), json!("true"));
        }
        if head.contains("abstract class ") {
            meta.insert("is_abstract".to_owned(), json!("true"));
        }
        if cleaned.contains("@Composable") {
            meta.insert("is_composable".to_owned(), json!("true"));
        }
        if cleaned.contains("@Module")
            || cleaned.contains("@HiltViewModel")
            || cleaned.contains("@AndroidEntryPoint")
        {
            meta.insert("is_di_component".to_owned(), json!("true"));
        }
        let inherits = extract_kotlin_inherits(&head);
        if !inherits.is_empty() {
            meta.insert("inherits_from".to_owned(), json!(inherits));
        }
    } else if language == "java" {
        if JAVA_ASYNC_BUILDERS
            .iter()
            .any(|builder| cleaned.contains(builder))
        {
            meta.insert("uses_async_java".to_owned(), json!("true"));
        }
        if cleaned.contains("@Singleton") || cleaned.contains("javax.inject.Singleton") {
            meta.insert("is_singleton".to_owned(), json!("true"));
        }
        if cleaned.contains("getInstance(")
            && cleaned.contains("private ")
            && cleaned.contains("static ")
        {
            meta.insert("is_singleton_pattern".to_owned(), json!("true"));
        }
        if head.trim_start().starts_with("public enum ")
            || head.contains("\npublic enum ")
            || head.contains("\nenum ")
        {
            meta.insert("is_enum".to_owned(), json!("true"));
        }
        if head.contains("interface ")
            && (head.contains("public interface") || head.trim_start().starts_with("interface "))
        {
            meta.insert("is_interface".to_owned(), json!("true"));
        }
        if head.contains("abstract class ") {
            meta.insert("is_abstract".to_owned(), json!("true"));
        }
        if cleaned.contains("@Test") || cleaned.contains("extends TestCase") {
            meta.insert("has_unit_test".to_owned(), json!("true"));
        }
        let inherits = extract_java_inherits(&head);
        if !inherits.is_empty() {
            meta.insert("inherits_from".to_owned(), json!(inherits));
        }
    }

    meta
}

fn extract_kotlin_inherits(head: &str) -> Vec<String> {
    let declaration = static_regex!(
        r"(?:^|\n)[^\n]*?(?:class|interface|object)\s+\w[\w<>]*?\s*(?:\([^)]*\))?\s*:\s*([^\{\n]+)"
    );
    let Some(capture) = declaration.captures(head) else {
        return Vec::new();
    };
    let raw = capture.get(1).map(|m| m.as_str()).unwrap_or_default();
    let generics = static_regex!(r"<[^>]*>");
    let ctor_args = static_regex!(r"\([^)]*\)");
    let simple_name = static_regex!(r"^[A-Z]\w*");
    let mut names = Vec::new();
    for part in raw.split(',') {
        let name = generics.replace_all(part, "");
        let name = ctor_args.replace_all(&name, "");
        let name = name.trim().to_owned();
        if !name.is_empty() && simple_name.is_match(&name) && !names.contains(&name) {
            names.push(name);
        }
    }
    names
}

fn extract_java_inherits(head: &str) -> Vec<String> {
    let generics = static_regex!(r"<[^>]*>");
    let mut names: Vec<String> = Vec::new();
    if let Some(capture) = static_regex!(r"\bextends\s+([A-Z]\w*(?:<[^>]*>)?)").captures(head) {
        let name = generics
            .replace_all(capture.get(1).map(|m| m.as_str()).unwrap_or_default(), "")
            .trim()
            .to_owned();
        if !name.is_empty() {
            names.push(name);
        }
    }
    if let Some(capture) =
        static_regex!(r"\bimplements\s+([A-Z][\w,\s<>]*?)(?:\{|$)").captures(head)
    {
        for part in capture
            .get(1)
            .map(|m| m.as_str())
            .unwrap_or_default()
            .split(',')
        {
            let name = generics.replace_all(part, "").trim().to_owned();
            if !name.is_empty() && !names.contains(&name) {
                names.push(name);
            }
        }
    }
    names
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kotlin_flags_detected() {
        let meta = detect_kotlin_java(
            "sealed class Migration : SignalDatabaseMigration {\n  suspend fun run() { launch { } }\n}",
            "kotlin",
        );
        assert_eq!(meta.get("is_sealed"), Some(&json!("true")));
        assert_eq!(meta.get("uses_coroutines"), Some(&json!("true")));
        assert_eq!(
            meta.get("inherits_from"),
            Some(&json!(["SignalDatabaseMigration"]))
        );
    }

    #[test]
    fn java_inherits_and_enum() {
        let meta = detect_kotlin_java(
            "public class FullBackupExporter extends FullBackupBase implements Closeable {\n static FullBackupExporter getInstance() {} private int x; }",
            "java",
        );
        assert_eq!(
            meta.get("inherits_from"),
            Some(&json!(["FullBackupBase", "Closeable"]))
        );
        assert_eq!(meta.get("is_singleton_pattern"), Some(&json!("true")));
    }

    #[test]
    fn comments_do_not_trigger_flags() {
        let meta = detect_kotlin_java("// launch a rocket\nclass Foo", "kotlin");
        assert!(!meta.contains_key("uses_coroutines"));
    }
}
