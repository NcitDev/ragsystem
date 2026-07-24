use std::{collections::BTreeMap, path::Path};

use serde::{Deserialize, Serialize};
use tree_sitter::{Language, Node, Parser};

use crate::discovery::short_sha256;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChunkType {
    FileSummary,
    ClassDeclaration,
    InterfaceDeclaration,
    Function,
    Method,
    Property,
    DocSection,
}

impl ChunkType {
    pub fn as_python_value(&self) -> &'static str {
        match self {
            Self::FileSummary => "file_summary",
            Self::ClassDeclaration => "class_declaration",
            Self::InterfaceDeclaration => "interface_declaration",
            Self::Function => "function",
            Self::Method => "method",
            Self::Property => "property",
            Self::DocSection => "doc_section",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Chunk {
    pub content: String,
    pub chunk_type: ChunkType,
    pub file_path: String,
    pub language: String,
    pub name: String,
    pub parent_name: String,
    pub start_line: usize,
    pub end_line: usize,
    pub metadata: BTreeMap<String, serde_json::Value>,
    pub source_text: String,
}

impl Chunk {
    pub fn chunk_id(&self) -> String {
        let raw = format!(
            "{}:{}:{}:{}",
            self.file_path,
            self.chunk_type.as_python_value(),
            self.start_line,
            self.end_line
        );
        short_sha256(raw.as_bytes())
    }

    pub fn content_hash(&self) -> String {
        short_sha256(self.content.as_bytes())
    }
}

#[derive(Debug, Clone, Copy)]
pub struct LanguageConfig {
    pub language: &'static str,
    pub extensions: &'static [&'static str],
    pub class_types: &'static [&'static str],
    pub function_types: &'static [&'static str],
    pub import_types: &'static [&'static str],
    pub wrapper_types: &'static [&'static str],
    pub available_in_rust: bool,
    pub parity_note: &'static str,
}

const CONFIGS: &[LanguageConfig] = &[
    LanguageConfig {
        language: "python",
        extensions: &[".py"],
        class_types: &["class_definition"],
        function_types: &["function_definition"],
        import_types: &["import_statement", "import_from_statement"],
        wrapper_types: &["decorated_definition"],
        available_in_rust: true,
        parity_note: "standalone maintained grammar crate",
    },
    LanguageConfig {
        language: "java",
        extensions: &[".java"],
        class_types: &["class_declaration", "interface_declaration", "enum_declaration"],
        function_types: &["method_declaration", "constructor_declaration"],
        import_types: &["import_declaration"],
        wrapper_types: &[],
        available_in_rust: true,
        parity_note: "standalone maintained grammar crate",
    },
    LanguageConfig {
        language: "kotlin",
        extensions: &[".kt", ".kts"],
        class_types: &["class_declaration", "object_declaration", "interface_declaration"],
        function_types: &["function_declaration"],
        import_types: &["import_header"],
        wrapper_types: &[],
        available_in_rust: true,
        parity_note: "tree-sitter-kotlin-ng tracks tree-sitter-grammars Kotlin",
    },
    LanguageConfig {
        language: "typescript",
        extensions: &[".ts", ".tsx"],
        class_types: &["class_declaration", "interface_declaration"],
        function_types: &["function_declaration", "method_definition", "arrow_function"],
        import_types: &["import_statement"],
        wrapper_types: &["export_statement", "ambient_declaration"],
        available_in_rust: true,
        parity_note: "standalone maintained grammar crate",
    },
    LanguageConfig {
        language: "javascript",
        extensions: &[".js", ".jsx", ".mjs"],
        class_types: &["class_declaration"],
        function_types: &["function_declaration", "method_definition", "arrow_function"],
        import_types: &["import_statement"],
        wrapper_types: &["export_statement"],
        available_in_rust: true,
        parity_note: "standalone maintained grammar crate",
    },
    LanguageConfig {
        language: "go",
        extensions: &[".go"],
        class_types: &["type_declaration"],
        function_types: &["function_declaration", "method_declaration"],
        import_types: &["import_declaration"],
        wrapper_types: &[],
        available_in_rust: true,
        parity_note: "standalone maintained grammar crate",
    },
    LanguageConfig {
        language: "rust",
        extensions: &[".rs"],
        class_types: &["struct_item", "enum_item", "impl_item", "trait_item"],
        function_types: &["function_item"],
        import_types: &["use_declaration"],
        wrapper_types: &[],
        available_in_rust: true,
        parity_note: "standalone maintained grammar crate",
    },
    LanguageConfig {
        language: "c",
        extensions: &[".c", ".h"],
        class_types: &["struct_specifier", "enum_specifier", "union_specifier"],
        function_types: &["function_definition"],
        import_types: &["preproc_include"],
        wrapper_types: &[],
        available_in_rust: true,
        parity_note: "standalone maintained grammar crate",
    },
    LanguageConfig {
        language: "cpp",
        extensions: &[".cpp", ".cc", ".cxx", ".hpp", ".hh"],
        class_types: &["class_specifier", "struct_specifier", "enum_specifier"],
        function_types: &["function_definition"],
        import_types: &["preproc_include"],
        wrapper_types: &["template_declaration"],
        available_in_rust: true,
        parity_note: "standalone maintained grammar crate",
    },
    LanguageConfig {
        language: "dart",
        extensions: &[".dart"],
        class_types: &[
            "class_declaration",
            "mixin_declaration",
            "extension_declaration",
            "enum_declaration",
        ],
        function_types: &[
            "method_declaration",
            "function_declaration",
            "getter_declaration",
            "setter_declaration",
            "constructor_declaration",
            "method_signature",
            "function_signature",
            "getter_signature",
            "setter_signature",
            "constructor_signature",
        ],
        import_types: &["import_or_export", "library_name", "part_directive"],
        wrapper_types: &["class_member"],
        available_in_rust: true,
        parity_note: "tree-sitter-dart 0.2.0 is the maintained Rust grammar crate; parser shape differs from the Python language-pack fallback but remains tree-sitter-based",
    },
];

