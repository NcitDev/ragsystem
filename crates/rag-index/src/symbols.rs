//! Native tree-sitter symbol extraction — the in-process replacement for the
//! external `ast-index` CLI.
//!
//! For one source file this produces three record streams:
//!
//! * [`SymbolDef`] — every definition (class/interface/struct/trait/impl/
//!   object/function/method/constructor/property) with its parent, signature,
//!   and 1-based inclusive line span.
//! * [`SymbolRef`] — every reference site, classified by [`RefKind`] (call
//!   target, member read, type mention, import name, bare identifier read),
//!   with the enclosing definition (`container`) and the trimmed source line,
//!   which is what renders a "caller line".
//! * [`SymbolEdge`] — structural edges: `calls`, `inherits`, `implements`,
//!   `imports`.
//!
//! The definition's own name site is never emitted as a reference; neither are
//! binding sites (parameter names, variable declarators, field names), which
//! are declarations rather than usages.
//!
//! Extraction is per-file and stateless: cross-file resolution (which `hello`
//! does `g.hello()` mean?) is deliberately *not* attempted here. Names are
//! matched by identifier, exactly like the `ast-index` CLI did.
//!
//! Measured on Signal-Android (5 598 Kotlin/Java files, the benchmark corpus):
//! 77 220 definitions, 964 381 references and 356 292 edges in 28 s
//! single-threaded, for a 0.29 GB SQLite footprint. 9 of those files yield no
//! definitions — see the per-language coverage notes on `spec_for` below.

use std::collections::{BTreeSet, HashSet};

use serde::{Deserialize, Serialize};
use tree_sitter::{Language, Node, Parser};

use crate::chunker::{detect_language, language_config, LanguageConfig};
use crate::graph::{AstGraph, AstReference, GraphNode, GraphRelation};

/// How a reference site uses the identifier.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RefKind {
    /// Identifier in callee position (`foo()`, `a.b.foo()`, `new Foo()`).
    Call,
    /// Member read that is not a call: the `bar` in `foo.bar`. Kotlin and Java
    /// property access lands here, which is why it is stored by default.
    Member,
    /// Identifier in a type position: annotation, heritage clause, generic arg.
    Type,
    /// Identifier inside an import statement.
    Import,
    /// A bare identifier read — usually a local variable. Off by default; see
    /// [`ExtractOptions::include_plain_identifiers`].
    Ident,
}

impl RefKind {
    /// Stable lowercase name used in SQLite and JSON.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Call => "call",
            Self::Member => "member",
            Self::Type => "type",
            Self::Import => "import",
            Self::Ident => "ident",
        }
    }

    /// Parse a stored value; unknown values fall back to [`RefKind::Ident`].
    #[must_use]
    pub fn parse(value: &str) -> Self {
        match value {
            "call" => Self::Call,
            "member" => Self::Member,
            "type" => Self::Type,
            "import" => Self::Import,
            _ => Self::Ident,
        }
    }
}

/// Structural relation between two symbols.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EdgeRelation {
    /// `from` contains a call site naming `to`.
    Calls,
    /// `from` extends the class `to`.
    Inherits,
    /// `from` implements the interface/trait/mixin `to`.
    Implements,
    /// The file imports `to`.
    Imports,
}

impl EdgeRelation {
    /// Stable lowercase name used in SQLite and JSON.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Calls => "calls",
            Self::Inherits => "inherits",
            Self::Implements => "implements",
            Self::Imports => "imports",
        }
    }

    /// Parse a stored value; unknown values fall back to [`EdgeRelation::Calls`].
    #[must_use]
    pub fn parse(value: &str) -> Self {
        match value {
            "inherits" => Self::Inherits,
            "implements" => Self::Implements,
            "imports" => Self::Imports,
            _ => Self::Calls,
        }
    }

    /// True for the subtyping relations `/implementations` cares about.
    #[must_use]
    pub fn is_subtyping(self) -> bool {
        matches!(self, Self::Inherits | Self::Implements)
    }
}

/// One definition site.
///
/// `start_line`/`end_line` are 1-based and inclusive and cover the *outer*
/// node — Python decorators and TS `export` keywords are inside the span.
/// `name_line`/`name_col` point at the identifier itself (`name_col` is
/// 0-based, matching `chunker`'s `name_col` metadata).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SymbolDef {
    /// Repo-relative path of the file the definition lives in.
    pub file_path: String,
    /// Bare identifier, e.g. `hello`.
    pub name: String,
    /// Dotted path through enclosing definitions, e.g. `Greeter.hello`.
    pub qualified_name: String,
    /// Immediately enclosing definition name, or empty at file level.
    pub parent_name: String,
    /// Normalized kind (`class`, `interface`, `method`, `property`, ...).
    pub kind: String,
    /// Source language.
    pub language: String,
    /// Declaration text up to the body, whitespace-collapsed.
    pub signature: String,
    /// First line of the definition (1-based, inclusive of decorators).
    pub start_line: usize,
    /// Last line of the definition (1-based, inclusive).
    pub end_line: usize,
    /// Line of the identifier itself (1-based).
    pub name_line: usize,
    /// Column of the identifier (0-based).
    pub name_col: usize,
}

impl SymbolDef {
    /// `path:start-end` citation used by the retrieval layer.
    #[must_use]
    pub fn citation(&self) -> String {
        format!(
            "{}:{}-{} ({})",
            self.file_path, self.start_line, self.end_line, self.qualified_name
        )
    }
}

/// One reference site.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SymbolRef {
    /// Repo-relative path of the referencing file.
    pub file_path: String,
    /// The referenced identifier.
    pub name: String,
    /// How the identifier is used.
    pub kind: RefKind,
    /// Qualified name of the enclosing definition, empty at file level.
    pub container: String,
    /// Bare name of the enclosing definition, empty at file level.
    pub container_name: String,
    /// Source language.
    pub language: String,
    /// 1-based line of the reference.
    pub line: usize,
    /// 0-based column of the reference.
    pub col: usize,
    /// Trimmed source line, ready to render as a caller line.
    pub context: String,
}

/// One structural edge.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SymbolEdge {
    /// Repo-relative path of the file the edge originates in.
    pub file_path: String,
    /// Bare name of the source symbol (empty for file-level `imports`).
    pub from_name: String,
    /// Qualified name of the source symbol.
    pub from_qualified: String,
    /// Bare name of the target symbol.
    pub to_name: String,
    /// Relation kind.
    pub relation: EdgeRelation,
    /// Source language.
    pub language: String,
    /// 1-based line the edge was observed on.
    pub line: usize,
    /// Trimmed source line for that edge.
    pub context: String,
}

/// Everything extracted from a single file.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct FileSymbols {
    /// Repo-relative path this batch belongs to.
    pub file_path: String,
    /// Detected/declared language.
    pub language: String,
    /// Definitions in source order.
    pub definitions: Vec<SymbolDef>,
    /// References in source order.
    pub references: Vec<SymbolRef>,
    /// Structural edges in source order.
    pub edges: Vec<SymbolEdge>,
}

impl FileSymbols {
    /// True when the file yielded nothing at all.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.definitions.is_empty() && self.references.is_empty() && self.edges.is_empty()
    }

    /// Project into the pre-existing in-memory [`AstGraph`].
    ///
    /// `graph.rs` already models exactly the node/edge shape retrieval wants
    /// (`callers`/`callees`/`traverse`), it just never had a producer. This is
    /// that producer, so nothing there needs to be superseded; the SQLite
    /// tables are the durable form and `AstGraph` stays the in-memory one.
    #[must_use]
    pub fn to_ast_graph(&self) -> AstGraph {
        let mut graph = AstGraph::default();
        for def in &self.definitions {
            graph.upsert_node(GraphNode {
                id: def.qualified_name.clone(),
                file_path: def.file_path.clone(),
                name: def.name.clone(),
                parent_name: def.parent_name.clone(),
                chunk_type: def.kind.clone(),
                language: def.language.clone(),
                patterns: Vec::new(),
                domains: Vec::new(),
            });
        }
        for edge in &self.edges {
            if edge.from_qualified.is_empty() {
                continue;
            }
            let relation = match edge.relation {
                EdgeRelation::Calls => GraphRelation::Calls,
                EdgeRelation::Inherits | EdgeRelation::Implements => GraphRelation::Inherits,
                EdgeRelation::Imports => GraphRelation::Imports,
            };
            graph.add_edge(edge.from_qualified.clone(), edge.to_name.clone(), relation);
        }
        graph
    }

    /// The edges as bare [`AstReference`] values (compat with `graph.rs`).
    #[must_use]
    pub fn ast_references(&self) -> Vec<AstReference> {
        self.to_ast_graph().edges
    }
}

/// Knobs that trade index size against reference coverage.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExtractOptions {
    /// Emit [`RefKind::Ident`] rows (bare identifier reads, mostly locals).
    ///
    /// Off by default. Calls, member reads, types and imports are always
    /// emitted, and those are what `usages`/`callers`/`refs` answer from.
    /// Bare local-variable reads nearly double the reference row count — on
    /// Signal-Android (5.6k Kotlin/Java files) they are the difference between
    /// a ~350 MB and a ~600 MB symbol index — while almost never being what
    /// someone searching for a symbol meant.
    pub include_plain_identifiers: bool,
    /// Store the trimmed source line on each reference/edge.
    pub include_context: bool,
    /// Hard cap on a stored context line.
    pub max_context_chars: usize,
    /// Minimum identifier length for [`RefKind::Ident`] rows.
    pub min_identifier_len: usize,
}

impl Default for ExtractOptions {
    fn default() -> Self {
        Self {
            include_plain_identifiers: false,
            include_context: true,
            max_context_chars: 200,
            min_identifier_len: 3,
        }
    }
}

