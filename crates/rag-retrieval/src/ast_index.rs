//! Best-effort bridge to the installed `ast-index` CLI.

use std::{collections::BTreeMap, path::Path, process::Command};

use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AstIndexHit {
    pub file_path: String,
    pub line: usize,
    pub name: String,
    pub kind: String,
    pub signature: String,
    pub context: String,
    pub source: String,
    pub code: String,
    pub start_line: usize,
    pub end_line: usize,
    pub score: f64,
}

impl AstIndexHit {
    #[must_use]
    pub fn to_context_candidate(&self) -> Value {
        serde_json::json!({
            "chunk_id": format!("ast:{}:{}:{}", self.file_path, self.start_line_or_line(), self.name_or_label()),
            "file_path": self.file_path,
            "name": self.name,
            "parent_name": "",
            "chunk_type": self.kind,
            "language": language_from_path(&self.file_path),
            "start_line": self.start_line_or_line(),
            "end_line": self.end_line_or_line(),
            "lines": format!("{}-{}", self.start_line_or_line(), self.end_line_or_line()),
            "code": self.code,
            "score": self.score,
            "citation": format!("{}:{}-{} ({})", self.file_path, self.start_line_or_line(), self.end_line_or_line(), self.name_or_label()),
            "why_included": format!("ast_index_{}", self.source),
        })
    }

    fn start_line_or_line(&self) -> usize {
        if self.start_line == 0 {
            self.line
        } else {
            self.start_line
        }
    }

    fn end_line_or_line(&self) -> usize {
        if self.end_line == 0 {
            self.line
        } else {
            self.end_line
        }
    }

    fn name_or_label(&self) -> String {
        if self.name.is_empty() {
            if self.signature.is_empty() {
                if self.context.is_empty() {
                    Path::new(&self.file_path)
                        .file_name()
                        .and_then(|value| value.to_str())
                        .unwrap_or("")
                        .to_owned()
                } else {
                    self.context.clone()
                }
            } else {
                self.signature.clone()
            }
        } else {
            self.name.clone()
        }
    }
}

#[must_use]
pub fn is_available() -> bool {
    Command::new("ast-index").arg("--version").output().is_ok()
}

fn run_text(root: &Path, args: &[&str]) -> Option<String> {
    let output = Command::new("ast-index")
        .args(args)
        .current_dir(root)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    String::from_utf8(output.stdout).ok()
}

fn run_json(root: &Path, args: &[&str]) -> Option<Value> {
    let output = run_text(root, args)?;
    serde_json::from_str(&output).ok()
}

fn language_from_path(path: &str) -> String {
    Path::new(path)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_owned()
}

fn query_terms(query: &str) -> Vec<String> {
    let mut out = Vec::new();
    for token in Regex::new(r"[A-Za-z_][A-Za-z0-9_]{2,}")
        .expect("static regex")
        .find_iter(query)
        .map(|m| m.as_str().to_owned())
    {
        if !out
            .iter()
            .any(|existing: &String| existing.eq_ignore_ascii_case(&token))
        {
            out.push(token);
        }
    }
    out.truncate(12);
    out
}

fn parse_text_search_hits(text: &str, source: &str) -> Vec<AstIndexHit> {
    let mut hits = Vec::new();
    let line_re = Regex::new(
        r"^(?P<indent>\s*)(?P<name>[A-Za-z_][A-Za-z0-9_.<>]*)\s+\((?P<path>.+):(?P<line>\d+)\)",
    )
    .expect("static regex");
    for line in text.lines() {
        let Some(caps) = line_re.captures(line) else {
            continue;
        };
        let file_path = caps["path"].trim().to_owned();
        let line = caps["line"].parse().unwrap_or(1);
        let name = caps["name"].trim().to_owned();
        let depth = caps.name("indent").map_or(0, |m| m.as_str().len() / 2);
        hits.push(AstIndexHit {
            file_path,
            line,
            name,
            kind: source.to_owned(),
            signature: String::new(),
            context: String::new(),
            source: source.to_owned(),
            code: String::new(),
            start_line: line,
            end_line: line,
            score: (10usize.saturating_sub(depth)) as f64,
        });
    }
    hits
}

