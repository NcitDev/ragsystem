//! Configuration, path, token, and auth compatibility for the Rust daemon.

use std::fs;
use std::io::{self, Read as _, Write as _};
use std::net::IpAddr;
use std::path::{Path, PathBuf};

use base64::Engine as _;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use toml::Value;

/// Temporary coexistence host for the Rust daemon.
pub const DEFAULT_HOST: &str = "127.0.0.1";
/// Temporary coexistence port; the Python daemon remains on port 7890.
// Production port since cutover; 7891 was the coexistence port while the
// Python daemon still owned 7890.
pub const DEFAULT_PORT: u16 = 7890;

/// Packaged defaults (single source of truth, embedded in the binary).
pub const PYTHON_DEFAULT_TOML: &str = include_str!("../assets/default.toml");

/// Validated bind settings for the temporary Rust daemon.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServerConfig {
    /// Loopback host or `localhost`.
    pub host: String,
    /// TCP port.
    pub port: u16,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            host: DEFAULT_HOST.to_owned(),
            port: DEFAULT_PORT,
        }
    }
}

impl ServerConfig {
    /// Validate a requested bind without resolving or opening a socket.
    pub fn new(host: impl AsRef<str>, port: u16) -> Result<Self, ConfigError> {
        let host = normalize_host(host.as_ref())?;
        if port == 0 {
            return Err(ConfigError::InvalidPort(port));
        }
        Ok(Self { host, port })
    }
}

/// Bind validation failures.
#[derive(Debug, Error)]
pub enum ConfigError {
    /// Host is empty.
    #[error("server.host must not be empty")]
    EmptyHost,
    /// Host is not loopback.
    #[error(
        "server.host={0:?} is not loopback and would expose the daemon; use 127.0.0.1 or localhost"
    )]
    NonLoopbackHost(String),
    /// Port zero cannot be used as a stable daemon port.
    #[error("server.port={0} is outside the valid range 1..=65535")]
    InvalidPort(u16),
    /// A TOML file could not be parsed.
    #[error("failed to parse TOML from {path}: {source}")]
    Toml {
        /// Path being parsed.
        path: String,
        /// Parser error.
        source: toml::de::Error,
    },
    /// A TOML value could not be converted into settings.
    #[error("invalid settings: {0}")]
    InvalidSettings(String),
    /// Filesystem operation failed.
    #[error("{context}: {source}")]
    Io {
        /// Operation context.
        context: &'static str,
        /// I/O source error.
        source: io::Error,
    },
    /// Required home resolution failed.
    #[error("could not resolve home directory; set RAG_HOME or HOME")]
    MissingHome,
}

/// Path contract for user-local daemon state.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RagPaths {
    /// Root state directory. Python uses `~/.rag`.
    pub home: PathBuf,
    /// User config path.
    pub config_path: PathBuf,
    /// Bearer token path.
    pub token_path: PathBuf,
}

impl RagPaths {
    /// Resolve from process env without creating directories.
    ///
    /// `RAG_HOME` is honored for tests and migration tooling so Rust never has
    /// to touch a real `~/.rag`; absent that, the Python default is `HOME/.rag`.
    pub fn from_env() -> Result<Self, ConfigError> {
        if let Some(value) = std::env::var_os("RAG_HOME") {
            return Ok(Self::from_home(PathBuf::from(value)));
        }
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .ok_or(ConfigError::MissingHome)?;
        Ok(Self::from_home(home.join(".rag")))
    }

    /// Build paths from an explicit RAG home. Preferred in tests.
    #[must_use]
    pub fn from_home(home: impl Into<PathBuf>) -> Self {
        let home = home.into();
        Self {
            config_path: home.join("config.toml"),
            token_path: home.join("token"),
            home,
        }
    }
}

/// Server settings from Python `Settings.server`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct PythonServerSettings {
    /// Bind host.
    pub host: String,
    /// Bind port.
    pub port: u16,
    /// Maximum protected requests executing concurrently.
    pub max_in_flight: u16,
}