/// Extract with default options; `language` may be `None` to auto-detect.
#[must_use]
pub fn extract_symbols(source: &str, file_path: &str, language: Option<&str>) -> FileSymbols {
    extract_symbols_with(source, file_path, language, &ExtractOptions::default())
}

/// Extract definitions, references and edges from one source file.
#[must_use]
pub fn extract_symbols_with(
    source: &str,
    file_path: &str,
    language: Option<&str>,
    options: &ExtractOptions,
) -> FileSymbols {
    let language = language
        .or_else(|| detect_language(file_path))
        .unwrap_or("unknown");
    let mut empty = FileSymbols {
        file_path: file_path.to_owned(),
        language: language.to_owned(),
        ..FileSymbols::default()
    };
    let Some(config) = language_config(language) else {
        return empty;
    };
    if !config.available_in_rust {
        return empty;
    }
    let Some(mut parser) = parser_for(language) else {
        return empty;
    };
    let Some(tree) = parser.parse(source, None) else {
        return empty;
    };
    let spec = spec_for(language);
    let mut extractor = Extractor {
        src: source.as_bytes(),
        lines: source.split('\n').collect(),
        options,
        config,
        spec,
        out: std::mem::take(&mut empty),
        scope: Vec::new(),
        call_sites: HashSet::new(),
        def_sites: HashSet::new(),
        type_sites: HashSet::new(),
        member_sites: HashSet::new(),
    };
    extractor.visit(tree.root_node(), None, false, 0);
    extractor.out
}

// ---------------------------------------------------------------------------
// language tables
// ---------------------------------------------------------------------------

/// Node kinds `chunker::LanguageConfig` does not list but a symbol index needs.
///
/// This intentionally *extends* `LanguageConfig` rather than replacing it:
/// `class_types`/`function_types`/`wrapper_types`/`import_types` still come
/// from there, so the two stay in sync for the shapes they agree on.
#[derive(Debug, Clone, Copy)]
struct SymbolSpec {
    /// Extra class-like kinds (scopes that make their members "methods").
    extra_class_types: &'static [&'static str],
    /// Extra function-like kinds.
    extra_function_types: &'static [&'static str],
    /// Kinds that declare one or more named properties/fields/constants.
    property_types: &'static [&'static str],
    /// Extra span-forwarding wrappers.
    extra_wrapper_types: &'static [&'static str],
    /// Call-expression kinds.
    call_types: &'static [&'static str],
}

const DEFAULT_SPEC: SymbolSpec = SymbolSpec {
    extra_class_types: &[],
    extra_function_types: &[],
    property_types: &[],
    extra_wrapper_types: &[],
    call_types: &["call_expression"],
};

/// Per-language node-kind table, and the honest coverage record.
///
/// Solid — definitions, calls and subtyping all verified against real code:
/// **python**, **typescript**, **javascript**, **rust**, **java**, **kotlin**.
///
/// Good, with a documented hole:
/// * **go** — definitions/calls/receivers are exact, but Go satisfies
///   interfaces *structurally*, so there are no `implements` edges at all and
///   `implementations()` is always empty for Go.
/// * **dart** — definitions/calls/heritage verified; `with M` is recorded as
///   `implements` because the mixin sits inside the `superclass` clause.
///
/// Partial, and lower-confidence:
/// * **cpp** — out-of-line `T Class::method()` resolves its owning type, and
///   in-class declarations are picked up, so a method with both a header
///   declaration and a definition yields two rows. Namespaces become `module`
///   scopes; templates keep the `template<...>` line in their span.
/// * **c** — functions and struct/enum/union tags only. No typedef names, no
///   macro definitions, and struct *members* are not definitions.
///
/// Known grammar-level gaps that are not fixable here: tree-sitter-kotlin-ng
/// mis-parses an annotated `annotation class Foo()` (annotation + empty
/// parens) into an `infix_expression`, so those declarations are invisible —
/// 5 real files out of 5 598 in Signal-Android, all of them Kotlin
/// `typealias`-only or annotation-only files.
fn spec_for(language: &str) -> &'static SymbolSpec {
    match language {
        "python" => &SymbolSpec {
            call_types: &["call"],
            ..DEFAULT_SPEC
        },
        "java" => &SymbolSpec {
            extra_class_types: &["record_declaration", "annotation_type_declaration"],
            extra_function_types: &["compact_constructor_declaration"],
            property_types: &["field_declaration", "constant_declaration"],
            extra_wrapper_types: &[],
            call_types: &[
                "method_invocation",
                "object_creation_expression",
                "explicit_constructor_invocation",
            ],
        },
        "kotlin" => &SymbolSpec {
            // `interface X {}` also parses as `class_declaration` in
            // tree-sitter-kotlin-ng; `companion object` and `typealias` have
            // their own nodes and the chunker lists neither.
            extra_class_types: &["companion_object", "type_alias"],
            extra_function_types: &["secondary_constructor", "anonymous_initializer"],
            property_types: &["property_declaration"],
            extra_wrapper_types: &[],
            call_types: &["call_expression"],
        },
        "typescript" => &SymbolSpec {
            extra_class_types: &["enum_declaration", "type_alias_declaration"],
            extra_function_types: &[
                "method_signature",
                "abstract_method_signature",
                "function_signature",
                "generator_function_declaration",
            ],
            property_types: &["public_field_definition"],
            extra_wrapper_types: &["lexical_declaration", "variable_declaration"],
            call_types: &["call_expression", "new_expression"],
        },
        "javascript" => &SymbolSpec {
            extra_class_types: &[],
            extra_function_types: &["generator_function_declaration"],
            property_types: &["field_definition", "public_field_definition"],
            extra_wrapper_types: &["lexical_declaration", "variable_declaration"],
            call_types: &["call_expression", "new_expression"],
        },
        "go" => &SymbolSpec {
            // `type_declaration` groups one or more `type_spec`s; the spec is
            // where the name and the struct/interface kind live.
            extra_class_types: &["type_spec"],
            // `method_elem` is an interface method requirement.
            extra_function_types: &["method_elem"],
            property_types: &[],
            extra_wrapper_types: &["type_declaration"],
            call_types: &["call_expression"],
        },
        "rust" => &SymbolSpec {
            extra_class_types: &["mod_item", "union_item", "type_item"],
            extra_function_types: &["function_signature_item"],
            property_types: &["const_item", "static_item"],
            extra_wrapper_types: &[],
            call_types: &["call_expression", "macro_invocation"],
        },
        "c" => &DEFAULT_SPEC,
        "cpp" => &SymbolSpec {
            extra_class_types: &["namespace_definition"],
            extra_function_types: &[],
            property_types: &[],
            extra_wrapper_types: &[],
            call_types: &["call_expression"],
        },
        "dart" => &SymbolSpec {
            extra_class_types: &[],
            extra_function_types: &[],
            property_types: &[],
            // `class_member` already comes from LanguageConfig; `declaration`
            // is the extra hop for abstract members (`int area();`).
            extra_wrapper_types: &["declaration"],
            call_types: &["call_expression", "new_expression"],
        },
        _ => &DEFAULT_SPEC,
    }
}

/// Duplicate of `chunker::parser_for`, which is private to that module.
///
/// See the migration notes: `chunker::parser_for` should become
/// `pub(crate)` so this copy can go away. Unlike the chunker's version this
/// one refuses an unknown language instead of silently parsing it as Python.
fn parser_for(language: &str) -> Option<Parser> {
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
        _ => return None,
    };
    let mut parser = Parser::new();
    parser.set_language(&ts_language).ok()?;
    Some(parser)
}

/// Identifier-ish leaf node kinds across the ten grammars.
const IDENT_KINDS: &[&str] = &[
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
    "simple_identifier",
    "namespace_identifier",
    "package_identifier",
    "statement_identifier",
    "identifier_dollar_escaped",
    "shorthand_property_identifier",
    "shorthand_property_identifier_pattern",
];

fn is_ident_leaf(kind: &str) -> bool {
    IDENT_KINDS.contains(&kind)
}

/// Subtrees that must never be searched when looking for a *name*.
const OPAQUE_KINDS: &[&str] = &[
    "arguments",
    "argument_list",
    "value_arguments",
    "type_arguments",
    "template_argument_list",
    "parameters",
    "parameter_list",
    "formal_parameters",
    "formal_parameter_list",
    "function_value_parameters",
    "class_parameters",
    "type_parameters",
    "template_parameter_list",
    "block",
    "class_body",
    "declaration_list",
    "field_declaration_list",
    "function_body",
    "statement_block",
    "compound_statement",
    "enum_body",
    "interface_body",
    "constructor_body",
];

fn is_opaque(kind: &str) -> bool {
    OPAQUE_KINDS.contains(&kind)
}

/// Parameter containers: a direct identifier child of these is a binding site.
const PARAMETER_KINDS: &[&str] = &[
    "parameters",
    "parameter_list",
    "formal_parameters",
    "formal_parameter_list",
    "function_value_parameters",
    "class_parameters",
    "lambda_parameters",
    "typed_parameter",
    "default_parameter",
    "typed_default_parameter",
    "required_parameter",
    "optional_parameter",
    "parameter",
    "class_parameter",
    "parameter_declaration",
    "formal_parameter",
    "spread_parameter",
    "self_parameter",
];

/// Parents whose `name`/`pattern` field is a declaration, not a usage.
const BINDING_PARENT_KINDS: &[&str] = &[
    "variable_declarator",
    "variable_declaration",
    "initialized_identifier",
    "short_var_declaration",
    "enum_constant",
    "import_specifier",
    "namespace_import",
    "type_parameter",
    "type_parameter_declaration",
    "const_spec",
    "var_spec",
    "field_declaration",
    "label_statement",
];