fn parse_json_hits(value: Value, source: &str) -> Vec<AstIndexHit> {
    let Some(items) = value.as_array() else {
        return Vec::new();
    };
    items
        .iter()
        .filter_map(|item| {
            let path = item
                .get("path")
                .or_else(|| item.get("file_path"))?
                .as_str()?;
            let line = item
                .get("line")
                .or_else(|| item.get("start_line"))
                .and_then(Value::as_u64)
                .unwrap_or(1) as usize;
            Some(AstIndexHit {
                file_path: path.to_owned(),
                line,
                name: item
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned(),
                kind: item
                    .get("kind")
                    .or_else(|| item.get("type"))
                    .and_then(Value::as_str)
                    .unwrap_or(source)
                    .to_owned(),
                signature: item
                    .get("signature")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned(),
                context: item
                    .get("context")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned(),
                source: source.to_owned(),
                code: item
                    .get("code")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned(),
                start_line: item
                    .get("start_line")
                    .and_then(Value::as_u64)
                    .unwrap_or(line as u64) as usize,
                end_line: item
                    .get("end_line")
                    .and_then(Value::as_u64)
                    .unwrap_or(line as u64) as usize,
                score: item.get("score").and_then(Value::as_f64).unwrap_or(0.0),
            })
        })
        .collect()
}

/// Return AST-derived source candidates for a developer query.
#[must_use]
pub fn retrieve_context(
    repo_path: impl AsRef<Path>,
    query: &str,
    limit: usize,
    include_usages: bool,
) -> Vec<Value> {
    let root = repo_path.as_ref();
    if !root.exists() || !is_available() {
        return Vec::new();
    }
    let terms = query_terms(query);
    if terms.is_empty() {
        return Vec::new();
    }

    let mut hits: Vec<AstIndexHit> = Vec::new();
    let per_term_limit = usize::max(3, usize::min(10, limit));
    for term in terms.iter().take(6) {
        if let Some(value) = run_json(
            root,
            &[
                "symbol",
                "--format",
                "json",
                "--limit",
                &per_term_limit.to_string(),
                term,
            ],
        ) {
            hits.extend(parse_json_hits(value, "symbol"));
        }
        if let Some(value) = run_json(
            root,
            &[
                "search",
                "--format",
                "json",
                "--limit",
                &per_term_limit.to_string(),
                term,
            ],
        ) {
            hits.extend(parse_json_hits(value, "search"));
        }
        if include_usages && hits.len() < limit * 2 {
            if let Some(value) = run_json(
                root,
                &[
                    "usages",
                    "--format",
                    "json",
                    "--limit",
                    &usize::max(3, per_term_limit / 2).to_string(),
                    term,
                ],
            ) {
                hits.extend(parse_json_hits(value, "usages"));
            }
        }
    }

    hits.sort_by(|a, b| {
        b.score
            .total_cmp(&a.score)
            .then_with(|| a.file_path.cmp(&b.file_path))
    });
    hits.dedup_by(|a, b| {
        a.file_path == b.file_path
            && (a.start_line_or_line(), a.name.clone(), a.source.clone())
                == (b.start_line_or_line(), b.name.clone(), b.source.clone())
    });
    hits.truncate(limit);
    hits.into_iter()
        .map(|hit| hit.to_context_candidate())
        .collect()
}

