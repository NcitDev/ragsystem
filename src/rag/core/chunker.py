"""Code-aware 3-tier chunking using tree-sitter.

Tier 1: File summary — package declarations + top-level signatures
Tier 2: Class summary — class signature + field/method signatures
Tier 3: Function detail — full function body with context header
"""

from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import structlog
import tree_sitter as ts

from rag.config import get_settings

logger = structlog.get_logger()


class ChunkType(str, Enum):
    FILE_SUMMARY = "file_summary"
    CLASS_DECLARATION = "class_declaration"
    INTERFACE_DECLARATION = "interface_declaration"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"
    DOC_SECTION = "doc_section"


@dataclass
class Chunk:
    """A single chunk from a source file or document."""

    content: str
    chunk_type: ChunkType
    file_path: str
    language: str
    name: str = ""
    parent_name: str = ""
    start_line: int = 0
    end_line: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        raw = f"{self.file_path}:{self.start_line}:{self.end_line}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]

    def enrich_metadata(self, test_files: set[str] | None = None) -> None:
        """Enrich chunk metadata with pattern detection and quality signals."""
        if self.language == "python" and self.content:
            from rag.core.patterns import detect_patterns_from_source

            rich_meta = detect_patterns_from_source(
                self.content, self.name, test_files=test_files
            )
            self.metadata.update(rich_meta)
        elif self.language in ("kotlin", "java") and self.content:
            enriched = _detect_kotlin_java_coroutines(self.content, self.language)
            if "inherits_from" in enriched and "inherits_from" in self.metadata:
                enriched["inherits_from"] = list(set(self.metadata["inherits_from"] + enriched["inherits_from"]))
            self.metadata.update(enriched)

    def to_index_metadata(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "language": self.language,
            "chunk_type": self.chunk_type.value,
            "name": self.name,
            "parent_name": self.parent_name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content_hash": self.content_hash,
            **self.metadata,
        }


_KOTLIN_COROUTINE_BUILDERS = (
    "launch", "async", "withContext", "runBlocking",
    "coroutineScope", "supervisorScope", "flow {", ".collect",
    "delay(", "awaitAll", "asFlow", "channelFlow", "callbackFlow",
)

_JAVA_ASYNC_BUILDERS = (
    "CompletableFuture", "ExecutorService", "Executors.",
    "submit(", "supplyAsync", "runAsync", "thenApply", "thenCompose",
)


def _strip_line_comments(text: str) -> str:
    """Remove // line comments and /* */ block comments cheaply (no full parse).
    Avoids false positives where keyword appears only in commentary."""
    out_lines = []
    in_block = False
    for line in text.splitlines():
        if in_block:
            end = line.find("*/")
            if end >= 0:
                line = line[end + 2 :]
                in_block = False
            else:
                continue
        # strip block-comment starts on the same line
        while "/*" in line:
            start = line.find("/*")
            end = line.find("*/", start + 2)
            if end >= 0:
                line = line[:start] + line[end + 2 :]
            else:
                line = line[:start]
                in_block = True
                break
        # strip // comments
        slash = line.find("//")
        if slash >= 0:
            line = line[:slash]
        out_lines.append(line)
    return "\n".join(out_lines)