/// Nodes that put their identifier descendants in *type* position.
const TYPE_CONTEXT_KINDS: &[&str] = &[
    "type",
    "type_identifier",
    "type_annotation",
    "type_arguments",
    "type_parameters",
    "generic_type",
    "scoped_type_identifier",
    "user_type",
    "nullable_type",
    "primary_constructor",
    "superclass",
    "superclasses",
    "super_interfaces",
    "extends_interfaces",
    "interfaces",
    "mixins",
    "class_heritage",
    "extends_clause",
    "implements_clause",
    "extends_type_clause",
    "base_class_clause",
    "delegation_specifier",
    "delegation_specifiers",
    "constructor_invocation",
    "trait_bounds",
    "type_list",
    "annotation",
    "marker_annotation",
    "modifiers",
];

/// Heritage clause kinds and the relation they express.
const HERITAGE_KINDS: &[(&str, EdgeRelation)] = &[
    ("superclasses", EdgeRelation::Inherits),
    ("superclass", EdgeRelation::Inherits),
    ("super_interfaces", EdgeRelation::Implements),
    ("extends_interfaces", EdgeRelation::Inherits),
    ("interfaces", EdgeRelation::Implements),
    ("mixins", EdgeRelation::Implements),
    ("extends_clause", EdgeRelation::Inherits),
    ("implements_clause", EdgeRelation::Implements),
    ("extends_type_clause", EdgeRelation::Inherits),
    ("base_class_clause", EdgeRelation::Inherits),
];

// ---------------------------------------------------------------------------
// walker
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct Scope {
    qualified: String,
    name: String,
    is_type: bool,
}

enum Role {
    /// Forward the span to the definition inside, keep walking.
    Wrapper,
    /// A definition of the given normalized kind.
    Definition(&'static str),
    /// One or more named properties declared by this node.
    Property,
    /// Nothing special.
    Plain,
}

struct Extractor<'a> {
    src: &'a [u8],
    lines: Vec<&'a str>,
    options: &'a ExtractOptions,
    config: &'static LanguageConfig,
    spec: &'static SymbolSpec,
    out: FileSymbols,
    scope: Vec<Scope>,
    call_sites: HashSet<usize>,
    def_sites: HashSet<usize>,
    type_sites: HashSet<usize>,
    member_sites: HashSet<usize>,
}

impl Extractor<'_> {
    fn text(&self, node: Node<'_>) -> &str {
        node.utf8_text(self.src).unwrap_or("")
    }

    fn line_text(&self, row: usize) -> String {
        let raw = self.lines.get(row).copied().unwrap_or("").trim();
        if !self.options.include_context {
            return String::new();
        }
        raw.chars().take(self.options.max_context_chars).collect()
    }

    fn container(&self) -> (String, String) {
        self.scope
            .last()
            .map(|scope| (scope.qualified.clone(), scope.name.clone()))
            .unwrap_or_default()
    }

    fn is_class_type(&self, kind: &str) -> bool {
        self.config.class_types.contains(&kind) || self.spec.extra_class_types.contains(&kind)
    }

    fn is_function_type(&self, kind: &str) -> bool {
        self.config.function_types.contains(&kind) || self.spec.extra_function_types.contains(&kind)
    }

    fn is_wrapper_type(&self, kind: &str) -> bool {
        self.config.wrapper_types.contains(&kind) || self.spec.extra_wrapper_types.contains(&kind)
    }

    fn role(&self, node: Node<'_>, suppressed: bool) -> Role {
        let kind = node.kind();
        if self.is_wrapper_type(kind) {
            return Role::Wrapper;
        }
        if suppressed {
            return Role::Plain;
        }
        if self.spec.property_types.contains(&kind) {
            // Only fields of a type (or file-level constants) are symbols;
            // a `val` inside a function body is a local, and indexing those
            // buries the real definitions under one row per local variable.
            if self.scope.last().is_none_or(|scope| scope.is_type) {
                return Role::Property;
            }
            return Role::Plain;
        }
        if self.is_class_type(kind) {
            return Role::Definition(self.class_kind(node));
        }
        if self.is_function_type(kind) {
            return Role::Definition(self.function_kind(node));
        }
        // C++ headers declare methods as `field_declaration`s whose declarator
        // is a `function_declarator`; the same node with a plain declarator is
        // a data member.
        if kind == "field_declaration" && self.out.language == "cpp" {
            if let Some(declarator) = node.child_by_field_name("declarator") {
                if declarator.kind() == "function_declarator" {
                    return Role::Definition("method");
                }
            }
        }
        // `const foo = () => {}` / `const foo = function () {}`.
        if kind == "variable_declarator" {
            if let Some(value) = node.child_by_field_name("value") {
                if matches!(
                    value.kind(),
                    "arrow_function" | "function_expression" | "function" | "generator_function"
                ) {
                    return Role::Definition(if self.scope.last().is_some_and(|s| s.is_type) {
                        "method"
                    } else {
                        "function"
                    });
                }
            }
        }
        Role::Plain
    }

    fn class_kind(&self, node: Node<'_>) -> &'static str {
        let kind = node.kind();
        match kind {
            "struct_item" | "struct_specifier" | "struct_declaration" => return "struct",
            "enum_item" | "enum_specifier" | "enum_declaration" => return "enum",
            "trait_item" => return "trait",
            "impl_item" => return "impl",
            "mod_item" | "namespace_definition" => return "module",
            "union_item" | "union_specifier" => return "union",
            "type_item" | "type_alias_declaration" | "type_alias" => return "type",
            "object_declaration" | "companion_object" => return "object",
            "mixin_declaration" => return "mixin",
            "extension_declaration" => return "extension",
            "record_declaration" => return "record",
            "type_spec" => {
                return match node.child_by_field_name("type").map(|ty| ty.kind()) {
                    Some("struct_type") => "struct",
                    Some("interface_type") => "interface",
                    _ => "type",
                }
            }
            _ => {}
        }
        if kind.contains("interface") {
            return "interface";
        }
        // Kotlin models `interface X {}` as a `class_declaration` carrying an
        // `interface` keyword token, and `enum class X` as a `class_modifier`
        // one level down inside `modifiers`.
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            match child.kind() {
                "interface" => return "interface",
                "enum" => return "enum",
                "modifiers" => {
                    let mut inner = child.walk();
                    for modifier in child.children(&mut inner) {
                        let mut leaf = modifier.walk();
                        if modifier.kind() == "class_modifier"
                            && modifier
                                .children(&mut leaf)
                                .any(|token| token.kind() == "enum")
                        {
                            return "enum";
                        }
                    }
                }
                _ => {}
            }
        }
        "class"
    }

    fn function_kind(&self, node: Node<'_>) -> &'static str {
        let kind = node.kind();
        if kind.contains("constructor") {
            return "constructor";
        }
        if kind.starts_with("getter") {
            return "getter";
        }
        if kind.starts_with("setter") {
            return "setter";
        }
        if kind == "anonymous_initializer" {
            return "initializer";
        }
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            match child.kind() {
                "get" => return "getter",
                "set" => return "setter",
                _ => {}
            }
        }
        if self.scope.last().is_some_and(|scope| scope.is_type) {
            "method"
        } else {
            "function"
        }
    }

    fn visit(&mut self, node: Node<'_>, outer: Option<Node<'_>>, suppressed: bool, depth: usize) {
        if depth > 128 {
            return;
        }
        match self.role(node, suppressed) {
            Role::Wrapper => {
                let forwarded = outer.or(Some(node));
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    self.visit(child, forwarded, suppressed, depth + 1);
                }
            }
            Role::Definition(kind) => self.visit_definition(node, outer, kind, depth),
            Role::Property => self.visit_property(node, outer, depth),
            Role::Plain => {
                self.visit_plain(node, suppressed, depth);
            }
        }
    }

    fn visit_definition(
        &mut self,
        node: Node<'_>,
        outer: Option<Node<'_>>,
        kind: &'static str,
        depth: usize,
    ) {
        let span = outer.unwrap_or(node);
        let name_node = definition_name_node(node);
        let name = name_node
            .map(|found| self.text(found).to_owned())
            .unwrap_or_default();
        let name = if name.is_empty() && kind == "object" {
            "Companion".to_owned()
        } else {
            name
        };
        if name.is_empty() {
            // Anonymous: no definition row, but still walk for references.
            self.visit_plain(node, false, depth);
            return;
        }
        if let Some(found) = name_node {
            self.def_sites.insert(found.id());
        }
        // C++ `Greeter::hello`, Go `func (g *Greeter) Hello`: the owning type
        // is spelled out at the definition site rather than lexically around
        // it, so it beats whatever scope we happen to be standing in.
        let explicit_parent = name_node
            .and_then(qualified_scope_name)
            .or_else(|| receiver_type_node(node))
            .map(|scope_node| {
                self.text(scope_node)
                    .rsplit("::")
                    .next()
                    .unwrap_or_default()
                    .to_owned()
            })
            .filter(|parent| !parent.is_empty());
        let kind = match (kind, explicit_parent.is_some()) {
            ("function", true) => "method",
            (other, _) => other,
        };
        let (scope_qualified, scope_name) = self.container();
        let parent_name = explicit_parent.clone().unwrap_or(scope_name);
        let qualified = match (explicit_parent, scope_qualified.as_str()) {
            (Some(explicit), _) => format!("{explicit}.{name}"),
            (None, "") => name.clone(),
            (None, prefix) => format!("{prefix}.{name}"),
        };
        let (name_line, name_col) = name_node
            .map(|found| {
                (
                    found.start_position().row + 1,
                    found.start_position().column,
                )
            })
            .unwrap_or((span.start_position().row + 1, 0));

        self.out.definitions.push(SymbolDef {
            file_path: self.out.file_path.clone(),
            name: name.clone(),
            qualified_name: qualified.clone(),
            parent_name,
            kind: kind.to_owned(),
            language: self.out.language.clone(),
            signature: self.signature_of(node),
            start_line: span.start_position().row + 1,
            end_line: span.end_position().row + 1,
            name_line,
            name_col,
        });

        self.collect_heritage(node, &name, &qualified);

        let is_type = !matches!(
            kind,
            "function" | "method" | "constructor" | "getter" | "setter" | "initializer"
        );
        self.scope.push(Scope {
            qualified,
            name,
            is_type,
        });
        let signature_field = node
            .child_by_field_name("signature")
            .map(|found| found.id());
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            let suppress_child = signature_field == Some(child.id());
            self.visit(child, None, suppress_child, depth + 1);
        }
        self.scope.pop();
    }

    fn visit_property(&mut self, node: Node<'_>, outer: Option<Node<'_>>, depth: usize) {
        let span = outer.unwrap_or(node);
        let (scope_qualified, scope_name) = self.container();
        for name_node in property_name_nodes(node) {
            let name = self.text(name_node).to_owned();
            if name.is_empty() {
                continue;
            }
            self.def_sites.insert(name_node.id());
            let qualified = if scope_qualified.is_empty() {
                name.clone()
            } else {
                format!("{scope_qualified}.{name}")
            };
            self.out.definitions.push(SymbolDef {
                file_path: self.out.file_path.clone(),
                name,
                qualified_name: qualified,
                parent_name: scope_name.clone(),
                kind: "property".to_owned(),
                language: self.out.language.clone(),
                signature: self.signature_of(node),
                start_line: span.start_position().row + 1,
                end_line: span.end_position().row + 1,
                name_line: name_node.start_position().row + 1,
                name_col: name_node.start_position().column,
            });
        }
        self.visit_plain(node, false, depth);
    }

    fn visit_plain(&mut self, node: Node<'_>, suppressed: bool, depth: usize) {
        let kind = node.kind();
        if self.spec.call_types.contains(&kind) {
            if let Some(callee) = call_target(node) {
                self.call_sites.insert(callee.id());
                self.record_call(callee);
            }
        }
        if MEMBER_ACCESS_KINDS.contains(&kind) {
            if let Some(member) = member_target(node) {
                self.member_sites.insert(member.id());
            }
        }
        if is_ident_leaf(kind) {
            self.record_identifier(node);
        }
        // `import` is what tree-sitter-kotlin-ng actually emits; the chunker's
        // `import_header` never matches. Package declarations are deliberately
        // excluded: they are not imports of anything.
        if self.config.import_types.contains(&kind) || kind == "import" {
            self.record_import(node);
        }
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            self.visit(child, None, suppressed, depth + 1);
        }
    }

    fn record_call(&mut self, callee: Node<'_>) {
        let name = self.text(callee).to_owned();
        if name.is_empty() {
            return;
        }
        let (from_qualified, from_name) = self.container();
        let row = callee.start_position().row;
        self.out.edges.push(SymbolEdge {
            file_path: self.out.file_path.clone(),
            from_name,
            from_qualified,
            to_name: name,
            relation: EdgeRelation::Calls,
            language: self.out.language.clone(),
            line: row + 1,
            context: self.line_text(row),
        });
    }

    fn record_import(&mut self, node: Node<'_>) {
        let row = node.start_position().row;
        let context = self.line_text(row);
        let mut seen = BTreeSet::new();
        for name_node in import_names(node) {
            let name = self.text(name_node).to_owned();
            if name.is_empty() || !seen.insert(name.clone()) {
                continue;
            }
            self.out.edges.push(SymbolEdge {
                file_path: self.out.file_path.clone(),
                from_name: String::new(),
                from_qualified: String::new(),
                to_name: name,
                relation: EdgeRelation::Imports,
                language: self.out.language.clone(),
                line: row + 1,
                context: context.clone(),
            });
        }
    }

    fn record_identifier(&mut self, node: Node<'_>) {
        if self.def_sites.contains(&node.id()) || is_binding_site(node) {
            return;
        }
        let name = self.text(node).to_owned();
        if name.is_empty() {
            return;
        }
        let kind = if self.call_sites.contains(&node.id()) {
            RefKind::Call
        } else if in_import(node) {
            RefKind::Import
        } else if self.type_sites.contains(&node.id()) || in_type_context(node) {
            RefKind::Type
        } else if self.member_sites.contains(&node.id()) {
            RefKind::Member
        } else {
            RefKind::Ident
        };
        if kind == RefKind::Ident
            && (!self.options.include_plain_identifiers
                || name.chars().count() < self.options.min_identifier_len)
        {
            return;
        }
        let (container, container_name) = self.container();
        let row = node.start_position().row;
        self.out.references.push(SymbolRef {
            file_path: self.out.file_path.clone(),
            name,
            kind,
            container,
            container_name,
            language: self.out.language.clone(),
            line: row + 1,
            col: node.start_position().column,
            context: self.line_text(row),
        });
    }

    fn collect_heritage(&mut self, node: Node<'_>, name: &str, qualified: &str) {
        let mut clauses: Vec<(Node<'_>, EdgeRelation)> = Vec::new();
        collect_heritage_clauses(node, 0, &mut clauses);
        // `impl Trait for Type` is the Rust implements edge.
        if node.kind() == "impl_item" {
            if let Some(trait_node) = node.child_by_field_name("trait") {
                clauses.push((trait_node, EdgeRelation::Implements));
            }
        }
        for (clause, relation) in clauses {
            for base in heritage_names(clause) {
                let base_name = self.text(base).to_owned();
                if base_name.is_empty() {
                    continue;
                }
                // Base types read as type references too — Python's
                // `class Greeter(Base)` has no `type_identifier` node.
                self.type_sites.insert(base.id());
                let row = base.start_position().row;
                self.out.edges.push(SymbolEdge {
                    file_path: self.out.file_path.clone(),
                    from_name: name.to_owned(),
                    from_qualified: qualified.to_owned(),
                    to_name: base_name,
                    relation,
                    language: self.out.language.clone(),
                    line: row + 1,
                    context: self.line_text(row),
                });
            }
        }
    }

    fn signature_of(&self, node: Node<'_>) -> String {
        let start = node.start_byte();
        let end = body_start_byte(node).unwrap_or_else(|| {
            let text = self.text(node);
            start + text.lines().next().map_or(text.len(), str::len)
        });
        let end = end.max(start).min(self.src.len());
        let raw = std::str::from_utf8(&self.src[start..end]).unwrap_or_default();
        collapse_whitespace(raw)
    }
}