/// Resolve exact symbol definitions and usages using ast-index.
#[must_use]
pub fn resolve_symbols(
    repo_path: impl AsRef<Path>,
    symbols: &[String],
    definitions_limit: usize,
    usages_limit: usize,
) -> Value {
    let root = repo_path.as_ref();
    if !root.exists() || !is_available() {
        return serde_json::json!({"definitions": [], "usages": []});
    }
    let mut definitions = Vec::new();
    let mut usages = Vec::new();
    for symbol in symbols {
        let clean = symbol.trim();
        if clean.is_empty() {
            continue;
        }
        // Over-fetch: the CLI truncates internally in nondeterministic scan
        // order, so asking for exactly `limit` returns a varying subset. A 3x
        // candidate pool makes the post-ranking top-`limit` stable.
        let definitions_fetch = (definitions_limit * 3).clamp(definitions_limit, 200);
        let usages_fetch = (usages_limit * 3).clamp(usages_limit, 200);
        if let Some(value) = run_json(
            root,
            &[
                "symbol",
                "--format",
                "json",
                "--limit",
                &definitions_fetch.to_string(),
                clean,
            ],
        ) {
            definitions.extend(parse_json_hits(value, "symbol"));
        }
        if let Some(value) = run_json(
            root,
            &[
                "usages",
                "--format",
                "json",
                "--limit",
                &usages_fetch.to_string(),
                clean,
            ],
        ) {
            usages.extend(parse_json_hits(value, "usages"));
        }
    }
    // Python `_attach_code`: read the source file and compute the real code
    // span (the CLI does not always emit `code`/`start_line`/`end_line`).
    for hit in definitions.iter_mut().chain(usages.iter_mut()) {
        attach_code(root, hit);
    }
    // The ast-index CLI scans in parallel, so its output ORDER (and therefore
    // any subset it truncates to) varies between runs. Rank with Python's
    // `_hit_rank_score` plus explicit tie-breakers before truncating so
    // identical requests return identical results.
    rank_hits_deterministically(&mut definitions);
    rank_hits_deterministically(&mut usages);
    // Python drops empty-code hits before ranking; keep parity for definitions.
    definitions.retain(|hit| !hit.code.trim().is_empty());
    // 50%-overlap dedupe (Python `_rank_unique_hits`/`_overlaps_existing`).
    let definitions = dedupe_overlapping(definitions, definitions_limit);
    let usages = dedupe_overlapping(usages, usages_limit);
    serde_json::json!({
        "definitions": definitions.into_iter().map(|hit| hit.to_context_candidate()).collect::<Vec<_>>(),
        "usages": usages.into_iter().map(|hit| hit.to_context_candidate()).collect::<Vec<_>>(),
    })
}

/// Python `_rank_unique_hits`: keep hits in ranked order, dropping any that
/// overlap an already-kept hit in the same file by ≥50%.
fn dedupe_overlapping(hits: Vec<AstIndexHit>, limit: usize) -> Vec<AstIndexHit> {
    let mut kept: Vec<AstIndexHit> = Vec::new();
    for hit in hits {
        if kept.iter().any(|existing| overlaps(&hit, existing)) {
            continue;
        }
        kept.push(hit);
        if kept.len() >= limit {
            break;
        }
    }
    kept
}

fn overlaps(candidate: &AstIndexHit, existing: &AstIndexHit) -> bool {
    if candidate.file_path != existing.file_path {
        return false;
    }
    let span = |hit: &AstIndexHit| {
        let start = if hit.start_line > 0 {
            hit.start_line
        } else {
            hit.line
        };
        let end = if hit.end_line > 0 {
            hit.end_line
        } else {
            hit.line
        };
        (start, end)
    };
    let (c_start, c_end) = span(candidate);
    let (e_start, e_end) = span(existing);
    let overlap = (c_end.min(e_end) as i64 - c_start.max(e_start) as i64 + 1).max(0);
    let shorter = (c_end - c_start + 1).min(e_end - e_start + 1).max(1);
    overlap as f64 / shorter as f64 >= 0.5
}

/// Python `_attach_code`: read the file, compute symbol/usage bounds, and set
/// `code`/`start_line`/`end_line`. Path-escape guarded to stay inside the repo.
const MAX_ATTACHED_SOURCE_BYTES: u64 = 4 * 1024 * 1024;

fn attach_code(root: &Path, hit: &mut AstIndexHit) {
    let Ok(root_abs) = root.canonicalize() else {
        return;
    };
    let Ok(path) = root.join(&hit.file_path).canonicalize() else {
        return;
    };
    if !path.starts_with(&root_abs) {
        return;
    }
    let Ok(bytes) = rag_index::read_file_bounded(&path, MAX_ATTACHED_SOURCE_BYTES) else {
        return;
    };
    let Ok(text) = String::from_utf8(bytes) else {
        return;
    };
    let lines: Vec<&str> = text.split('\n').collect();
    if lines.is_empty() {
        return;
    }
    let (start, end) =
        if (hit.source == "symbol" || hit.source == "search_symbol") && hit.kind != "property" {
            symbol_bounds(&lines, hit.line, 90)
        } else {
            usage_bounds(&lines, hit.line)
        };
    hit.start_line = start;
    hit.end_line = end;
    hit.code = lines[start.saturating_sub(1)..end.min(lines.len())].join("\n");
}