def _detect_kotlin_java_coroutines(content: str, language: str) -> dict[str, Any]:
    """Cheap text-level detection of suspend/coroutine/singleton/etc. usage.
    Returns string-typed flags suitable for Qdrant KEYWORD payload index."""
    import re
    meta: dict[str, Any] = {}
    cleaned = _strip_line_comments(content)
    head = cleaned[:300]  # signature/declaration window

    # DI Dependency Extraction
    if "@Provides" in cleaned:
        meta["is_di_provider"] = "true"
        # Kotlin: fun someName(...) : ReturnType
        provides_kt = re.findall(r"@Provides[\s\S]*?fun\s+\w+\s*\([^)]*\)\s*:\s*([A-Z]\w+)", cleaned)
        # Java: public ReturnType someName(...)
        provides_java = re.findall(r"@Provides[\s\S]*?(?:public|protected|private)?\s+([A-Z]\w+)\s+\w+\s*\(", cleaned)
        provides = list(set(provides_kt + provides_java))
        if provides:
            meta["provides"] = provides
            
    if "@Inject" in cleaned:
        meta["is_di_consumer"] = "true"
        # Kotlin property: @Inject lateinit var someService: ServiceType
        injects_kt = re.findall(r"@Inject\s+(?:lateinit\s+)?var\s+\w+\s*:\s*([A-Z]\w+)", cleaned)
        # Constructor inject: @Inject constructor(val service: ServiceType)
        injects_ctor = re.findall(r"@Inject\s+constructor\s*\((.*?)\)", cleaned, re.DOTALL)
        deps = list(injects_kt)
        for ctor_args in injects_ctor:
            types = re.findall(r":\s*([A-Z]\w+)", ctor_args)
            deps.extend(types)
        if deps:
            meta["injects"] = list(set(deps))

    if language == "kotlin":
        if "suspend fun " in head or head.lstrip().startswith("suspend "):
            meta["is_suspend"] = "true"
        if any(b in cleaned for b in _KOTLIN_COROUTINE_BUILDERS):
            meta["uses_coroutines"] = "true"
        if "Flow<" in cleaned or ": Flow<" in cleaned:
            meta["uses_flow"] = "true"
        # Singletons: @Singleton (Dagger/Hilt/javax.inject) OR `object` declaration.
        if "@Singleton" in cleaned or "javax.inject.Singleton" in cleaned:
            meta["is_singleton"] = "true"
        # Kotlin `object Foo` is a singleton by definition.
        # Skip `companion object` here — those aren't standalone singletons.
        for line in cleaned.splitlines()[:5]:
            stripped = line.lstrip()
            if stripped.startswith("object ") and not stripped.startswith("object {"):
                meta["is_singleton"] = "true"
                meta["is_kotlin_object"] = "true"
                break
        # Sealed class (common ADT signal)
        if "sealed class " in head or "sealed interface " in head:
            meta["is_sealed"] = "true"
        # Data class
        if "data class " in head:
            meta["is_data_class"] = "true"
        # Interface decl
        if head.lstrip().startswith("interface ") or "\ninterface " in head:
            meta["is_interface"] = "true"
        # Abstract class
        if "abstract class " in head:
            meta["is_abstract"] = "true"
        # Composable function (Jetpack Compose)
        if "@Composable" in cleaned:
            meta["is_composable"] = "true"
        # Hilt/Dagger module
        if "@Module" in cleaned or "@HiltViewModel" in cleaned or "@AndroidEntryPoint" in cleaned:
            meta["is_di_component"] = "true"
        # Inheritance: class Foo : Bar, Baz(...) — extract superclass + interfaces
        inherits = _extract_kotlin_inherits_from(head)
        if inherits:
            meta["inherits_from"] = inherits

    elif language == "java":
        if any(b in cleaned for b in _JAVA_ASYNC_BUILDERS):
            meta["uses_async_java"] = "true"
        if "@Singleton" in cleaned or "javax.inject.Singleton" in cleaned:
            meta["is_singleton"] = "true"
        # Classic singleton pattern: getInstance() + private ctor
        if "getInstance(" in cleaned and "private " in cleaned and "static " in cleaned:
            meta["is_singleton_pattern"] = "true"
        # Enum singleton (Effective Java item)
        if head.lstrip().startswith("public enum ") or "\npublic enum " in head or "\nenum " in head:
            meta["is_enum"] = "true"
        if "interface " in head and ("public interface" in head or head.lstrip().startswith("interface ")):
            meta["is_interface"] = "true"
        if "abstract class " in head:
            meta["is_abstract"] = "true"
        # JUnit test class signal
        if "@Test" in cleaned or "extends TestCase" in cleaned:
            meta["has_unit_test"] = "true"
        # Inheritance: class Foo extends Bar implements Baz
        inherits = _extract_java_inherits_from(head)
        if inherits:
            meta["inherits_from"] = inherits

    return meta


def _extract_kotlin_inherits_from(head: str) -> list[str]:
    """Extract superclass and interface names from the first line of a Kotlin
    class/interface declaration.  Handles:
      class Foo : Bar(args), Baz
      class Foo : SomeInterface
      interface Foo : Bar
    Returns a deduplicated list of simple type names (no generics, no args).
    """
    import re
    # Match everything after the first colon on the declaration line, before
    # the opening brace or end-of-line.
    m = re.search(r"(?:^|\n)[^\n]*?(?:class|interface|object)\s+\w[\w<>]*?\s*(?:\([^)]*\))?\s*:\s*([^{\n]+)", head)
    if not m:
        return []
    raw = m.group(1)
    # Strip generic params and constructor args, then split on commas.
    names: list[str] = []
    for part in raw.split(","):
        name = re.sub(r"<[^>]*>", "", part)  # strip generics
        name = re.sub(r"\([^)]*\)", "", name)  # strip ctor args
        name = name.strip()
        if name and re.match(r"[A-Z]\w*", name):
            names.append(name)
    return list(dict.fromkeys(names))  # deduplicated, order-preserving