pub fn supported_languages() -> Vec<&'static str> {
    CONFIGS.iter().map(|config| config.language).collect()
}

pub fn supported_extensions() -> Vec<String> {
    CONFIGS
        .iter()
        .flat_map(|config| config.extensions.iter().map(|ext| (*ext).to_owned()))
        .collect()
}

pub fn language_config(language: &str) -> Option<&'static LanguageConfig> {
    CONFIGS.iter().find(|config| config.language == language)
}

pub fn detect_language(file_path: &str) -> Option<&'static str> {
    let ext = Path::new(file_path)
        .extension()
        .and_then(|value| value.to_str())?;
    let dotted = format!(".{}", ext.to_ascii_lowercase());
    CONFIGS
        .iter()
        .find(|config| config.extensions.contains(&dotted.as_str()))
        .map(|config| config.language)
}

pub fn chunk_code(
    source: &str,
    file_path: &str,
    language: Option<&str>,
    max_chars: usize,
) -> Vec<Chunk> {
    let language = language
        .or_else(|| detect_language(file_path))
        .unwrap_or("unknown");
    let Some(config) = language_config(language) else {
        return sliding_window(source, file_path, language, max_chars);
    };
    if !config.available_in_rust {
        return sliding_window(source, file_path, language, max_chars);
    }
    let Ok(mut parser) = parser_for(language) else {
        return sliding_window(source, file_path, language, max_chars);
    };
    let Some(tree) = parser.parse(source, None) else {
        return sliding_window(source, file_path, language, max_chars);
    };
    let root = tree.root_node();
    let lines: Vec<&str> = source.lines().collect();
    let bytes = source.as_bytes();
    let mut chunks = Vec::new();

    let mut summary_parts = Vec::new();
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        if config.import_types.contains(&child.kind()) {
            summary_parts.push(node_text(child, bytes).to_owned());
        } else if let Some((inner, _kind)) = unwrap_node(child, config) {
            let first = node_text(inner, bytes)
                .lines()
                .next()
                .unwrap_or("")
                .to_owned();
            summary_parts.push(first);
        }
    }
    if !summary_parts.is_empty() {
        chunks.push(Chunk {
            content: truncate_chars(&summary_parts.join("\n"), max_chars),
            chunk_type: ChunkType::FileSummary,
            file_path: file_path.to_owned(),
            language: language.to_owned(),
            name: Path::new(file_path)
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or(file_path)
                .to_owned(),
            parent_name: String::new(),
            start_line: 1,
            end_line: root.end_position().row + 1,
            metadata: BTreeMap::new(),
            source_text: source.to_owned(),
        });
    }

    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        match unwrap_node(child, config) {
            Some((inner, DefinitionKind::Class)) => {
                extract_class(
                    inner,
                    child,
                    config,
                    file_path,
                    language,
                    max_chars,
                    &lines,
                    bytes,
                    &mut chunks,
                );
            }
            Some((inner, DefinitionKind::Function)) => {
                extract_function(
                    inner,
                    child,
                    config,
                    file_path,
                    language,
                    "",
                    max_chars,
                    &lines,
                    bytes,
                    &mut chunks,
                );
            }
            None => {}
        }
    }

    if chunks.is_empty() {
        sliding_window(source, file_path, language, max_chars)
    } else {
        chunks
    }
}