impl Default for PythonServerSettings {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_owned(),
            port: 7890,
            max_in_flight: 32,
        }
    }
}

/// Embedding settings.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct EmbeddingSettings {
    /// Embedding model name.
    pub model: String,
    /// Deprecated provider field retained for config compatibility.
    pub provider: String,
    /// Vector dimension.
    pub dim: u16,
    /// Embedding batch size.
    pub batch_size: u16,
    /// Ollama keep-alive string.
    pub keep_alive: String,
}

impl Default for EmbeddingSettings {
    fn default() -> Self {
        Self {
            model: "qwen3-embedding:4b".to_owned(),
            provider: "ollama".to_owned(),
            dim: 2560,
            batch_size: 64,
            keep_alive: "30m".to_owned(),
        }
    }
}

/// Deprecated reranker settings retained for parsing.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct RerankerSettings {
    /// Model name.
    pub model: String,
    /// Deprecated runtime flag.
    pub enabled: bool,
    /// Top-k value.
    pub top_k: u16,
}

impl Default for RerankerSettings {
    fn default() -> Self {
        Self {
            model: "dengcao/Qwen3-Reranker-4B:Q8_0".to_owned(),
            enabled: false,
            top_k: 5,
        }
    }
}

/// Qdrant configuration.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct QdrantSettings {
    /// `server` or legacy `embedded`.
    pub mode: String,
    /// Server URL.
    pub url: String,
    /// Environment variable containing the Qdrant API key. The secret itself
    /// is deliberately never stored in the TOML configuration.
    pub api_key_env: String,
    /// Embedded path.
    pub path: String,
    /// Default code collection.
    pub code_collection: String,
    /// Default docs collection.
    pub docs_collection: String,
}

impl Default for QdrantSettings {
    fn default() -> Self {
        Self {
            mode: "server".to_owned(),
            url: "http://127.0.0.1:6333".to_owned(),
            api_key_env: "QDRANT_API_KEY".to_owned(),
            path: "~/.rag/qdrant_data".to_owned(),
            code_collection: "code_chunks".to_owned(),
            docs_collection: "doc_chunks".to_owned(),
        }
    }
}

impl QdrantSettings {
    /// Expand a leading `~` the same way Python `Path.expanduser()` does for
    /// the supported `~/.rag/...` config values.
    #[must_use]
    pub fn resolved_path(&self, home_dir: &Path) -> PathBuf {
        expand_user_path(&self.path, home_dir)
    }
}

/// Indexing settings.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct IndexSettings {
    /// Max chunk size in chars.
    pub max_chunk_chars: u32,
    /// Maximum bytes read from any single source file.
    pub max_file_bytes: u64,
    /// Default retrieval top-k.
    pub retrieval_top_k: u16,
    /// Directory names skipped during discovery.
    pub skip_dirs: Vec<String>,
}

impl Default for IndexSettings {
    fn default() -> Self {
        Self {
            max_chunk_chars: 8000,
            max_file_bytes: 4 * 1024 * 1024,
            retrieval_top_k: 20,
            skip_dirs: [
                ".git",
                "node_modules",
                ".venv",
                "venv",
                "__pycache__",
                "build",
                "dist",
                ".tox",
                ".mypy_cache",
                ".ruff_cache",
            ]
            .into_iter()
            .map(str::to_owned)
            .collect(),
        }
    }
}

/// LLM settings.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct LlmSettings {
    /// Ollama URL.
    pub ollama_url: String,
    /// Planner model.
    pub agent_model: String,
    /// Generation model, empty means fall back to agent model.
    pub gen_model: String,
}

impl Default for LlmSettings {
    fn default() -> Self {
        Self {
            ollama_url: "http://localhost:11434".to_owned(),
            agent_model: "qwen3:8b".to_owned(),
            gen_model: String::new(),
        }
    }
}