def _extract_java_inherits_from(head: str) -> list[str]:
    """Extract superclass and interface names from a Java class declaration.
    Handles:
      class Foo extends Bar implements Baz, Qux
      interface Foo extends Bar, Baz
    Returns a deduplicated list of simple type names.
    """
    import re
    names: list[str] = []
    extends_m = re.search(r"\bextends\s+([A-Z]\w*(?:<[^>]*>)?)", head)
    if extends_m:
        name = re.sub(r"<[^>]*>", "", extends_m.group(1)).strip()
        if name:
            names.append(name)
    implements_m = re.search(r"\bimplements\s+([A-Z][\w,\s<>]*?)(?:\{|$)", head)
    if implements_m:
        for part in implements_m.group(1).split(","):
            name = re.sub(r"<[^>]*>", "", part).strip()
            if name and re.match(r"[A-Z]\w*", name):
                names.append(name)
    return list(dict.fromkeys(names))


LANGUAGE_CONFIG: dict[str, dict[str, Any]] = {
    "python": {
        "grammar_module": "tree_sitter_python",
        "class_types": ["class_definition"],
        "function_types": ["function_definition"],
        "name_field": "name",
        "body_field": "body",
        "import_types": ["import_statement", "import_from_statement"],
        "decorator_type": "decorator",
        "docstring_type": "expression_statement",
        "extensions": [".py"],
    },
    "java": {
        "grammar_module": "tree_sitter_java",
        "class_types": ["class_declaration", "interface_declaration", "enum_declaration"],
        "function_types": ["method_declaration", "constructor_declaration"],
        "name_field": "name",
        "body_field": "body",
        "import_types": ["import_declaration"],
        "extensions": [".java"],
    },
    "kotlin": {
        "grammar_module": "tree_sitter_kotlin",
        "class_types": ["class_declaration", "object_declaration", "interface_declaration"],
        "function_types": ["function_declaration"],
        "name_field": "simple_identifier",
        "body_field": "function_body",
        "import_types": ["import_header"],
        "extensions": [".kt", ".kts"],
    },
    "typescript": {
        "grammar_module": "tree_sitter_typescript",
        "class_types": ["class_declaration", "interface_declaration"],
        "function_types": ["function_declaration", "method_definition", "arrow_function"],
        "name_field": "name",
        "body_field": "body",
        "import_types": ["import_statement"],
        "extensions": [".ts", ".tsx"],
        "sub_language": "typescript",
    },
    "javascript": {
        "grammar_module": "tree_sitter_javascript",
        "class_types": ["class_declaration"],
        "function_types": ["function_declaration", "method_definition", "arrow_function"],
        "name_field": "name",
        "body_field": "body",
        "import_types": ["import_statement"],
        "extensions": [".js", ".jsx", ".mjs"],
    },
    "go": {
        "grammar_module": "tree_sitter_go",
        "class_types": ["type_declaration"],
        "function_types": ["function_declaration", "method_declaration"],
        "name_field": "name",
        "body_field": "body",
        "import_types": ["import_declaration"],
        "extensions": [".go"],
    },
    "rust": {
        "grammar_module": "tree_sitter_rust",
        "class_types": ["struct_item", "enum_item", "impl_item", "trait_item"],
        "function_types": ["function_item"],
        "name_field": "name",
        "body_field": "body",
        "import_types": ["use_declaration"],
        "extensions": [".rs"],
    },
    "c": {
        "grammar_module": "tree_sitter_c",
        "class_types": ["struct_specifier", "enum_specifier", "union_specifier"],
        "function_types": ["function_definition"],
        "name_field": "declarator",
        "body_field": "body",
        "import_types": ["preproc_include"],
        "extensions": [".c", ".h"],
    },
    "cpp": {
        "grammar_module": "tree_sitter_cpp",
        "class_types": ["class_specifier", "struct_specifier", "enum_specifier"],
        "function_types": ["function_definition"],
        "name_field": "declarator",
        "body_field": "body",
        "import_types": ["preproc_include"],
        "extensions": [".cpp", ".cc", ".cxx", ".hpp", ".hh"],
    },
    "dart": {
        # Loaded via tree_sitter_language_pack (no standalone PyPI package).
        "grammar_loader": "language_pack",
        "grammar_lang": "dart",
        "class_types": [
            "class_definition",
            "mixin_declaration",
            "extension_declaration",
            "enum_declaration",
        ],
        # Dart's grammar emits separate signature + function_body siblings.
        # We treat the *_signature nodes as the function units; body content
        # is appended via _dart_attach_body during extraction.
        "function_types": [
            "method_signature",
            "function_signature",
            "getter_signature",
            "setter_signature",
            "constructor_signature",
        ],
        "name_field": "name",
        "body_field": "function_body",
        "import_types": ["import_or_export", "library_name", "part_directive"],
        "extensions": [".dart"],
    },
}