fn window_bounds(lines: &[&str], line: usize, radius: usize) -> (usize, usize) {
    let start = line.saturating_sub(radius).max(1);
    let end = (line + radius).min(lines.len());
    (start, end)
}

fn usage_bounds(lines: &[&str], line: usize) -> (usize, usize) {
    let idx = line.saturating_sub(1).min(lines.len().saturating_sub(1));
    let floor = idx.saturating_sub(40);
    for pos in (floor..=idx).rev() {
        let stripped = lines[pos].trim_start();
        if stripped.starts_with("fun ")
            || stripped.starts_with("def ")
            || stripped.starts_with("function ")
            || stripped.starts_with("class ")
            || stripped.starts_with("interface ")
            || stripped.starts_with("object ")
        {
            return symbol_bounds(lines, pos + 1, 80);
        }
    }
    window_bounds(lines, line, 8)
}

fn symbol_bounds(lines: &[&str], line: usize, max_lines: usize) -> (usize, usize) {
    let idx = line.saturating_sub(1).min(lines.len().saturating_sub(1));
    let mut start = idx;
    while start > 0 && idx - start < 6 {
        let prev = lines[start - 1].trim();
        if prev.starts_with('@')
            || prev.starts_with("//")
            || prev.starts_with("/*")
            || prev.starts_with('*')
        {
            start -= 1;
            continue;
        }
        break;
    }
    let symbol_line = symbol_line_regex();
    let mut brace_balance = 0i32;
    let mut saw_open = false;
    let end_limit = (idx + max_lines).min(lines.len());
    // The position IS the line number we return, so indexing by it is intended.
    #[allow(clippy::needless_range_loop)]
    for pos in idx..end_limit {
        let stripped = lines[pos].trim();
        brace_balance += brace_delta(lines[pos]);
        if lines[pos].contains('{') {
            saw_open = true;
        }
        if saw_open && brace_balance <= 0 && pos > idx {
            return (start + 1, pos + 1);
        }
        if !saw_open && pos > idx {
            if stripped.is_empty() {
                return (start + 1, pos);
            }
            if symbol_line.is_match(stripped) {
                return (start + 1, pos);
            }
        }
    }
    (start + 1, lines.len().min(end_limit))
}

fn brace_delta(line: &str) -> i32 {
    let mut in_string = false;
    let mut quote = ' ';
    let mut delta = 0;
    let bytes: Vec<char> = line.chars().collect();
    let mut i = 0;
    while i < bytes.len() {
        let ch = bytes[i];
        if in_string {
            if ch == '\\' {
                i += 2;
                continue;
            }
            if ch == quote {
                in_string = false;
            }
        } else if ch == '\'' || ch == '"' {
            in_string = true;
            quote = ch;
        } else if ch == '{' {
            delta += 1;
        } else if ch == '}' {
            delta -= 1;
        }
        i += 1;
    }
    delta
}

fn symbol_line_regex() -> &'static Regex {
    static CELL: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
    CELL.get_or_init(|| {
        Regex::new(r"\b(class|interface|object|enum|fun|def|function|val|var)\b|=>|\{")
            .expect("static regex")
    })
}