/// LSP settings.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct LspSettings {
    /// Enable LSP enrichment.
    pub enabled: bool,
    /// Auto-detect servers.
    pub auto_detect: bool,
    /// Timeout in milliseconds.
    pub timeout: u32,
}

impl Default for LspSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            auto_detect: true,
            timeout: 5000,
        }
    }
}

/// Retrieval planner provider settings.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct RetrievalAgentSettings {
    /// Provider name.
    pub provider: String,
    /// Model name or display name.
    pub model: String,
    /// API key environment variable.
    pub api_key_env: String,
    /// Optional provider base URL.
    pub base_url: String,
}

impl Default for RetrievalAgentSettings {
    fn default() -> Self {
        Self {
            provider: "agy".to_owned(),
            model: "Gemini 3.5 Flash (Low)".to_owned(),
            api_key_env: "GEMINI_API_KEY".to_owned(),
            base_url: String::new(),
        }
    }
}

/// Complete Python-compatible settings tree.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct Settings {
    /// Server section.
    pub server: PythonServerSettings,
    /// Embeddings section.
    pub embeddings: EmbeddingSettings,
    /// Deprecated reranker section.
    pub reranker: RerankerSettings,
    /// Qdrant section.
    pub qdrant: QdrantSettings,
    /// Index section.
    pub index: IndexSettings,
    /// LLM section.
    pub llm: LlmSettings,
    /// LSP section.
    pub lsp: LspSettings,
    /// Planner provider section.
    pub retrieval_agent: RetrievalAgentSettings,
}

impl Settings {
    /// Validate settings with the same bounds and compatibility allowances as
    /// the Python Pydantic models.
    pub fn validate(&mut self) -> Result<(), ConfigError> {
        let host = self.server.host.trim();
        if matches!(host, "0.0.0.0" | "::" | "[::]") {
            return Err(ConfigError::InvalidSettings(format!(
                "server.host={:?} binds all interfaces and exposes the daemon publicly",
                self.server.host
            )));
        }
        self.server.host = host.to_owned();
        ensure_range("server.max_in_flight", self.server.max_in_flight, 1, 1024)?;

        if !matches!(
            self.embeddings.provider.as_str(),
            "auto" | "ollama" | "fastembed"
        ) {
            return Err(ConfigError::InvalidSettings(
                "embeddings.provider must be auto, ollama, or fastembed".to_owned(),
            ));
        }
        ensure_range("embeddings.dim", self.embeddings.dim, 32, 8192)?;
        ensure_range("embeddings.batch_size", self.embeddings.batch_size, 1, 512)?;
        ensure_range("reranker.top_k", self.reranker.top_k, 1, 100)?;
        ensure_range(
            "index.max_chunk_chars",
            self.index.max_chunk_chars,
            500,
            100_000,
        )?;
        ensure_range(
            "index.max_file_bytes",
            self.index.max_file_bytes,
            1024,
            1024 * 1024 * 1024,
        )?;
        ensure_range("index.retrieval_top_k", self.index.retrieval_top_k, 1, 500)?;
        ensure_range("lsp.timeout", self.lsp.timeout, 1000, 60_000)?;
        if !matches!(self.qdrant.mode.as_str(), "server" | "embedded") {
            return Err(ConfigError::InvalidSettings(
                "qdrant.mode must be server or embedded".to_owned(),
            ));
        }
        self.qdrant.url = trim_url(&self.qdrant.url, "qdrant.url")?;
        self.qdrant.api_key_env = self.qdrant.api_key_env.trim().to_owned();
        if !self.qdrant.api_key_env.is_empty()
            && !is_environment_variable_name(&self.qdrant.api_key_env)
        {
            return Err(ConfigError::InvalidSettings(
                "qdrant.api_key_env must be empty or a valid environment variable name".to_owned(),
            ));
        }
        self.llm.ollama_url = trim_url(&self.llm.ollama_url, "ollama_url")?;
        if !matches!(
            self.retrieval_agent.provider.as_str(),
            "gemini" | "openai" | "anthropic" | "ollama" | "agy"
        ) {
            return Err(ConfigError::InvalidSettings(
                "retrieval_agent.provider is invalid".to_owned(),
            ));
        }
        Ok(())
    }
}