# Reverse mapping: extension -> language
EXTENSION_TO_LANG: dict[str, str] = {}
for _lang, _config in LANGUAGE_CONFIG.items():
    for _ext in _config["extensions"]:
        EXTENSION_TO_LANG[_ext] = _lang


def detect_language(file_path: str) -> str | None:
    ext = Path(file_path).suffix.lower()
    return EXTENSION_TO_LANG.get(ext)


def _get_parser(language: str) -> ts.Parser:
    config = LANGUAGE_CONFIG[language]

    # Languages without a standalone tree-sitter-* PyPI wheel use the
    # community-maintained tree_sitter_language_pack.
    loader = config.get("grammar_loader")
    if loader == "language_pack":
        from tree_sitter_language_pack import get_language as _pack_get_language
        lang = _pack_get_language(config["grammar_lang"])
        return ts.Parser(lang)

    module_name = config["grammar_module"]
    grammar_module = importlib.import_module(module_name)

    # Handle typescript sub-language
    sub = config.get("sub_language")
    if sub:
        lang = ts.Language(grammar_module.language_typescript())
    else:
        lang = ts.Language(grammar_module.language())

    parser = ts.Parser(lang)
    return parser


def _get_node_name(node: ts.Node, config: dict[str, Any]) -> str:
    name_field = config.get("name_field", "name")

    if hasattr(node, "child_by_field_name"):
        name_node = node.child_by_field_name(name_field)
        if name_node:
            return name_node.text.decode("utf-8") if name_node.text else ""

    # For Kotlin simple_identifier
    if name_field == "simple_identifier":
        for child in node.children:
            if child.type == "simple_identifier":
                return child.text.decode("utf-8") if child.text else ""

    # For C/C++ declarator (may be nested)
    if name_field == "declarator":
        name_node = node.child_by_field_name("declarator")
        if name_node:
            # May be a function_declarator wrapping an identifier
            ident = name_node.child_by_field_name("declarator") or name_node
            return ident.text.decode("utf-8").split("(")[0] if ident.text else ""

    # Dart: method_signature wraps function_signature/getter_signature/etc.
    # whose own `name` field holds the identifier. Mixin declarations have a
    # positional `identifier` child (no field name).
    if node.type == "method_signature":
        for child in node.children:
            inner = child.child_by_field_name("name") if hasattr(child, "child_by_field_name") else None
            if inner and inner.text:
                return inner.text.decode("utf-8")
    if node.type == "mixin_declaration":
        for child in node.children:
            if child.type == "identifier" and child.text:
                return child.text.decode("utf-8")

    return ""


def _build_context_header(file_path: str, language: str, parent_name: str = "") -> str:
    parts = [f"// File: {file_path}"]
    if parent_name:
        parts.append(f"// Class: {parent_name}")
    parts.append(f"// Language: {language}")
    return "\n".join(parts)