/// Python `_hit_rank_score` with (path, line) tie-breakers for stable order.
fn rank_hits_deterministically(hits: &mut [AstIndexHit]) {
    fn rank(hit: &AstIndexHit) -> f64 {
        let start = if hit.start_line > 0 {
            hit.start_line
        } else {
            hit.line
        };
        let end = if hit.end_line > 0 {
            hit.end_line
        } else {
            hit.line
        };
        let line_count = end.saturating_sub(start) + 1;
        let mut score = hit.score + (line_count as f64 / 20.0).min(2.0);
        let signature = hit.signature.trim();
        let code = hit.code.trim();
        if signature.starts_with("override ") || code.starts_with("override ") {
            score += 1.5;
        }
        if line_count <= 1 && !code.contains('{') && !code.contains('=') {
            score -= 1.0;
        }
        if code.contains("@Deprecated") {
            score -= 0.75;
        }
        score
    }
    hits.sort_by(|left, right| {
        rank(right)
            .total_cmp(&rank(left))
            .then_with(|| left.file_path.cmp(&right.file_path))
            .then_with(|| left.line.cmp(&right.line))
    });
}

/// Return caller tree nodes for a function with compact source slices.
#[must_use]
pub fn call_tree(repo_path: impl AsRef<Path>, symbol: &str, limit: usize) -> Vec<Value> {
    let root = repo_path.as_ref();
    if !root.exists() || !is_available() || symbol.trim().is_empty() {
        return Vec::new();
    }
    let Some(text) = run_text(
        root,
        &[
            "call-tree",
            "--format",
            "text",
            "--limit",
            &limit.to_string(),
            symbol.trim(),
        ],
    ) else {
        return Vec::new();
    };
    parse_text_search_hits(&text, "call_tree")
        .into_iter()
        .map(|hit| hit.to_context_candidate())
        .collect()
}

/// Return one-hop callers for a function with compact source slices.
#[must_use]
pub fn callers(repo_path: impl AsRef<Path>, symbol: &str, limit: usize) -> Vec<Value> {
    let root = repo_path.as_ref();
    if !root.exists() || !is_available() || symbol.trim().is_empty() {
        return Vec::new();
    }
    let Some(text) = run_text(
        root,
        &[
            "callers",
            "--format",
            "text",
            "--limit",
            &limit.to_string(),
            symbol.trim(),
        ],
    ) else {
        return Vec::new();
    };
    let line_re = Regex::new(r"^\s*:(?P<line>\d+)\s+(?P<context>.*)$").expect("static regex");
    let mut current_path = String::new();
    let mut out = Vec::new();
    for line in text.lines() {
        if line.ends_with(':') && !line.trim().starts_with(':') {
            current_path = line.trim_end_matches(':').trim().to_owned();
            continue;
        }
        let Some(caps) = line_re.captures(line) else {
            continue;
        };
        let line_no = caps["line"].parse().unwrap_or(1);
        out.push(AstIndexHit {
            file_path: current_path.clone(),
            line: line_no,
            name: symbol.trim().to_owned(),
            kind: "caller".to_owned(),
            signature: String::new(),
            context: caps["context"].trim().to_owned(),
            source: "callers".to_owned(),
            code: String::new(),
            start_line: line_no,
            end_line: line_no,
            score: 8.0,
        });
    }
    out.into_iter()
        .map(|hit| hit.to_context_candidate())
        .collect()
}

/// A structurally related file returned as a token-light link (Python
/// `RelatedLink`): sibling / collaborator / subclass_or_caller / implementor /
/// usage / reference.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RelatedLink {
    pub file_path: String,
    pub name: String,
    pub lines: String,
    pub relation: String,
}

fn relation_priority(relation: &str) -> u8 {
    match relation {
        "implementor" | "subclass" => 0,
        "subclass_or_caller" | "usage" => 1,
        "collaborator" | "reference" => 2,
        _ => 3,
    }
}