fn is_environment_variable_name(value: &str) -> bool {
    let mut bytes = value.bytes();
    matches!(bytes.next(), Some(b'A'..=b'Z' | b'a'..=b'z' | b'_'))
        && bytes.all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
}

/// Load packaged defaults merged with an explicit user home config.
pub fn load_settings(paths: &RagPaths) -> Result<Settings, ConfigError> {
    let defaults = parse_toml_value(PYTHON_DEFAULT_TOML, "packaged default.toml")?;
    load_settings_with_defaults(paths, defaults)
}

/// Load settings with an explicit defaults value, useful for fixture tests.
pub fn load_settings_with_defaults(
    paths: &RagPaths,
    mut data: Value,
) -> Result<Settings, ConfigError> {
    if paths.config_path.exists() {
        let user_text =
            fs::read_to_string(&paths.config_path).map_err(|source| ConfigError::Io {
                context: "read user config",
                source,
            })?;
        let user = parse_toml_value(&user_text, &paths.config_path.display().to_string())?;
        deep_merge(&mut data, user);
    }
    let mut settings: Settings = data
        .try_into()
        .map_err(|error| ConfigError::InvalidSettings(error.to_string()))?;
    settings.validate()?;
    Ok(settings)
}

/// Load dotenv files in Python priority order without overriding existing env.
pub fn load_env_files(paths: &RagPaths, cwd: &Path) -> Result<Vec<PathBuf>, ConfigError> {
    let mut loaded = Vec::new();
    let user_env = paths.home.join(".env");
    if user_env.exists() {
        load_dotenv_no_override(&user_env)?;
        loaded.push(user_env);
    }
    if let Some(project_env) = find_dotenv(cwd) {
        load_dotenv_no_override(&project_env)?;
        loaded.push(project_env);
    }
    Ok(loaded)
}

/// Return an existing token or create one and enforce private permissions.
pub fn get_or_create_token(paths: &RagPaths) -> Result<String, ConfigError> {
    fs::create_dir_all(&paths.home).map_err(|source| ConfigError::Io {
        context: "create RAG home",
        source,
    })?;
    if paths.token_path.exists() {
        return read_existing_token(&paths.token_path);
    }
    let token = generate_token_urlsafe_32()?;
    let mut options = fs::OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
    }
    let mut file = match options.open(&paths.token_path) {
        Ok(file) => file,
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
            // Another concurrently starting daemon won creation. Always use
            // the token that actually landed on disk.
            return read_existing_token(&paths.token_path);
        }
        Err(source) => {
            return Err(ConfigError::Io {
                context: "create token",
                source,
            })
        }
    };
    file.write_all(token.as_bytes())
        .and_then(|()| file.sync_all())
        .map_err(|source| ConfigError::Io {
            context: "write token",
            source,
        })?;
    drop(file);
    set_private_mode(&paths.token_path)?;
    Ok(token)
}

fn read_existing_token(path: &Path) -> Result<String, ConfigError> {
    let metadata = fs::symlink_metadata(path).map_err(|source| ConfigError::Io {
        context: "inspect token",
        source,
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(ConfigError::InvalidSettings(
            "token path must be a regular file, not a symlink or device".to_owned(),
        ));
    }
    let mut options = fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.custom_flags(libc::O_NOFOLLOW);
    }
    let mut file = options.open(path).map_err(|source| ConfigError::Io {
        context: "read token",
        source,
    })?;
    let mut existing = String::new();
    file.read_to_string(&mut existing)
        .map_err(|source| ConfigError::Io {
            context: "read token",
            source,
        })?;
    let trimmed = existing.trim();
    if trimmed.is_empty() {
        return Err(ConfigError::InvalidSettings(
            "token file is empty; refusing to rotate credentials implicitly".to_owned(),
        ));
    }
    set_private_mode(path)?;
    Ok(trimmed.to_owned())
}