// ---------------------------------------------------------------------------
// node helpers
// ---------------------------------------------------------------------------

fn collapse_whitespace(value: &str) -> String {
    // Some grammars have no separate body node (Go's `type_spec` inlines the
    // struct literal), so cut at the opening brace as a backstop.
    let value = value.split_once('{').map_or(value, |(head, _)| head);
    let mut out = String::new();
    for token in value.split_whitespace() {
        if !out.is_empty() {
            out.push(' ');
        }
        out.push_str(token);
    }
    out.truncate(
        out.char_indices()
            .nth(240)
            .map_or(out.len(), |(index, _)| index),
    );
    out.trim_end_matches([';', '(', ':', '=']).trim().to_owned()
}

const BODY_KINDS: &[&str] = &[
    "block",
    "class_body",
    "declaration_list",
    "field_declaration_list",
    "function_body",
    "statement_block",
    "compound_statement",
    "enum_body",
    "interface_body",
    "constructor_body",
    "enum_class_body",
];

fn body_start_byte(node: Node<'_>) -> Option<usize> {
    if let Some(body) = node.child_by_field_name("body") {
        return Some(body.start_byte());
    }
    let mut cursor = node.walk();
    let found = node
        .children(&mut cursor)
        .find(|child| BODY_KINDS.contains(&child.kind()))
        .map(|child| child.start_byte());
    found
}

