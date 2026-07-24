use std::{collections::BTreeMap, path::PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct LspServerSpec {
    pub language: &'static str,
    pub binary: &'static str,
    pub name: &'static str,
    pub install_hint: &'static str,
    pub args: &'static [&'static str],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LspServerStatus {
    pub language: String,
    pub name: String,
    pub found: bool,
    pub install_hint: String,
    pub path: Option<PathBuf>,
}

pub const LSP_SERVERS: &[LspServerSpec] = &[
    LspServerSpec {
        language: "python",
        binary: "pyright-langserver",
        name: "pyright",
        install_hint: "npm install -g pyright",
        args: &["--stdio"],
    },
    LspServerSpec {
        language: "typescript",
        binary: "typescript-language-server",
        name: "tsserver",
        install_hint: "npm install -g typescript-language-server typescript",
        args: &["--stdio"],
    },
    LspServerSpec {
        language: "go",
        binary: "gopls",
        name: "gopls",
        install_hint: "go install golang.org/x/tools/gopls@latest",
        args: &["serve"],
    },
    LspServerSpec {
        language: "rust",
        binary: "rust-analyzer",
        name: "rust-analyzer",
        install_hint: "rustup component add rust-analyzer",
        args: &[],
    },
    LspServerSpec {
        language: "java",
        binary: "jdtls",
        name: "jdtls",
        install_hint: "brew install jdtls",
        args: &[],
    },
    LspServerSpec {
        language: "c",
        binary: "clangd",
        name: "clangd",
        install_hint: "brew install llvm",
        args: &["--background-index"],
    },
    LspServerSpec {
        language: "cpp",
        binary: "clangd",
        name: "clangd",
        install_hint: "brew install llvm",
        args: &["--background-index"],
    },
    LspServerSpec {
        language: "dart",
        binary: "dart",
        name: "dart language-server",
        install_hint: "Install Dart SDK: https://dart.dev/get-dart",
        args: &["language-server", "--protocol=lsp"],
    },
    LspServerSpec {
        language: "kotlin",
        binary: "kotlin-language-server",
        name: "kotlin-language-server",
        install_hint: "brew install kotlin-language-server",
        args: &[],
    },
];

pub fn detect_lsp_servers(languages: Option<&[&str]>) -> Vec<LspServerStatus> {
    let requested = languages.map(<[&str]>::to_vec);
    LSP_SERVERS
        .iter()
        .filter(|spec| {
            requested
                .as_ref()
                .is_none_or(|items| items.contains(&spec.language))
        })
        .map(|spec| {
            let path = which_on_path(spec.binary);
            LspServerStatus {
                language: spec.language.to_owned(),
                name: spec.name.to_owned(),
                found: path.is_some(),
                install_hint: spec.install_hint.to_owned(),
                path,
            }
        })
        .collect()
}

fn which_on_path(binary: &str) -> Option<PathBuf> {
    let paths = std::env::var_os("PATH")?;
    let mut aliases = BTreeMap::new();
    aliases.insert(binary.to_owned(), binary.to_owned());
    for dir in std::env::split_paths(&paths) {
        let candidate = dir.join(binary);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}