/// Verify an Authorization header against the daemon token.
pub fn verify_bearer_header(header: Option<&str>, expected: &str) -> bool {
    header
        .and_then(parse_bearer)
        .is_some_and(|presented| constant_time_eq(presented.as_bytes(), expected.as_bytes()))
}

/// Extract a bearer credential using Python's whitespace and case rules.
#[must_use]
pub fn parse_bearer(value: &str) -> Option<&str> {
    let value = value.trim();
    let split = value.find(char::is_whitespace)?;
    let (scheme, credential) = value.split_at(split);
    let credential = credential.trim();
    if scheme.eq_ignore_ascii_case("bearer") && !credential.is_empty() {
        Some(credential)
    } else {
        None
    }
}

fn parse_toml_value(text: &str, path: &str) -> Result<Value, ConfigError> {
    text.parse::<Value>().map_err(|source| ConfigError::Toml {
        path: path.to_owned(),
        source,
    })
}

fn deep_merge(base: &mut Value, override_value: Value) {
    match (base, override_value) {
        (Value::Table(base), Value::Table(override_table)) => {
            for (key, value) in override_table {
                match base.get_mut(&key) {
                    Some(existing) if existing.is_table() && value.is_table() => {
                        deep_merge(existing, value);
                    }
                    _ => {
                        base.insert(key, value);
                    }
                }
            }
        }
        (base, override_value) => *base = override_value,
    }
}

fn ensure_range<T>(name: &str, value: T, min: T, max: T) -> Result<(), ConfigError>
where
    T: PartialOrd + std::fmt::Display,
{
    if value < min || value > max {
        return Err(ConfigError::InvalidSettings(format!(
            "{name}={value} is outside {min}..={max}"
        )));
    }
    Ok(())
}

fn trim_url(value: &str, name: &str) -> Result<String, ConfigError> {
    if !value.starts_with("http://") && !value.starts_with("https://") {
        return Err(ConfigError::InvalidSettings(format!(
            "{name} must start with http:// or https://"
        )));
    }
    Ok(value.trim_end_matches('/').to_owned())
}

fn load_dotenv_no_override(path: &Path) -> Result<(), ConfigError> {
    let text = fs::read_to_string(path).map_err(|source| ConfigError::Io {
        context: "read dotenv",
        source,
    })?;
    for line in text.lines() {
        if let Some((key, value)) = parse_env_line(line) {
            if std::env::var_os(&key).is_none() {
                if key.contains(['\0', '=']) || value.contains('\0') {
                    return Err(ConfigError::InvalidSettings(format!(
                        "dotenv {} contains an invalid environment entry",
                        path.display()
                    )));
                }
                std::env::set_var(key, value);
            }
        }
    }
    Ok(())
}

fn parse_env_line(line: &str) -> Option<(String, String)> {
    let trimmed = line.trim();
    if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with("export ") {
        return None;
    }
    let (key, raw_value) = trimmed.split_once('=')?;
    let key = key.trim();
    if key.is_empty() {
        return None;
    }
    let mut value = raw_value.trim().to_owned();
    if (value.starts_with('"') && value.ends_with('"'))
        || (value.starts_with('\'') && value.ends_with('\''))
    {
        value = value[1..value.len().saturating_sub(1)].to_owned();
    }
    Some((key.to_owned(), value))
}

fn find_dotenv(cwd: &Path) -> Option<PathBuf> {
    for ancestor in cwd.ancestors() {
        let candidate = ancestor.join(".env");
        if candidate.exists() {
            return Some(candidate);
        }
    }
    None
}