#[derive(Clone, Copy)]
enum DefinitionKind {
    Class,
    Function,
}

fn parser_for(language: &str) -> Result<Parser, tree_sitter::LanguageError> {
    let ts_language: Language = match language {
        "python" => tree_sitter_python::LANGUAGE.into(),
        "java" => tree_sitter_java::LANGUAGE.into(),
        "kotlin" => tree_sitter_kotlin_ng::LANGUAGE.into(),
        "typescript" => tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into(),
        "javascript" => tree_sitter_javascript::LANGUAGE.into(),
        "go" => tree_sitter_go::LANGUAGE.into(),
        "rust" => tree_sitter_rust::LANGUAGE.into(),
        "c" => tree_sitter_c::LANGUAGE.into(),
        "cpp" => tree_sitter_cpp::LANGUAGE.into(),
        "dart" => tree_sitter_dart::LANGUAGE.into(),
        _ => tree_sitter_python::LANGUAGE.into(),
    };
    let mut parser = Parser::new();
    parser.set_language(&ts_language)?;
    Ok(parser)
}

fn unwrap_node<'a>(node: Node<'a>, config: &LanguageConfig) -> Option<(Node<'a>, DefinitionKind)> {
    let mut current = node;
    for _ in 0..3 {
        if config.class_types.contains(&current.kind()) {
            return Some((current, DefinitionKind::Class));
        }
        if config.function_types.contains(&current.kind()) {
            return Some((current, DefinitionKind::Function));
        }
        if !config.wrapper_types.contains(&current.kind()) {
            return None;
        }
        let mut cursor = current.walk();
        current = current.children(&mut cursor).find(|child| {
            config.class_types.contains(&child.kind())
                || config.function_types.contains(&child.kind())
                || config.wrapper_types.contains(&child.kind())
        })?;
    }
    None
}

#[allow(clippy::too_many_arguments)]
fn extract_class(
    node: Node<'_>,
    outer: Node<'_>,
    config: &LanguageConfig,
    file_path: &str,
    language: &str,
    max_chars: usize,
    lines: &[&str],
    bytes: &[u8],
    chunks: &mut Vec<Chunk>,
) {
    let class_name = node_name(node, bytes);
    let members = collect_members(node, config);
    let mut summary_lines = Vec::new();
    for (member, _outer) in &members {
        summary_lines.push(
            node_text(*member, bytes)
                .lines()
                .next()
                .unwrap_or("")
                .to_owned(),
        );
    }
    let first = node_text(node, bytes).lines().next().unwrap_or("");
    let chunk_type = if node.kind().contains("interface") {
        ChunkType::InterfaceDeclaration
    } else {
        ChunkType::ClassDeclaration
    };
    chunks.push(Chunk {
        content: truncate_chars(
            &format!("{}\n{}", first, summary_lines.join("\n")),
            max_chars,
        ),
        chunk_type,
        file_path: file_path.to_owned(),
        language: language.to_owned(),
        name: class_name.clone(),
        parent_name: String::new(),
        start_line: outer.start_position().row + 1,
        end_line: outer.end_position().row + 1,
        metadata: name_position_meta(node, bytes),
        source_text: line_slice(
            lines,
            outer.start_position().row,
            outer.end_position().row + 1,
        ),
    });
    for (member, member_outer) in members {
        extract_function(
            member,
            member_outer,
            config,
            file_path,
            language,
            &class_name,
            max_chars,
            lines,
            bytes,
            chunks,
        );
    }
}

#[allow(clippy::too_many_arguments)]
fn extract_function(
    node: Node<'_>,
    outer: Node<'_>,
    config: &LanguageConfig,
    file_path: &str,
    language: &str,
    parent_name: &str,
    max_chars: usize,
    lines: &[&str],
    bytes: &[u8],
    chunks: &mut Vec<Chunk>,
) {
    let name = node_name(node, bytes);
    let start = outer.start_position().row;
    let end = outer.end_position().row + 1;
    let source_text = line_slice(lines, start, end);
    if source_text.trim().is_empty() {
        return;
    }
    let content = format!(
        "{}\n\n{}",
        context_header(file_path, language, parent_name),
        source_text
    );
    let mut metadata = BTreeMap::new();
    if let Some(name_node) = name_node(node) {
        metadata.insert(
            "name_line".to_owned(),
            serde_json::json!(name_node.start_position().row),
        );
        metadata.insert(
            "name_col".to_owned(),
            serde_json::json!(name_node.start_position().column),
        );
    }
    let _ = config;
    chunks.push(Chunk {
        content: truncate_chars(&content, max_chars),
        chunk_type: if parent_name.is_empty() {
            ChunkType::Function
        } else {
            ChunkType::Method
        },
        file_path: file_path.to_owned(),
        language: language.to_owned(),
        name,
        parent_name: parent_name.to_owned(),
        start_line: start + 1,
        end_line: end,
        metadata,
        source_text,
    });
}