def chunk_code(source: str, file_path: str, language: str | None = None) -> list[Chunk]:
    """Chunk source code using tree-sitter 3-tier strategy."""
    if language is None:
        language = detect_language(file_path)
    if language is None or language not in LANGUAGE_CONFIG:
        return _chunk_sliding_window(source, file_path, language or "unknown")

    settings = get_settings()
    max_chars = settings.index.max_chunk_chars
    config = LANGUAGE_CONFIG[language]
    chunks: list[Chunk] = []

    try:
        parser = _get_parser(language)
        tree = parser.parse(source.encode("utf-8"))
        root = tree.root_node
    except Exception as e:
        logger.warning("parse_failed", file=file_path, language=language, error=str(e))
        return _chunk_sliding_window(source, file_path, language)

    # Tier 1: File summary
    file_summary_parts: list[str] = []
    import_types = config.get("import_types", [])

    for child in root.children:
        if child.type in import_types:
            text = child.text.decode("utf-8") if child.text else ""
            file_summary_parts.append(text)
        elif child.type in config["class_types"]:
            first_line = (child.text.decode("utf-8") if child.text else "").split("\n")[0]
            file_summary_parts.append(first_line)
        elif child.type in config["function_types"]:
            first_line = (child.text.decode("utf-8") if child.text else "").split("\n")[0]
            file_summary_parts.append(first_line)

    if file_summary_parts:
        summary_content = "\n".join(file_summary_parts)[:max_chars]
        chunks.append(Chunk(
            content=summary_content,
            chunk_type=ChunkType.FILE_SUMMARY,
            file_path=file_path,
            language=language,
            name=Path(file_path).name,
            start_line=1,
            end_line=root.end_point[0] + 1,
        ))

    # Tier 2 & 3
    for child in root.children:
        if child.type in config["class_types"]:
            class_name = _get_node_name(child, config)
            _extract_class_chunks(child, config, file_path, language, class_name, max_chars, chunks)
        elif child.type in config["function_types"]:
            _extract_function_chunk(child, config, file_path, language, "", max_chars, chunks)

    if not chunks:
        return _chunk_sliding_window(source, file_path, language)

    _enrich_chunks_with_fqn(chunks, source)
    return chunks


def _collect_class_members(node: ts.Node, config: dict[str, Any]) -> list[ts.Node]:
    members: list[ts.Node] = []
    for child in node.children:
        if child.type in config["function_types"]:
            members.append(child)
        elif child.type in ("block", "class_body", "body", "declaration_list"):
            for grandchild in child.children:
                if grandchild.type in config["function_types"]:
                    members.append(grandchild)
    return members


def _extract_class_chunks(
    node: ts.Node,
    config: dict[str, Any],
    file_path: str,
    language: str,
    class_name: str,
    max_chars: int,
    chunks: list[Chunk],
) -> None:
    class_text = node.text.decode("utf-8") if node.text else ""
    members = _collect_class_members(node, config)

    summary_lines: list[str] = []
    for member in members:
        member_text = member.text.decode("utf-8") if member.text else ""
        summary_lines.append(member_text.split("\n")[0])

    chunk_type = (
        ChunkType.INTERFACE_DECLARATION if "interface" in node.type
        else ChunkType.CLASS_DECLARATION
    )

    first_line = class_text.split("\n")[0]
    summary_content = first_line + "\n" + "\n".join(summary_lines)
    chunks.append(Chunk(
        content=summary_content[:max_chars],
        chunk_type=chunk_type,
        file_path=file_path,
        language=language,
        name=class_name,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
    ))

    for member in members:
        _extract_function_chunk(member, config, file_path, language, class_name, max_chars, chunks)


def _extract_function_chunk(
    node: ts.Node,
    config: dict[str, Any],
    file_path: str,
    language: str,
    parent_name: str,
    max_chars: int,
    chunks: list[Chunk],
) -> None:
    func_name = _get_node_name(node, config)
    func_text = node.text.decode("utf-8") if node.text else ""

    # Dart's grammar emits signature and function_body as separate siblings.
    # Splice the immediate following function_body so the chunk holds the
    # full implementation, not just the prototype.
    end_line = node.end_point[0] + 1
    if language == "dart" and node.next_sibling and node.next_sibling.type == "function_body":
        body_node = node.next_sibling
        body_text = body_node.text.decode("utf-8") if body_node.text else ""
        if body_text:
            func_text = f"{func_text} {body_text}"
            end_line = body_node.end_point[0] + 1

    if not func_text.strip():
        return

    context = _build_context_header(file_path, language, parent_name)
    content = f"{context}\n\n{func_text}"

    chunk_type = ChunkType.METHOD if parent_name else ChunkType.FUNCTION

    chunks.append(Chunk(
        content=content[:max_chars],
        chunk_type=chunk_type,
        file_path=file_path,
        language=language,
        name=func_name,
        parent_name=parent_name,
        start_line=node.start_point[0] + 1,
        end_line=end_line,
    ))


def chunk_document(content: str, file_path: str, doc_type: str = "markdown") -> list[Chunk]:
    """Chunk a document (markdown, text) by sections."""
    settings = get_settings()
    max_chars = settings.index.max_chunk_chars

    if doc_type == "markdown":
        return _chunk_markdown(content, file_path, max_chars)
    return _chunk_sliding_window(content, file_path, "text")


