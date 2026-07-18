use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};

use anyhow::{bail, Context};
use reqwest::Method;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

use crate::client::ApiClient;

const VOLATILE_KEYS: &[&str] = &[
    "latency_ms",
    "retrieval_ms",
    "generation_ms",
    "symbol_inference_ms",
    "uptime_seconds",
    "updated_at",
    "ts",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShadowCase {
    pub name: String,
    pub method: String,
    pub path: String,
    #[serde(default)]
    pub body: Value,
}

#[derive(Debug, Serialize)]
pub struct ShadowResult {
    pub name: String,
    pub matched: bool,
    pub ranking_matched: bool,
    pub python_latency_ms: f64,
    pub rust_latency_ms: f64,
    pub python: Value,
    pub rust: Value,
}

#[derive(Debug, Serialize)]
pub struct ShadowReport {
    pub passed: bool,
    pub contract_passed: bool,
    pub ranking_passed: bool,
    pub latency_passed: bool,
    pub python_p95_ms: f64,
    pub rust_p95_ms: f64,
    pub cases: Vec<ShadowResult>,
}

pub async fn shadow_compare(
    python: &ApiClient,
    rust: &ApiClient,
    cases: &[ShadowCase],
) -> anyhow::Result<ShadowReport> {
    let mut results = Vec::with_capacity(cases.len());
    for case in cases {
        let method = Method::from_bytes(case.method.as_bytes())
            .with_context(|| format!("invalid method in shadow case {}", case.name))?;
        let body = (method != Method::GET).then(|| case.body.clone());
        let left_raw = python
            .request(method.clone(), &case.path, body.clone())
            .await?;
        let right_raw = rust.request(method, &case.path, body).await?;
        let python_latency_ms = response_latency(&left_raw);
        let rust_latency_ms = response_latency(&right_raw);
        let ranking_matched = first_hit(&left_raw) == first_hit(&right_raw);
        let left = normalize(left_raw);
        let right = normalize(right_raw);
        results.push(ShadowResult {
            name: case.name.clone(),
            matched: left == right,
            ranking_matched,
            python_latency_ms,
            rust_latency_ms,
            python: left,
            rust: right,
        });
    }
    let contract_passed = results.iter().all(|result| result.matched);
    let ranking_passed = results.iter().all(|result| result.ranking_matched);
    let python_p95_ms = percentile_95(results.iter().map(|result| result.python_latency_ms));
    let rust_p95_ms = percentile_95(results.iter().map(|result| result.rust_latency_ms));
    let latency_passed = python_p95_ms <= f64::EPSILON || rust_p95_ms <= python_p95_ms;
    Ok(ShadowReport {
        passed: contract_passed && ranking_passed && latency_passed,
        contract_passed,
        ranking_passed,
        latency_passed,
        python_p95_ms,
        rust_p95_ms,
        cases: results,
    })
}

fn response_latency(value: &Value) -> f64 {
    value
        .get("latency_ms")
        .and_then(Value::as_f64)
        .unwrap_or(0.0)
}

fn first_hit(value: &Value) -> Option<&str> {
    ["results", "slices", "definitions", "candidates"]
        .iter()
        .find_map(|key| {
            value
                .get(key)
                .and_then(Value::as_array)
                .and_then(|items| items.first())
                .and_then(|item| item.get("file_path"))
                .and_then(Value::as_str)
        })
}

fn percentile_95(values: impl Iterator<Item = f64>) -> f64 {
    let mut values: Vec<_> = values.filter(|value| value.is_finite()).collect();
    if values.is_empty() {
        return 0.0;
    }
    values.sort_by(f64::total_cmp);
    let index = ((values.len() as f64 * 0.95).ceil() as usize).saturating_sub(1);
    values[index]
}

pub fn default_shadow_cases() -> Vec<ShadowCase> {
    vec![
        ShadowCase {
            name: "health".into(),
            method: "GET".into(),
            path: "/health".into(),
            body: Value::Null,
        },
        ShadowCase {
            name: "status".into(),
            method: "GET".into(),
            path: "/status".into(),
            body: Value::Null,
        },
        ShadowCase {
            name: "search".into(),
            method: "POST".into(),
            path: "/search".into(),
            body: json!({"query": "bearer auth", "top_k": 10}),
        },
        ShadowCase {
            name: "resolve".into(),
            method: "POST".into(),
            path: "/resolve".into(),
            body: json!({"repo": "ragsystem", "symbols": ["require_auth"]}),
        },
        ShadowCase {
            name: "context-pack".into(),
            method: "POST".into(),
            path: "/context-pack".into(),
            body: json!({"repo": "ragsystem", "query": "bearer auth"}),
        },
        ShadowCase {
            name: "smart-search".into(),
            method: "POST".into(),
            path: "/smart-search".into(),
            body: json!({"question": "where is bearer auth handled?", "repo": "ragsystem"}),
        },
    ]
}

pub fn load_shadow_cases(path: &Path) -> anyhow::Result<Vec<ShadowCase>> {
    let data = fs::read(path).with_context(|| format!("failed to read {}", path.display()))?;
    serde_json::from_slice(&data).context("invalid shadow-case JSON")
}

pub fn normalize(value: Value) -> Value {
    match value {
        Value::Object(object) => {
            let normalized: BTreeMap<_, _> = object
                .into_iter()
                .filter(|(key, _)| !VOLATILE_KEYS.contains(&key.as_str()))
                .map(|(key, value)| (key, normalize(value)))
                .collect();
            Value::Object(normalized.into_iter().collect::<Map<_, _>>())
        }
        Value::Array(items) => Value::Array(items.into_iter().map(normalize).collect()),
        other => other,
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CutoverManifest {
    pub source: PathBuf,
    pub backup: PathBuf,
    pub backup_sha256: BTreeMap<String, String>,
    pub rust_binary: PathBuf,
    pub shadow_report: PathBuf,
    pub state: String,
    pub rollback_command: String,
}

pub fn prepare_cutover(
    source: &Path,
    backup: &Path,
    rust_binary: &Path,
    shadow_report: &Path,
) -> anyhow::Result<CutoverManifest> {
    let source = source.canonicalize().context("RAG home does not exist")?;
    if !rust_binary.is_file() {
        bail!("Rust binary does not exist: {}", rust_binary.display());
    }
    let report: Value = serde_json::from_slice(&fs::read(shadow_report)?)
        .context("shadow report is not valid JSON")?;
    if report.get("passed") != Some(&Value::Bool(true)) {
        bail!("shadow validation has not passed");
    }
    if backup.exists() {
        bail!("backup path already exists: {}", backup.display());
    }
    copy_tree(&source, backup)?;
    let hashes = hash_tree(backup)?;
    let manifest = CutoverManifest {
        source: source.clone(),
        backup: backup.to_owned(),
        backup_sha256: hashes,
        rust_binary: rust_binary.to_owned(),
        shadow_report: shadow_report.to_owned(),
        state: "prepared".to_owned(),
        rollback_command: format!(
            "rag-rs migration rollback --manifest {} --acknowledge-data-risk",
            backup.join("cutover-manifest.json").display()
        ),
    };
    fs::write(
        backup.join("cutover-manifest.json"),
        serde_json::to_vec_pretty(&manifest)?,
    )?;
    Ok(manifest)
}

pub fn activate_cutover(
    manifest_path: &Path,
    acknowledge_data_risk: bool,
) -> anyhow::Result<CutoverManifest> {
    if !acknowledge_data_risk {
        bail!("cutover activation requires --acknowledge-data-risk");
    }
    let mut manifest: CutoverManifest = serde_json::from_slice(&fs::read(manifest_path)?)?;
    if manifest.state != "prepared" {
        bail!("cutover manifest is not in prepared state");
    }
    verify_hashes(&manifest.backup, &manifest.backup_sha256)?;
    manifest.state = "activated".to_owned();
    fs::write(manifest_path, serde_json::to_vec_pretty(&manifest)?)?;
    Ok(manifest)
}

pub fn rollback(
    manifest_path: &Path,
    acknowledge_data_risk: bool,
) -> anyhow::Result<CutoverManifest> {
    if !acknowledge_data_risk {
        bail!("rollback requires --acknowledge-data-risk");
    }
    let mut manifest: CutoverManifest = serde_json::from_slice(&fs::read(manifest_path)?)?;
    verify_hashes(&manifest.backup, &manifest.backup_sha256)?;
    if manifest.state != "activated" {
        bail!("rollback is only valid for an activated cutover");
    }
    // The backup is intentionally never copied over live state automatically.
    // Operators must stop both daemons before restoring the verified directory.
    manifest.state = "rollback_ready".to_owned();
    fs::write(manifest_path, serde_json::to_vec_pretty(&manifest)?)?;
    Ok(manifest)
}

fn copy_tree(source: &Path, destination: &Path) -> anyhow::Result<()> {
    fs::create_dir_all(destination)?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let kind = entry.file_type()?;
        let target = destination.join(entry.file_name());
        if kind.is_symlink() {
            bail!("refusing to copy symlink: {}", entry.path().display());
        } else if kind.is_dir() {
            copy_tree(&entry.path(), &target)?;
        } else if kind.is_file() {
            fs::copy(entry.path(), target)?;
        }
    }
    Ok(())
}

fn hash_tree(root: &Path) -> anyhow::Result<BTreeMap<String, String>> {
    let mut hashes = BTreeMap::new();
    hash_tree_inner(root, root, &mut hashes)?;
    Ok(hashes)
}

fn hash_tree_inner(
    root: &Path,
    current: &Path,
    hashes: &mut BTreeMap<String, String>,
) -> anyhow::Result<()> {
    for entry in fs::read_dir(current)? {
        let entry = entry?;
        if entry.file_type()?.is_dir() {
            hash_tree_inner(root, &entry.path(), hashes)?;
        } else if entry.file_name() != "cutover-manifest.json" {
            let relative = entry
                .path()
                .strip_prefix(root)?
                .to_string_lossy()
                .to_string();
            let digest = Sha256::digest(fs::read(entry.path())?);
            hashes.insert(relative, format!("{digest:x}"));
        }
    }
    Ok(())
}

fn verify_hashes(root: &Path, expected: &BTreeMap<String, String>) -> anyhow::Result<()> {
    let actual = hash_tree(root)?;
    if &actual != expected {
        bail!("backup checksum verification failed");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::fs;

    use serde_json::json;
    use tempfile::tempdir;

    use super::{activate_cutover, normalize, prepare_cutover, rollback};

    #[test]
    fn normalization_removes_only_declared_volatile_fields() {
        assert_eq!(
            normalize(json!({"latency_ms": 12.0, "result": {"ts": 1, "id": "stable"}})),
            json!({"result": {"id": "stable"}})
        );
    }

    #[test]
    fn cutover_requires_shadow_pass_and_verified_backup() {
        let temp = tempdir().unwrap();
        let source = temp.path().join("rag-home");
        let backup = temp.path().join("backup");
        let binary = temp.path().join("rag-rs");
        let report = temp.path().join("shadow.json");
        fs::create_dir(&source).unwrap();
        fs::write(source.join("state.json"), "{}").unwrap();
        fs::write(&binary, "binary").unwrap();
        fs::write(&report, r#"{"passed":true}"#).unwrap();
        let manifest = prepare_cutover(&source, &backup, &binary, &report).unwrap();
        let manifest_path = backup.join("cutover-manifest.json");
        assert_eq!(manifest.state, "prepared");
        assert!(activate_cutover(&manifest_path, false).is_err());
        assert_eq!(
            activate_cutover(&manifest_path, true).unwrap().state,
            "activated"
        );
        assert_eq!(
            rollback(&manifest_path, true).unwrap().state,
            "rollback_ready"
        );
    }
}