fn collect_members<'a>(node: Node<'a>, config: &LanguageConfig) -> Vec<(Node<'a>, Node<'a>)> {
    let mut out = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if let Some((inner, DefinitionKind::Function)) = unwrap_node(child, config) {
            out.push((inner, child));
        } else if ["block", "class_body", "body", "declaration_list"].contains(&child.kind()) {
            let mut body_cursor = child.walk();
            for grandchild in child.children(&mut body_cursor) {
                if let Some((inner, DefinitionKind::Function)) = unwrap_node(grandchild, config) {
                    out.push((inner, grandchild));
                }
            }
        }
    }
    out
}

fn node_name(node: Node<'_>, bytes: &[u8]) -> String {
    let Some(name_node) = name_node(node) else {
        return String::new();
    };
    let text = node_text(name_node, bytes);
    text.split('(').next().unwrap_or(text).to_owned()
}

fn name_node(node: Node<'_>) -> Option<Node<'_>> {
    if let Some(signature) = node.child_by_field_name("signature") {
        if let Some(name) = name_node(signature) {
            return Some(name);
        }
    }
    for field in ["name", "simple_identifier", "declarator", "type"] {
        if let Some(child) = node.child_by_field_name(field) {
            if let Some(inner) = child.child_by_field_name("declarator") {
                return Some(inner);
            }
            return Some(child);
        }
    }
    let mut cursor = node.walk();
    let found = node.children(&mut cursor).find(|child| {
        [
            "identifier",
            "type_identifier",
            "field_identifier",
            "property_identifier",
        ]
        .contains(&child.kind())
    });
    if found.is_some() {
        return found;
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if let Some(found) = name_node(child) {
            return Some(found);
        }
    }
    None
}

fn name_position_meta(node: Node<'_>, _bytes: &[u8]) -> BTreeMap<String, serde_json::Value> {
    let mut metadata = BTreeMap::new();
    if let Some(name_node) = name_node(node) {
        metadata.insert(
            "name_line".to_owned(),
            serde_json::json!(name_node.start_position().row),
        );
        metadata.insert(
            "name_col".to_owned(),
            serde_json::json!(name_node.start_position().column),
        );
    }
    metadata
}

fn node_text<'a>(node: Node<'_>, bytes: &'a [u8]) -> &'a str {
    node.utf8_text(bytes).unwrap_or("")
}

fn line_slice(lines: &[&str], start: usize, end: usize) -> String {
    lines
        .get(start..end.min(lines.len()))
        .unwrap_or_default()
        .join("\n")
}

fn context_header(file_path: &str, language: &str, parent_name: &str) -> String {
    let leader = if language == "python" { "#" } else { "//" };
    let mut parts = vec![format!("{leader} File: {file_path}")];
    if !parent_name.is_empty() {
        parts.push(format!("{leader} Class: {parent_name}"));
    }
    parts.push(format!("{leader} Language: {language}"));
    parts.join("\n")
}

fn truncate_chars(value: &str, max_chars: usize) -> String {
    value.chars().take(max_chars).collect()
}

fn sliding_window(source: &str, file_path: &str, language: &str, max_chars: usize) -> Vec<Chunk> {
    let lines: Vec<&str> = source.split('\n').collect();
    let mut chunks = Vec::new();
    let mut start = 0;
    while start < lines.len() {
        let end = (start + 60).min(lines.len());
        let text = truncate_chars(&lines[start..end].join("\n"), max_chars);
        if !text.trim().is_empty() {
            chunks.push(Chunk {
                content: text,
                chunk_type: ChunkType::FileSummary,
                file_path: file_path.to_owned(),
                language: language.to_owned(),
                name: Path::new(file_path)
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or(file_path)
                    .to_owned(),
                parent_name: String::new(),
                start_line: start + 1,
                end_line: end,
                metadata: BTreeMap::new(),
                source_text: String::new(),
            });
        }
        if end == lines.len() {
            break;
        }
        start += 50;
    }
    chunks
}