def _chunk_markdown(content: str, file_path: str, max_chars: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    current_section = ""
    current_name = Path(file_path).stem
    current_start = 1

    for i, line in enumerate(content.split("\n"), 1):
        if line.startswith("#") and current_section.strip():
            chunks.append(Chunk(
                content=current_section[:max_chars],
                chunk_type=ChunkType.DOC_SECTION,
                file_path=file_path,
                language="markdown",
                name=current_name,
                start_line=current_start,
                end_line=i - 1,
                metadata={"doc_type": "markdown"},
            ))
            current_section = line + "\n"
            current_name = line.lstrip("#").strip()
            current_start = i
        else:
            current_section += line + "\n"

    if current_section.strip():
        chunks.append(Chunk(
            content=current_section[:max_chars],
            chunk_type=ChunkType.DOC_SECTION,
            file_path=file_path,
            language="markdown",
            name=current_name,
            start_line=current_start,
            end_line=current_start + current_section.count("\n"),
            metadata={"doc_type": "markdown"},
        ))

    return chunks


def _chunk_sliding_window(
    content: str, file_path: str, language: str,
    window_lines: int = 60, overlap_lines: int = 10,
) -> list[Chunk]:
    settings = get_settings()
    max_chars = settings.index.max_chunk_chars
    lines = content.split("\n")
    chunks: list[Chunk] = []

    i = 0
    while i < len(lines):
        window = lines[i : i + window_lines]
        chunk_text = "\n".join(window)[:max_chars]
        if chunk_text.strip():
            chunks.append(Chunk(
                content=chunk_text,
                chunk_type=ChunkType.FILE_SUMMARY,
                file_path=file_path,
                language=language,
                name=Path(file_path).name,
                start_line=i + 1,
                end_line=min(i + window_lines, len(lines)),
            ))
        i += window_lines - overlap_lines

    return chunks


def _enrich_chunks_with_fqn(chunks: list[Chunk], source: str) -> None:
    import re
    # Determine package
    package_match = re.search(r"\bpackage\s+([a-zA-Z0-9_\.]+)", source)
    package_name = package_match.group(1) if package_match else ""

    # Determine imports
    imports = re.findall(r"\bimport\s+(?:static\s+)?([a-zA-Z0-9_\.\*]+)", source)

    for chunk in chunks:
        if chunk.language not in ("java", "kotlin"):
            continue

        # If it's a class or interface declaration, compute defines_fqn
        if chunk.chunk_type in (ChunkType.CLASS_DECLARATION, ChunkType.INTERFACE_DECLARATION) and chunk.name:
            defines_fqn = f"{package_name}.{chunk.name}" if package_name else chunk.name
            chunk.metadata["defines_fqn"] = defines_fqn

            # Extract raw inherits_from statically and resolve to FQNs
            raw_inherits = []
            cleaned = _strip_line_comments(chunk.content)
            head = cleaned[:300]
            if chunk.language == "kotlin":
                raw_inherits = _extract_kotlin_inherits_from(head)
            elif chunk.language == "java":
                raw_inherits = _extract_java_inherits_from(head)

            if raw_inherits:
                resolved_inherits = list(raw_inherits)
                for parent in raw_inherits:
                    matched_import = False
                    for imp in imports:
                        if imp.endswith(f".{parent}"):
                            resolved_inherits.append(imp)
                            matched_import = True
                            break
                    if not matched_import:
                        for imp in imports:
                            if imp.endswith(".*"):
                                resolved_inherits.append(imp[:-1] + parent)
                        if package_name:
                            resolved_inherits.append(f"{package_name}.{parent}")
                chunk.metadata["inherits_from"] = list(set(resolved_inherits))

        # Scan for referenced classes in this chunk
        words = set(re.findall(r"\b([A-Z][a-zA-Z0-9_]+)\b", chunk.content))
        referenced_fqns = []
        for word in words:
            if word == chunk.name:
                continue
            # Check explicit import
            matched_import = False
            for imp in imports:
                if imp.endswith(f".{word}"):
                    referenced_fqns.append(imp)
                    matched_import = True
                    break
            if not matched_import:
                # Check wildcard imports
                for imp in imports:
                    if imp.endswith(".*"):
                        referenced_fqns.append(imp[:-1] + word)
                # Fallback to same package
                if package_name:
                    referenced_fqns.append(f"{package_name}.{word}")

        if referenced_fqns:
            chunk.metadata["references_fqn"] = list(set(referenced_fqns))


def supported_languages() -> list[str]:
    return list(LANGUAGE_CONFIG.keys())


def supported_extensions() -> list[str]:
    return list(EXTENSION_TO_LANG.keys())