fn generate_token_urlsafe_32() -> Result<String, ConfigError> {
    let mut bytes = [0_u8; 32];
    fill_random(&mut bytes)?;
    Ok(base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes))
}

#[cfg(unix)]
fn fill_random(bytes: &mut [u8]) -> Result<(), ConfigError> {
    getrandom::fill(bytes).map_err(|error| ConfigError::Io {
        context: "read random source",
        source: io::Error::other(error.to_string()),
    })
}

#[cfg(not(unix))]
fn fill_random(bytes: &mut [u8]) -> Result<(), ConfigError> {
    getrandom::fill(bytes).map_err(|error| ConfigError::Io {
        context: "read random source",
        source: io::Error::other(error.to_string()),
    })
}

#[cfg(unix)]
fn set_private_mode(path: &Path) -> Result<(), ConfigError> {
    use std::os::unix::fs::PermissionsExt as _;

    let metadata = fs::metadata(path).map_err(|source| ConfigError::Io {
        context: "read token permissions",
        source,
    })?;
    let mut permissions = metadata.permissions();
    permissions.set_mode(0o600);
    fs::set_permissions(path, permissions).map_err(|source| ConfigError::Io {
        context: "set token permissions",
        source,
    })
}

#[cfg(not(unix))]
fn set_private_mode(_path: &Path) -> Result<(), ConfigError> {
    Ok(())
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut diff = 0_u8;
    for (a, b) in left.iter().zip(right.iter()) {
        diff |= a ^ b;
    }
    diff == 0
}

fn expand_user_path(value: &str, home_dir: &Path) -> PathBuf {
    if value == "~" {
        return home_dir.to_path_buf();
    }
    if let Some(rest) = value.strip_prefix("~/") {
        return home_dir.join(rest);
    }
    PathBuf::from(value)
}

fn normalize_host(raw: &str) -> Result<String, ConfigError> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err(ConfigError::EmptyHost);
    }
    if trimmed.eq_ignore_ascii_case("localhost") {
        return Ok("localhost".to_owned());
    }

    let candidate = trimmed
        .strip_prefix('[')
        .and_then(|value| value.strip_suffix(']'))
        .unwrap_or(trimmed);
    match candidate.parse::<IpAddr>() {
        Ok(address) if address.is_loopback() => Ok(address.to_string()),
        _ => Err(ConfigError::NonLoopbackHost(trimmed.to_owned())),
    }
}

#[cfg(test)]
mod tests {
    use super::{ConfigError, ServerConfig, DEFAULT_HOST, DEFAULT_PORT};

    #[test]
    fn defaults_use_temporary_coexistence_address() {
        let config = ServerConfig::default();
        assert_eq!(config.host, DEFAULT_HOST);
        assert_eq!(config.port, DEFAULT_PORT);
    }

    #[test]
    fn accepts_ipv4_ipv6_and_localhost_loopback() {
        assert!(ServerConfig::new("127.0.0.1", 7891).is_ok());
        assert!(ServerConfig::new("127.0.0.2", 7891).is_ok());
        assert!(ServerConfig::new("::1", 7891).is_ok());
        assert!(ServerConfig::new("[::1]", 7891).is_ok());
        assert!(ServerConfig::new("localhost", 7891).is_ok());
    }

    #[test]
    fn rejects_wildcard_and_non_loopback_binds() {
        for host in ["0.0.0.0", "::", "[::]", "192.168.1.10", "example.com"] {
            assert!(matches!(
                ServerConfig::new(host, 7891),
                Err(ConfigError::NonLoopbackHost(_))
            ));
        }
    }

    #[test]
    fn rejects_zero_port() {
        assert!(matches!(
            ServerConfig::new(DEFAULT_HOST, 0),
            Err(ConfigError::InvalidPort(0))
        ));
    }
}