/// Level-order search for the `name` field, refusing to enter bodies and
/// parameter lists (Java's `formal_parameter` also has a `name` field).
fn field_name_search(node: Node<'_>) -> Option<Node<'_>> {
    let mut level = vec![node];
    for _ in 0..4 {
        let mut next = Vec::new();
        for parent in &level {
            let mut cursor = parent.walk();
            for (index, child) in parent.children(&mut cursor).enumerate() {
                let field = parent.field_name_for_child(index as u32);
                if is_opaque(child.kind()) || field == Some("body") {
                    continue;
                }
                if field == Some("name") {
                    return reduce_to_ident(child);
                }
                next.push(child);
            }
        }
        if next.is_empty() {
            break;
        }
        level = next;
    }
    None
}

fn reduce_to_ident(node: Node<'_>) -> Option<Node<'_>> {
    if is_ident_leaf(node.kind()) {
        return Some(node);
    }
    last_ident_leaf(node)
}

fn last_ident_leaf(node: Node<'_>) -> Option<Node<'_>> {
    let mut found = None;
    collect_ident_leaves(node, node, &mut |leaf| found = Some(leaf));
    found
}

fn first_ident_leaf(node: Node<'_>) -> Option<Node<'_>> {
    let mut found = None;
    collect_ident_leaves(node, node, &mut |leaf| {
        if found.is_none() {
            found = Some(leaf);
        }
    });
    found
}

fn collect_ident_leaves<'t>(root: Node<'t>, node: Node<'t>, sink: &mut impl FnMut(Node<'t>)) {
    if node.id() != root.id() && is_opaque(node.kind()) {
        return;
    }
    if is_ident_leaf(node.kind()) {
        sink(node);
        return;
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        collect_ident_leaves(root, child, sink);
    }
}

fn declarator_name(node: Node<'_>) -> Option<Node<'_>> {
    let mut current = node;
    for _ in 0..6 {
        if is_ident_leaf(current.kind()) {
            return Some(current);
        }
        if current.kind() == "qualified_identifier" {
            return current
                .child_by_field_name("name")
                .and_then(reduce_to_ident)
                .or_else(|| last_ident_leaf(current));
        }
        let Some(next) = current.child_by_field_name("declarator") else {
            return last_ident_leaf(current);
        };
        current = next;
    }
    None
}

/// The `Greeter` in a C++ out-of-line `Greeter::hello` definition.
fn qualified_scope_name(name_node: Node<'_>) -> Option<Node<'_>> {
    let parent = name_node.parent()?;
    if parent.kind() != "qualified_identifier" {
        return None;
    }
    parent.child_by_field_name("scope")
}

fn definition_name_node(node: Node<'_>) -> Option<Node<'_>> {
    if node.kind() == "impl_item" {
        return node.child_by_field_name("type").and_then(last_ident_leaf);
    }
    // A direct `name` field wins. Checking it before `declarator` keeps C++
    // out-of-line definitions (`std::string Greeter::hello(...)`) from
    // resolving to the *return type's* `name` field two levels down.
    if let Some(found) = node.child_by_field_name("name").and_then(reduce_to_ident) {
        return Some(found);
    }
    if let Some(declarator) = node.child_by_field_name("declarator") {
        if let Some(found) = declarator_name(declarator) {
            return Some(found);
        }
    }
    // Dart wraps the name two hops down: `method_declaration` ->
    // `method_signature` -> `function_signature` -> `name`.
    if let Some(signature) = node.child_by_field_name("signature") {
        if let Some(found) = definition_name_node(signature) {
            return Some(found);
        }
    }
    if let Some(found) = field_name_search(node) {
        return Some(found);
    }
    let mut cursor = node.walk();
    let found = node
        .children(&mut cursor)
        .find(|child| is_ident_leaf(child.kind()));
    found
}

/// Go puts the owning type in the receiver: `func (g *Greeter) Hello()`.
fn receiver_type_node(node: Node<'_>) -> Option<Node<'_>> {
    let receiver = node.child_by_field_name("receiver")?;
    let mut cursor = receiver.walk();
    for child in receiver.children(&mut cursor) {
        if child.kind() != "parameter_declaration" {
            continue;
        }
        if let Some(found) = child.child_by_field_name("type").and_then(last_ident_leaf) {
            return Some(found);
        }
    }
    None
}

fn property_name_nodes(node: Node<'_>) -> Vec<Node<'_>> {
    let mut out = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            // Java `private int x, y;`
            "variable_declarator" => {
                if let Some(name) = child.child_by_field_name("name").and_then(reduce_to_ident) {
                    out.push(name);
                }
            }
            // Kotlin `val x: Foo = ...` — the *first* identifier is the
            // property; the last one is its type.
            "variable_declaration" => {
                if let Some(name) = first_ident_leaf(child) {
                    out.push(name);
                }
            }
            _ => {}
        }
    }
    if out.is_empty() {
        // TS `public_field_definition`, Rust `const_item`/`static_item`.
        if let Some(name) = node.child_by_field_name("name").and_then(reduce_to_ident) {
            out.push(name);
        }
    }
    out
}

/// Nodes whose identifier descendants are argument values, not the callee.
const ARGUMENT_KINDS: &[&str] = &[
    "arguments",
    "argument_list",
    "value_arguments",
    "type_arguments",
    "template_argument_list",
];

/// Dotted access expressions: `obj.field`, `obj?.field`, `pkg::item`.
const MEMBER_ACCESS_KINDS: &[&str] = &[
    "member_expression",
    "navigation_expression",
    "attribute",
    "field_expression",
    "selector_expression",
    "field_access",
];

/// The member side of `obj.member`.
fn member_target(node: Node<'_>) -> Option<Node<'_>> {
    for field in ["property", "attribute", "field", "name"] {
        if let Some(child) = node.child_by_field_name(field) {
            if let Some(found) = last_ident_leaf(child) {
                return Some(found);
            }
        }
    }
    // Kotlin's `navigation_expression` labels nothing; the member is the last
    // identifier outside the receiver's argument list.
    last_ident_leaf(node)
}

fn call_target(node: Node<'_>) -> Option<Node<'_>> {
    for field in ["function", "name", "constructor", "macro"] {
        if let Some(child) = node.child_by_field_name(field) {
            if let Some(found) = last_ident_leaf(child) {
                return Some(found);
            }
        }
    }
    // Java `new Foo()` uses `type`; Kotlin calls have no field at all.
    if node.kind() == "object_creation_expression" {
        if let Some(child) = node.child_by_field_name("type") {
            return last_ident_leaf(child);
        }
    }
    let mut cursor = node.walk();
    let candidate = node
        .children(&mut cursor)
        .find(|child| child.is_named() && !ARGUMENT_KINDS.contains(&child.kind()))?;
    last_ident_leaf(candidate)
}

/// Dotted forms that name one thing: keep only the final segment, so
/// `import java.util.List` yields `List` and `class F : Job.Factory<T>`
/// records `Factory`, not `Job` *and* `Factory`.
const DOTTED_KINDS: &[&str] = &[
    "dotted_name",
    "scoped_identifier",
    "qualified_identifier",
    "scoped_type_identifier",
    "scoped_use_list",
    "attribute",
    // Kotlin spells `Job.Factory<T>` as one `user_type`.
    "user_type",
];

fn import_names(node: Node<'_>) -> Vec<Node<'_>> {
    let mut out = Vec::new();
    import_walk(node, node, &mut out);
    out
}

fn import_walk<'t>(root: Node<'t>, node: Node<'t>, out: &mut Vec<Node<'t>>) {
    if node.id() != root.id() && DOTTED_KINDS.contains(&node.kind()) {
        if let Some(last) = last_ident_leaf(node) {
            out.push(last);
        }
        return;
    }
    if is_ident_leaf(node.kind()) {
        out.push(node);
        return;
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        import_walk(root, child, out);
    }
}

fn is_binding_site(node: Node<'_>) -> bool {
    let Some(parent) = node.parent() else {
        return false;
    };
    let parent_kind = parent.kind();
    let field = field_name_of(parent, node);
    if PARAMETER_KINDS.contains(&parent_kind)
        && matches!(field, None | Some("name") | Some("pattern"))
    {
        return true;
    }
    if BINDING_PARENT_KINDS.contains(&parent_kind)
        && matches!(field, None | Some("name") | Some("pattern"))
    {
        return true;
    }
    false
}

fn field_name_of<'t>(parent: Node<'t>, child: Node<'t>) -> Option<&'static str> {
    let mut cursor = parent.walk();
    for (index, candidate) in parent.children(&mut cursor).enumerate() {
        if candidate.id() == child.id() {
            return parent.field_name_for_child(index as u32);
        }
    }
    None
}

fn in_type_context(node: Node<'_>) -> bool {
    if node.kind() == "type_identifier" {
        return true;
    }
    let mut current = node.parent();
    for _ in 0..3 {
        let Some(parent) = current else {
            return false;
        };
        if TYPE_CONTEXT_KINDS.contains(&parent.kind()) {
            return true;
        }
        current = parent.parent();
    }
    false
}

const IMPORT_CONTEXT_KINDS: &[&str] = &[
    "import_statement",
    "import_from_statement",
    "import_declaration",
    "import_header",
    "import",
    "import_spec",
    "import_or_export",
    "library_import",
    "import_specification",
    "preproc_include",
    "use_declaration",
    "package_header",
    "package_declaration",
    "package_clause",
    "part_directive",
    "library_name",
];

fn in_import(node: Node<'_>) -> bool {
    let mut current = node.parent();
    for _ in 0..6 {
        let Some(parent) = current else {
            return false;
        };
        if IMPORT_CONTEXT_KINDS.contains(&parent.kind()) {
            return true;
        }
        current = parent.parent();
    }
    false
}

/// Gather the heritage clauses of a definition.
///
/// Clauses nest: TypeScript hangs `extends_clause`/`implements_clause` off a
/// `class_heritage`, and Dart hides `mixins` inside `superclass`. Each nested
/// clause is collected on its own so it keeps its own relation, and
/// [`heritage_walk`] then refuses to re-enter them.
fn collect_heritage_clauses<'t>(
    node: Node<'t>,
    depth: usize,
    out: &mut Vec<(Node<'t>, EdgeRelation)>,
) {
    if depth > 2 {
        return;
    }
    let mut cursor = node.walk();
    for (index, child) in node.children(&mut cursor).enumerate() {
        // Python's `superclasses` clause *is* an `argument_list`, so the
        // heritage match has to run before the opaque-subtree skip.
        let field = node.field_name_for_child(index as u32);
        let matched = HERITAGE_KINDS
            .iter()
            .find(|(kind, _)| *kind == child.kind() || Some(*kind) == field)
            .map(|(_, relation)| *relation);
        if let Some(relation) = matched {
            out.push((child, relation));
            collect_heritage_clauses(child, depth + 1, out);
            continue;
        }
        if is_opaque(child.kind()) {
            continue;
        }
        if child.kind() == "delegation_specifiers" {
            let mut inner = child.walk();
            for grandchild in child.children(&mut inner) {
                if grandchild.kind() != "delegation_specifier" {
                    continue;
                }
                // `Base()` (a constructor invocation) is the superclass; a
                // bare `Shape` is an implemented interface. That is the only
                // signal Kotlin syntax gives.
                let mut ctor = grandchild.walk();
                let relation = if grandchild
                    .children(&mut ctor)
                    .any(|great| great.kind() == "constructor_invocation")
                {
                    EdgeRelation::Inherits
                } else {
                    EdgeRelation::Implements
                };
                out.push((grandchild, relation));
            }
            continue;
        }
        if child.kind() == "class_heritage" {
            let before = out.len();
            collect_heritage_clauses(child, depth + 1, out);
            if out.len() == before {
                // tree-sitter-javascript puts `extends Base` straight into
                // `class_heritage` without an `extends_clause` node.
                out.push((child, EdgeRelation::Inherits));
            }
        }
    }
}

fn heritage_names(clause: Node<'_>) -> Vec<Node<'_>> {
    let mut out = Vec::new();
    heritage_walk(clause, clause, &mut out);
    out
}

fn is_heritage_clause(kind: &str) -> bool {
    kind == "class_heritage" || HERITAGE_KINDS.iter().any(|(name, _)| *name == kind)
}

/// Collect the *base type* identifiers of a heritage clause: for dotted forms
/// (`mixins.Mixin`, `com.example.Base`) keep only the final segment, and never
/// descend into constructor arguments (`Base(context)`).
fn heritage_walk<'t>(root: Node<'t>, node: Node<'t>, out: &mut Vec<Node<'t>>) {
    if node.id() != root.id()
        && (ARGUMENT_KINDS.contains(&node.kind()) || is_heritage_clause(node.kind()))
    {
        return;
    }
    if is_ident_leaf(node.kind()) {
        out.push(node);
        return;
    }
    if DOTTED_KINDS.contains(&node.kind()) {
        if let Some(last) = last_ident_leaf(node) {
            out.push(last);
        }
        return;
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        heritage_walk(root, child, out);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // -----------------------------------------------------------------
    // fixtures
    // -----------------------------------------------------------------

    const PYTHON: &str = "import os\n\
                          from a.b import C\n\
                          \n\
                          @decorator\n\
                          @mod.other(1)\n\
                          class Greeter(Base, mixins.Mixin):\n\
                          \x20   attr = 1\n\
                          \n\
                          \x20   @property\n\
                          \x20   def hello(self, name: str) -> str:\n\
                          \x20       helper()\n\
                          \x20       return f\"hello {name}\"\n\
                          \n\
                          def build_message(name: str) -> str:\n\
                          \x20   g = Greeter()\n\
                          \x20   return g.hello(name)\n";

    const TYPESCRIPT: &str = r#"import { readFileSync } from "node:fs";

export interface Shape { area(): number; }

export class Greeter extends Base implements Shape {
  private x = 1;
  hello(name: string): string {
    helper();
    return `hello ${name}`;
  }
  get value(): number { return this.x; }
}

export const arrowFn = (a: number) => a + 1;

export default function buildMessage(name: string): string {
  return new Greeter().hello(name);
}
"#;

    const JAVASCRIPT: &str = r#"import { readFileSync } from "node:fs";

export class Greeter extends Base {
  hello(name) {
    helper();
    return `hello ${name}`;
  }
}

export const arrowFn = (a) => a + 1;
"#;

    const RUST: &str = r#"use std::fmt::Display;

pub struct Greeter { field: u32 }

pub trait Speak { fn speak(&self); }

impl Speak for Greeter {
    fn speak(&self) { helper(); }
}

impl Greeter {
    pub fn hello<T: Display>(&self, name: T) -> String {
        format!("hello {name}")
    }
}

pub fn build_message(name: &str) -> String {
    Greeter.hello(name)
}
"#;

    const JAVA: &str = r#"package com.example;

import java.util.List;

public class Greeter extends Base implements Shape, Other {
    private int x;

    public Greeter(int x) { this.x = x; }

    @Override
    public String hello(String name) {
        helper();
        return "hello " + name;
    }
}

interface Shape { int area(); }
"#;

    const KOTLIN: &str = r#"package com.example

import kotlinx.coroutines.launch

interface Shape {
    fun area(): Int
}

object Registry {
    fun get(): Int = 1
}

@HiltViewModel
class Greeter(val x: Int) : Base(), Shape {
    override fun area(): Int = x

    suspend fun hello(name: String): String {
        helper()
        return "hello $name"
    }

    companion object {
        const val TAG = "Greeter"
    }
}

fun buildMessage(name: String): String = Greeter(1).hello(name)
"#;

    const GO: &str = "package main\n\
                      \n\
                      import \"fmt\"\n\
                      \n\
                      type Shape interface { Area() int }\n\
                      \n\
                      type Greeter struct { X int }\n\
                      \n\
                      func (g *Greeter) Hello(name string) string {\n\
                      \thelper()\n\
                      \treturn \"hello \" + name\n\
                      }\n\
                      \n\
                      func BuildMessage(name string) string {\n\
                      \tg := Greeter{}\n\
                      \treturn g.Hello(name)\n\
                      }\n";

    const C: &str = r#"#include <stdio.h>

struct Greeter { int x; };

int hello(const char *name) {
    helper();
    return 0;
}
"#;

    const CPP: &str = r#"#include <string>

class Greeter : public Base, private Other {
public:
    std::string hello(const std::string &name);
};

std::string Greeter::hello(const std::string &name) {
    helper();
    return "hello";
}

template <typename T>
T identity(T value) { return value; }
"#;

    const DART: &str = r#"import "dart:math";

abstract class Shape { int area(); }

class Greeter extends Base with M implements Shape, Other {
  int x = 0;
  String hello(String name) {
    helper();
    return "hello $name";
  }
}

String buildMessage(String name) {
  return Greeter().hello(name);
}
"#;

    fn corpus() -> Vec<(&'static str, &'static str, &'static str)> {
        vec![
            ("python", "src/sample.py", PYTHON),
            ("typescript", "src/sample.ts", TYPESCRIPT),
            ("javascript", "src/sample.js", JAVASCRIPT),
            ("rust", "src/sample.rs", RUST),
            ("java", "src/Sample.java", JAVA),
            ("kotlin", "src/Sample.kt", KOTLIN),
            ("go", "src/sample.go", GO),
            ("c", "src/sample.c", C),
            ("cpp", "src/sample.cpp", CPP),
            ("dart", "src/sample.dart", DART),
        ]
    }

    fn extract(language: &str) -> FileSymbols {
        let (_, path, source) = corpus()
            .into_iter()
            .find(|(name, _, _)| *name == language)
            .expect("language in corpus");
        extract_symbols(source, path, Some(language))
    }

    /// Everything, including bare local reads — the widest reference set the
    /// extractor can produce, used where a test needs to prove an identifier
    /// is *absent* for a reason other than the default filter.
    fn extract_verbose(language: &str) -> FileSymbols {
        let (_, path, source) = corpus()
            .into_iter()
            .find(|(name, _, _)| *name == language)
            .expect("language in corpus");
        extract_symbols_with(
            source,
            path,
            Some(language),
            &ExtractOptions {
                include_plain_identifiers: true,
                ..ExtractOptions::default()
            },
        )
    }

    /// `(kind, qualified_name, parent_name, start_line, end_line)`.
    type DefRow = (&'static str, &'static str, &'static str, usize, usize);

    fn assert_defs(language: &str, expected: &[DefRow]) {
        let file = extract(language);
        let actual: Vec<(String, String, String, usize, usize)> = file
            .definitions
            .iter()
            .map(|def| {
                (
                    def.kind.clone(),
                    def.qualified_name.clone(),
                    def.parent_name.clone(),
                    def.start_line,
                    def.end_line,
                )
            })
            .collect();
        let expected: Vec<(String, String, String, usize, usize)> = expected
            .iter()
            .map(|(kind, qualified, parent, start, end)| {
                (
                    (*kind).to_owned(),
                    (*qualified).to_owned(),
                    (*parent).to_owned(),
                    *start,
                    *end,
                )
            })
            .collect();
        assert_eq!(actual, expected, "definitions for {language}");
    }

    // -----------------------------------------------------------------
    // definitions: exact kinds, parents and line spans
    // -----------------------------------------------------------------

    /// Decorators/annotations/`export` are *inside* the span (the R3 bug class
    /// where decorated and exported definitions were dropped entirely), while
    /// `name_line` still points at the identifier.
    #[test]
    fn definitions_have_exact_kinds_parents_and_spans() {
        assert_defs(
            "python",
            &[
                ("class", "Greeter", "", 4, 12),
                ("method", "Greeter.hello", "Greeter", 9, 12),
                ("function", "build_message", "", 14, 16),
            ],
        );
        assert_defs(
            "typescript",
            &[
                ("interface", "Shape", "", 3, 3),
                ("method", "Shape.area", "Shape", 3, 3),
                ("class", "Greeter", "", 5, 12),
                ("property", "Greeter.x", "Greeter", 6, 6),
                ("method", "Greeter.hello", "Greeter", 7, 10),
                ("getter", "Greeter.value", "Greeter", 11, 11),
                ("function", "arrowFn", "", 14, 14),
                ("function", "buildMessage", "", 16, 18),
            ],
        );
        assert_defs(
            "javascript",
            &[
                ("class", "Greeter", "", 3, 8),
                ("method", "Greeter.hello", "Greeter", 4, 7),
                ("function", "arrowFn", "", 10, 10),
            ],
        );
        assert_defs(
            "rust",
            &[
                ("struct", "Greeter", "", 3, 3),
                ("trait", "Speak", "", 5, 5),
                ("method", "Speak.speak", "Speak", 5, 5),
                ("impl", "Greeter", "", 7, 9),
                ("method", "Greeter.speak", "Greeter", 8, 8),
                ("impl", "Greeter", "", 11, 15),
                ("method", "Greeter.hello", "Greeter", 12, 14),
                ("function", "build_message", "", 17, 19),
            ],
        );
        assert_defs(
            "java",
            &[
                ("class", "Greeter", "", 5, 15),
                ("property", "Greeter.x", "Greeter", 6, 6),
                ("constructor", "Greeter.Greeter", "Greeter", 8, 8),
                ("method", "Greeter.hello", "Greeter", 10, 14),
                ("interface", "Shape", "", 17, 17),
                ("method", "Shape.area", "Shape", 17, 17),
            ],
        );
        assert_defs(
            "kotlin",
            &[
                ("interface", "Shape", "", 5, 7),
                ("method", "Shape.area", "Shape", 6, 6),
                ("object", "Registry", "", 9, 11),
                ("method", "Registry.get", "Registry", 10, 10),
                ("class", "Greeter", "", 13, 25),
                ("method", "Greeter.area", "Greeter", 15, 15),
                ("method", "Greeter.hello", "Greeter", 17, 20),
                ("object", "Greeter.Companion", "Greeter", 22, 24),
                ("property", "Greeter.Companion.TAG", "Companion", 23, 23),
                ("function", "buildMessage", "", 27, 27),
            ],
        );
        assert_defs(
            "go",
            &[
                ("interface", "Shape", "", 5, 5),
                ("method", "Shape.Area", "Shape", 5, 5),
                ("struct", "Greeter", "", 7, 7),
                ("method", "Greeter.Hello", "Greeter", 9, 12),
                ("function", "BuildMessage", "", 14, 17),
            ],
        );
        assert_defs(
            "c",
            &[
                ("struct", "Greeter", "", 3, 3),
                ("function", "hello", "", 5, 8),
            ],
        );
        assert_defs(
            "cpp",
            &[
                ("class", "Greeter", "", 3, 6),
                ("method", "Greeter.hello", "Greeter", 5, 5),
                // Out-of-line definition: the owning type comes from
                // `Greeter::hello`, not from lexical scope.
                ("method", "Greeter.hello", "Greeter", 8, 11),
                ("function", "identity", "", 13, 14),
            ],
        );
        assert_defs(
            "dart",
            &[
                ("class", "Shape", "", 3, 3),
                ("method", "Shape.area", "Shape", 3, 3),
                ("class", "Greeter", "", 5, 11),
                ("method", "Greeter.hello", "Greeter", 7, 10),
                ("function", "buildMessage", "", 13, 15),
            ],
        );
    }

    #[test]
    fn decorated_and_exported_definitions_keep_the_identifier_position() {
        // Python: span starts at the first decorator, name is on the `class`
        // line five lines later.
        let python = extract("python");
        let class = python
            .definitions
            .iter()
            .find(|def| def.name == "Greeter")
            .expect("class");
        assert_eq!((class.start_line, class.name_line), (4, 6));
        assert_eq!(class.signature, "class Greeter(Base, mixins.Mixin)");

        // Kotlin: span starts at the `@HiltViewModel` annotation.
        let kotlin = extract("kotlin");
        let annotated = kotlin
            .definitions
            .iter()
            .find(|def| def.name == "Greeter")
            .expect("class");
        assert_eq!((annotated.start_line, annotated.name_line), (13, 14));

        // Java: the `@Override` annotation is part of `modifiers`.
        let java = extract("java");
        let overridden = java
            .definitions
            .iter()
            .find(|def| def.qualified_name == "Greeter.hello")
            .expect("method");
        assert_eq!((overridden.start_line, overridden.name_line), (10, 11));

        // TypeScript: `export default function` starts at `export`.
        let typescript = extract("typescript");
        let exported = typescript
            .definitions
            .iter()
            .find(|def| def.name == "buildMessage")
            .expect("function");
        assert_eq!((exported.start_line, exported.name_line), (16, 16));
        assert_eq!(exported.name_col, 24);
    }

    // -----------------------------------------------------------------
    // calls
    // -----------------------------------------------------------------

    #[test]
    fn call_sites_resolve_to_the_callee_across_languages() {
        // (language, caller qualified name, callee, line)
        let cases: &[(&str, &str, &str, usize)] = &[
            ("python", "build_message", "hello", 16),
            ("python", "Greeter.hello", "helper", 11),
            ("typescript", "buildMessage", "hello", 17),
            ("typescript", "buildMessage", "Greeter", 17),
            ("javascript", "Greeter.hello", "helper", 5),
            ("rust", "build_message", "hello", 18),
            ("rust", "Greeter.hello", "format", 13),
            ("java", "Greeter.hello", "helper", 12),
            ("kotlin", "buildMessage", "hello", 27),
            ("kotlin", "buildMessage", "Greeter", 27),
            ("go", "BuildMessage", "Hello", 16),
            ("c", "hello", "helper", 6),
            ("cpp", "Greeter.hello", "helper", 9),
            ("dart", "buildMessage", "hello", 14),
        ];
        for (language, caller, callee, line) in cases {
            let file = extract(language);
            assert!(
                file.edges.iter().any(|edge| {
                    edge.relation == EdgeRelation::Calls
                        && edge.from_qualified == *caller
                        && edge.to_name == *callee
                        && edge.line == *line
                }),
                "{language}: expected call edge {caller} -> {callee} at line {line}, got {:?}",
                file.edges
                    .iter()
                    .filter(|edge| edge.relation == EdgeRelation::Calls)
                    .map(|edge| (edge.from_qualified.clone(), edge.to_name.clone(), edge.line))
                    .collect::<Vec<_>>()
            );
            // The same site is also a `call` reference, which is what
            // `usages`/`callers` read.
            assert!(
                file.references.iter().any(|reference| {
                    reference.kind == RefKind::Call
                        && reference.name == *callee
                        && reference.container == *caller
                        && reference.line == *line
                }),
                "{language}: expected call reference {callee} in {caller}"
            );
        }
    }

    // -----------------------------------------------------------------
    // inheritance / implementation
    // -----------------------------------------------------------------

    #[test]
    fn inheritance_edges_are_extracted_per_language() {
        // (language, subtype, supertype, relation)
        let cases: &[(&str, &str, &str, EdgeRelation)] = &[
            ("python", "Greeter", "Base", EdgeRelation::Inherits),
            // Dotted bases keep only the final segment.
            ("python", "Greeter", "Mixin", EdgeRelation::Inherits),
            ("typescript", "Greeter", "Base", EdgeRelation::Inherits),
            ("typescript", "Greeter", "Shape", EdgeRelation::Implements),
            ("javascript", "Greeter", "Base", EdgeRelation::Inherits),
            // `impl Speak for Greeter`.
            ("rust", "Greeter", "Speak", EdgeRelation::Implements),
            ("java", "Greeter", "Base", EdgeRelation::Inherits),
            ("java", "Greeter", "Shape", EdgeRelation::Implements),
            ("java", "Greeter", "Other", EdgeRelation::Implements),
            // Kotlin: `Base()` is a superclass call, bare `Shape` is not.
            ("kotlin", "Greeter", "Base", EdgeRelation::Inherits),
            ("kotlin", "Greeter", "Shape", EdgeRelation::Implements),
            ("cpp", "Greeter", "Base", EdgeRelation::Inherits),
            ("cpp", "Greeter", "Other", EdgeRelation::Inherits),
            ("dart", "Greeter", "Base", EdgeRelation::Inherits),
            ("dart", "Greeter", "M", EdgeRelation::Implements),
            ("dart", "Greeter", "Shape", EdgeRelation::Implements),
        ];
        for (language, subtype, supertype, relation) in cases {
            let file = extract(language);
            assert!(
                file.edges.iter().any(|edge| {
                    edge.relation == *relation
                        && edge.from_name == *subtype
                        && edge.to_name == *supertype
                }),
                "{language}: expected {subtype} {} {supertype}, got {:?}",
                relation.as_str(),
                file.edges
                    .iter()
                    .filter(|edge| edge.relation.is_subtyping())
                    .map(|edge| (
                        edge.from_name.clone(),
                        edge.relation.as_str(),
                        edge.to_name.clone()
                    ))
                    .collect::<Vec<_>>()
            );
        }
    }

    /// Kotlin has three declaration forms the chunker's `LanguageConfig` does
    /// not list at all: `typealias`, `companion object`, and `enum class`
    /// (which is a `class_declaration` with an `enum` class modifier).
    #[test]
    fn kotlin_declaration_forms_the_chunker_config_omits() {
        let file = extract_symbols(
            "typealias ActiveContactCount = Int\n\
             \n\
             enum class Color {\n\
             \x20   RED\n\
             }\n",
            "Types.kt",
            Some("kotlin"),
        );
        assert_eq!(
            file.definitions
                .iter()
                .map(|def| (def.kind.as_str(), def.name.as_str()))
                .collect::<Vec<_>>(),
            vec![("type", "ActiveContactCount"), ("enum", "Color")]
        );
        // The alias target is a reference, not the alias name.
        assert!(file
            .references
            .iter()
            .any(|reference| reference.name == "Int" && reference.kind == RefKind::Type));
    }

    /// A nested supertype is recorded under its own name. Signal-Android is
    /// full of `class Factory : Job.Factory<T>`; recording both `Job` and
    /// `Factory` made `implementations("Job")` return every job factory.
    #[test]
    fn dotted_supertypes_collapse_to_the_final_segment() {
        let file = extract_symbols(
            "class NoOpJob : Job(Parameters()) {\n\
             \x20   class Factory : Job.Factory<NoOpJob> {\n\
             \x20   }\n\
             }\n",
            "NoOpJob.kt",
            Some("kotlin"),
        );
        let edges: Vec<(&str, &str, &str)> = file
            .edges
            .iter()
            .filter(|edge| edge.relation.is_subtyping())
            .map(|edge| {
                (
                    edge.from_name.as_str(),
                    edge.relation.as_str(),
                    edge.to_name.as_str(),
                )
            })
            .collect();
        assert_eq!(
            edges,
            vec![
                ("NoOpJob", "inherits", "Job"),
                ("Factory", "implements", "Factory"),
            ]
        );
    }

    #[test]
    fn go_has_no_interface_satisfaction_edges() {
        // Honest negative: Go satisfies interfaces structurally, so there is
        // nothing syntactic to extract. `Greeter` implements `Shape` in the
        // fixture and the index does not know it.
        let file = extract("go");
        assert!(!file.edges.iter().any(|edge| edge.relation.is_subtyping()));
    }

    // -----------------------------------------------------------------
    // references
    // -----------------------------------------------------------------

    #[test]
    fn a_definitions_own_name_site_is_never_a_reference() {
        // Run in verbose mode so the guarantee is proven by the exclusion
        // logic, not by the default filter happening to drop the row.
        for (language, _, _) in corpus() {
            let file = extract_verbose(language);
            for def in &file.definitions {
                let collision = file.references.iter().find(|reference| {
                    reference.name == def.name
                        && reference.line == def.name_line
                        && reference.col == def.name_col
                });
                assert!(
                    collision.is_none(),
                    "{language}: {} at {}:{} was emitted as a reference: {collision:?}",
                    def.qualified_name,
                    def.name_line,
                    def.name_col
                );
            }
        }
    }

    #[test]
    fn usages_are_recorded_away_from_the_definition() {
        // `Greeter` is defined on line 6 in Python and used on line 15.
        let python = extract("python");
        let greeter: Vec<_> = python
            .references
            .iter()
            .filter(|reference| reference.name == "Greeter")
            .collect();
        assert_eq!(greeter.len(), 1);
        assert_eq!(greeter[0].line, 15);
        assert_eq!(greeter[0].kind, RefKind::Call);
        assert_eq!(greeter[0].container, "build_message");
        assert_eq!(greeter[0].context, "g = Greeter()");
    }

    #[test]
    fn parameters_and_declarators_are_not_usages() {
        let java = extract_verbose("java");
        // `String name` in the signature binds a parameter; only the *type*
        // `String` is a usage, the binding `name` is not — and `name` *is*
        // recorded where it is read, on line 13.
        assert!(java
            .references
            .iter()
            .any(|reference| reference.name == "String" && reference.line == 11));
        assert!(!java
            .references
            .iter()
            .any(|reference| reference.name == "name" && reference.line == 11));
        assert!(java
            .references
            .iter()
            .any(|reference| reference.name == "name" && reference.line == 13));
        // The field declarator `x` is a definition, not a reference.
        assert!(!java
            .references
            .iter()
            .any(|reference| reference.name == "x" && reference.line == 6));
    }

    /// Two regressions found by indexing Signal-Android: a typed Kotlin
    /// property was named after its *type* (`val db: SignalDatabase` produced
    /// a definition called `SignalDatabase`), and every function-local `val`
    /// became a top-level symbol, burying the real declarations.
    #[test]
    fn typed_properties_use_the_variable_name_and_locals_are_not_definitions() {
        let source = "class Repo {\n\
                      \x20   private val database: SignalDatabase = provide()\n\
                      \n\
                      \x20   fun export(): String {\n\
                      \x20       val snapshot: SignalDatabase = database.snapshot()\n\
                      \x20       return snapshot.name\n\
                      \x20   }\n\
                      }\n\
                      \n\
                      const val TAG: String = \"Repo\"\n";
        let file = extract_symbols(source, "Repo.kt", Some("kotlin"));
        assert_eq!(
            file.definitions
                .iter()
                .map(|def| (def.kind.as_str(), def.qualified_name.as_str()))
                .collect::<Vec<_>>(),
            vec![
                ("class", "Repo"),
                ("property", "Repo.database"),
                ("method", "Repo.export"),
                // `snapshot` is a local, not a symbol.
                ("property", "TAG"),
            ]
        );
        // The property's type is a reference, not a definition.
        assert!(
            file.references
                .iter()
                .any(|reference| reference.name == "SignalDatabase"
                    && reference.kind == RefKind::Type)
        );
    }

    /// Property/field reads (`this.x`, `foo.bar`) are `member` references and
    /// survive the default filter — Kotlin and Java code is full of them and
    /// "who reads this field" is a real question.
    #[test]
    fn member_reads_are_kept_by_default() {
        let typescript = extract("typescript");
        let member = typescript
            .references
            .iter()
            .find(|reference| reference.name == "x" && reference.line == 11)
            .expect("this.x read");
        assert_eq!(member.kind, RefKind::Member);
        assert_eq!(member.container, "Greeter.value");

        // The default set is exactly "everything but bare local reads".
        assert!(typescript
            .references
            .iter()
            .all(|reference| reference.kind != RefKind::Ident));
    }

    #[test]
    fn heritage_and_annotation_names_are_type_references() {
        let python = extract("python");
        let base = python
            .references
            .iter()
            .find(|reference| reference.name == "Base")
            .expect("Base reference");
        assert_eq!(base.kind, RefKind::Type);
        assert_eq!(base.container, "Greeter");

        let kotlin = extract("kotlin");
        assert_eq!(
            kotlin
                .references
                .iter()
                .find(|reference| reference.name == "HiltViewModel")
                .map(|reference| reference.kind),
            Some(RefKind::Type)
        );
    }

    #[test]
    fn imports_produce_edges_for_the_final_segment_only() {
        let java = extract("java");
        let imports: Vec<&str> = java
            .edges
            .iter()
            .filter(|edge| edge.relation == EdgeRelation::Imports)
            .map(|edge| edge.to_name.as_str())
            .collect();
        assert_eq!(imports, vec!["List"], "java.util.List collapses to List");

        // `package com.example;` is not an import of anything.
        assert!(!java
            .edges
            .iter()
            .any(|edge| edge.to_name == "com" || edge.to_name == "example"));

        let rust = extract("rust");
        assert_eq!(
            rust.edges
                .iter()
                .filter(|edge| edge.relation == EdgeRelation::Imports)
                .map(|edge| edge.to_name.as_str())
                .collect::<Vec<_>>(),
            vec!["Display"]
        );

        // tree-sitter-kotlin-ng emits `import`, not the `import_header` the
        // chunker's LanguageConfig lists; the extractor accepts both.
        let kotlin = extract("kotlin");
        assert_eq!(
            kotlin
                .edges
                .iter()
                .filter(|edge| edge.relation == EdgeRelation::Imports)
                .map(|edge| edge.to_name.as_str())
                .collect::<Vec<_>>(),
            vec!["launch"]
        );
    }

    #[test]
    fn plain_identifiers_are_off_by_default_and_change_nothing_structural() {
        let lean = extract("python");
        let verbose = extract_verbose("python");

        assert!(!lean
            .references
            .iter()
            .any(|reference| reference.kind == RefKind::Ident));
        assert!(verbose
            .references
            .iter()
            .any(|reference| reference.kind == RefKind::Ident));
        assert!(verbose.references.len() > lean.references.len());

        // Only the `ident` rows differ; definitions and edges are identical.
        assert_eq!(lean.definitions, verbose.definitions);
        assert_eq!(lean.edges, verbose.edges);
        assert_eq!(
            lean.references,
            verbose
                .references
                .into_iter()
                .filter(|reference| reference.kind != RefKind::Ident)
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn context_can_be_dropped_and_is_capped() {
        let options = ExtractOptions {
            include_context: false,
            ..ExtractOptions::default()
        };
        let file = extract_symbols_with(PYTHON, "src/sample.py", Some("python"), &options);
        assert!(file
            .references
            .iter()
            .all(|reference| reference.context.is_empty()));

        let capped = ExtractOptions {
            max_context_chars: 5,
            ..ExtractOptions::default()
        };
        let file = extract_symbols_with(PYTHON, "src/sample.py", Some("python"), &capped);
        assert!(file
            .references
            .iter()
            .all(|reference| reference.context.chars().count() <= 5));
    }

    // -----------------------------------------------------------------
    // shared chunker fixtures + degenerate input
    // -----------------------------------------------------------------

    #[test]
    fn shared_r3_chunker_fixtures_extract() {
        let cases: [(&str, &str, &str); 4] = [
            (
                "python",
                "src/sample.py",
                include_str!("../../../tests/rust-compat/r3/fixtures/sample.py"),
            ),
            (
                "rust",
                "src/sample.rs",
                include_str!("../../../tests/rust-compat/r3/fixtures/sample.rs"),
            ),
            (
                "typescript",
                "src/sample.ts",
                include_str!("../../../tests/rust-compat/r3/fixtures/sample.ts"),
            ),
            (
                "dart",
                "src/sample.dart",
                include_str!("../../../tests/rust-compat/r3/fixtures/sample.dart"),
            ),
        ];
        for (language, path, source) in cases {
            let file = extract_symbols(source, path, Some(language));
            // Every fixture declares `Greeter` with a `hello` member and a
            // top-level builder that calls it.
            assert!(
                file.definitions
                    .iter()
                    .any(|def| def.name == "Greeter" && def.parent_name.is_empty()),
                "{language}: no Greeter definition"
            );
            assert!(
                file.definitions
                    .iter()
                    .any(|def| def.name == "hello" && def.parent_name == "Greeter"),
                "{language}: no Greeter.hello"
            );
            assert!(
                file.edges.iter().any(|edge| {
                    edge.relation == EdgeRelation::Calls && edge.to_name == "hello"
                }),
                "{language}: no call to hello"
            );
        }
    }

    #[test]
    fn unknown_and_broken_input_is_inert() {
        let unknown = extract_symbols("whatever", "notes.txt", None);
        assert!(unknown.is_empty());
        assert_eq!(unknown.language, "unknown");

        // Unparseable source must not panic and must not invent definitions.
        let broken = extract_symbols("class {{{ ((", "src/broken.py", Some("python"));
        assert!(broken.definitions.is_empty());

        let empty = extract_symbols("", "src/empty.rs", Some("rust"));
        assert!(empty.is_empty());
    }

    #[test]
    fn extraction_is_deterministic() {
        for (language, path, source) in corpus() {
            let first = extract_symbols(source, path, Some(language));
            let second = extract_symbols(source, path, Some(language));
            assert_eq!(first, second, "{language} extraction is not stable");
        }
    }

    #[test]
    fn ast_graph_projection_answers_callers_and_callees() {
        let graph = extract("python").to_ast_graph();
        assert!(graph.nodes.contains_key("Greeter.hello"));
        assert_eq!(graph.callees("build_message"), vec!["Greeter", "hello"]);
        assert_eq!(graph.callers("helper"), vec!["Greeter.hello"]);
    }
}