/// Python `_ast_index_related`: implementors (`implementations`) + cross-refs
/// (`refs`) via the ast-index CLI, merged by file keeping the strongest
/// relation, per-relation-capped, priority-ordered. Returns links, not code.
#[must_use]
pub fn related_files(
    repo_path: impl AsRef<Path>,
    symbols: &[String],
    prime_paths: &std::collections::BTreeSet<String>,
    limit: usize,
) -> Vec<RelatedLink> {
    let root = repo_path.as_ref();
    if !root.exists() || !is_available() {
        return Vec::new();
    }
    // (priority, link) per file — lower priority wins.
    let mut ranked: BTreeMap<String, (u8, RelatedLink)> = BTreeMap::new();
    let mut add = |item: &Value, relation: &str| {
        let Some(fp) = item
            .get("path")
            .or_else(|| item.get("file_path"))
            .and_then(Value::as_str)
        else {
            return;
        };
        if fp.is_empty() || prime_paths.contains(fp) {
            return;
        }
        let priority = relation_priority(relation);
        if ranked
            .get(fp)
            .is_some_and(|(existing, _)| *existing <= priority)
        {
            return;
        }
        let line = item
            .get("line")
            .and_then(Value::as_u64)
            .map(|value| value.to_string())
            .unwrap_or_else(|| "?".to_owned());
        let name = item
            .get("name")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .map(str::to_owned)
            .unwrap_or_else(|| {
                Path::new(fp)
                    .file_stem()
                    .and_then(|value| value.to_str())
                    .unwrap_or_default()
                    .to_owned()
            });
        ranked.insert(
            fp.to_owned(),
            (
                priority,
                RelatedLink {
                    file_path: fp.to_owned(),
                    name,
                    lines: format!("{line}-{line}"),
                    relation: relation.to_owned(),
                },
            ),
        );
    };

    for symbol in symbols.iter().take(5) {
        if let Some(Value::Array(items)) = run_json(
            root,
            &[
                "implementations",
                "--format",
                "json",
                "--limit",
                "25",
                symbol,
            ],
        ) {
            for item in &items {
                add(item, "implementor");
            }
        }
        if let Some(value) = run_json(root, &["refs", "--format", "json", "--limit", "25", symbol])
        {
            for item in value
                .get("usages")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                add(item, "usage");
            }
            for item in value
                .get("definitions")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                add(item, "reference");
            }
        }
    }

    // Per-relation cap of 12, priority-ordered, then truncate to `limit`.
    let mut links: Vec<(u8, RelatedLink)> = ranked.into_values().collect();
    links.sort_by(|(left, ll), (right, rl)| {
        left.cmp(right)
            .then_with(|| ll.file_path.cmp(&rl.file_path))
    });
    let mut per_relation: BTreeMap<String, usize> = BTreeMap::new();
    let mut out = Vec::new();
    for (_, link) in links {
        let count = per_relation.entry(link.relation.clone()).or_insert(0);
        if *count >= 12 {
            continue;
        }
        *count += 1;
        out.push(link);
        if out.len() >= limit {
            break;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::{
        attach_code, call_tree, callers, is_available, resolve_symbols, AstIndexHit,
        MAX_ATTACHED_SOURCE_BYTES,
    };
    use crate::repo_agent::{compact_slice, infer_risks};
    use serde_json::json;

    #[test]
    fn compact_slice_keeps_stable_fields() {
        let value = compact_slice(&json!({
            "file_path": "src/main.py",
            "name": "main",
            "lines": "1-3",
            "score": 1.0,
            "ignored": "x"
        }));
        assert_eq!(value["file_path"], "src/main.py");
        assert!(value.get("ignored").is_none());
    }

    #[test]
    fn helper_functions_are_safe_when_index_is_missing() {
        if !is_available() {
            return;
        }
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let _ = resolve_symbols(&root, &["SearchPlan".to_owned()], 3, 3);
        let _ = call_tree(&root, "SearchPlan", 3);
        let _ = callers(&root, "SearchPlan", 3);
        let risks = infer_risks("analytics event module move", true, &[], &[]);
        assert!(!risks.is_empty());
    }

    #[test]
    fn source_attachment_refuses_files_over_its_memory_budget() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("large.rs");
        let file = std::fs::File::create(&path).unwrap();
        file.set_len(MAX_ATTACHED_SOURCE_BYTES + 1).unwrap();
        let mut hit = AstIndexHit {
            file_path: "large.rs".to_owned(),
            line: 1,
            name: "large".to_owned(),
            kind: "function".to_owned(),
            signature: String::new(),
            context: String::new(),
            source: "symbol".to_owned(),
            code: String::new(),
            start_line: 1,
            end_line: 1,
            score: 1.0,
        };

        attach_code(temp.path(), &mut hit);

        assert!(hit.code.is_empty());
    }
}
