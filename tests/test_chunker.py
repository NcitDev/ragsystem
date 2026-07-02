"""Tests for tree-sitter code chunking."""

from rag.core.chunker import (
    Chunk,
    ChunkType,
    chunk_code,
    chunk_document,
    detect_language,
    supported_languages,
)


def test_detect_language():
    assert detect_language("main.py") == "python"
    assert detect_language("App.tsx") == "typescript"
    assert detect_language("main.go") == "go"
    assert detect_language("lib.rs") == "rust"
    assert detect_language("main.c") == "c"
    assert detect_language("file.cpp") == "cpp"
    assert detect_language("file.txt") is None


def test_supported_languages():
    langs = supported_languages()
    assert "python" in langs
    assert "go" in langs
    assert "rust" in langs
    assert "c" in langs
    assert "cpp" in langs
    assert len(langs) >= 9


def test_chunk_python_function():
    source = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"
'''
    chunks = chunk_code(source, "test.py", "python")
    assert len(chunks) >= 1
    func_chunks = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
    assert len(func_chunks) == 1
    assert func_chunks[0].name == "hello"


def test_chunk_python_class():
    source = '''
class MyClass:
    def method_a(self):
        pass

    def method_b(self):
        pass
'''
    chunks = chunk_code(source, "test.py", "python")
    class_chunks = [c for c in chunks if c.chunk_type == ChunkType.CLASS_DECLARATION]
    method_chunks = [c for c in chunks if c.chunk_type == ChunkType.METHOD]
    assert len(class_chunks) == 1
    assert class_chunks[0].name == "MyClass"
    assert len(method_chunks) == 2


def test_chunk_file_summary():
    source = '''
import os
from pathlib import Path

def foo():
    pass

class Bar:
    pass
'''
    chunks = chunk_code(source, "test.py", "python")
    summaries = [c for c in chunks if c.chunk_type == ChunkType.FILE_SUMMARY]
    assert len(summaries) == 1


def test_chunk_go():
    source = '''
package main

import "fmt"

func main() {
    fmt.Println("hello")
}
'''
    chunks = chunk_code(source, "main.go", "go")
    assert len(chunks) >= 1
    func_chunks = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
    assert len(func_chunks) == 1


def test_chunk_dart_class():
    source = '''
class Counter {
  int _value = 0;
  int get value => _value;
  void increment() {
    _value++;
  }
}
'''
    chunks = chunk_code(source, "lib/counter.dart", "dart")
    assert len(chunks) >= 1
    types = {c.chunk_type for c in chunks}
    assert ChunkType.CLASS_DECLARATION in types or ChunkType.METHOD in types
    names = {c.name for c in chunks if c.name}
    assert "Counter" in names or "increment" in names


def test_chunk_dart_top_level_function():
    source = "void main() { print('hi'); }\n"
    chunks = chunk_code(source, "main.dart", "dart")
    func_chunks = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
    assert len(func_chunks) >= 1
    assert any(c.name == "main" for c in func_chunks)


def test_chunk_unknown_language_fallback():
    source = "line1\nline2\nline3\n"
    chunks = chunk_code(source, "file.xyz")
    assert len(chunks) >= 1  # Falls back to sliding window


def test_chunk_markdown():
    source = """# Title
Some intro text.

## Section 1
Content of section 1.

## Section 2
Content of section 2.
"""
    chunks = chunk_document(source, "doc.md", "markdown")
    assert len(chunks) >= 2
    assert all(c.chunk_type == ChunkType.DOC_SECTION for c in chunks)


def test_chunk_id_deterministic():
    c1 = Chunk(content="test", chunk_type=ChunkType.FUNCTION, file_path="a.py", language="python", start_line=1, end_line=5)
    c2 = Chunk(content="test", chunk_type=ChunkType.FUNCTION, file_path="a.py", language="python", start_line=1, end_line=5)
    assert c1.chunk_id == c2.chunk_id


def test_content_hash():
    c = Chunk(content="hello", chunk_type=ChunkType.FUNCTION, file_path="a.py", language="python")
    assert len(c.content_hash) == 16


def test_to_index_metadata_is_a_chunk_method():
    """Regression: to_index_metadata was once mis-indented after a `return` in
    enrich_metadata's module function, so it was never attached to Chunk and
    every call site (indexer.py) raised AttributeError — indexing was broken."""
    assert "to_index_metadata" in Chunk.__dict__, "to_index_metadata must be a Chunk method"

    c = Chunk(
        content="def f(): pass",
        chunk_type=ChunkType.FUNCTION,
        file_path="pkg/mod.py",
        language="python",
        name="f",
        parent_name="C",
        start_line=10,
        end_line=12,
        metadata={"complexity": 1, "is_test": "false"},
    )
    meta = c.to_index_metadata()

    assert meta["file_path"] == "pkg/mod.py"
    assert meta["language"] == "python"
    assert meta["chunk_type"] == "function"  # enum .value, not the enum
    assert meta["name"] == "f"
    assert meta["parent_name"] == "C"
    assert meta["start_line"] == 10
    assert meta["end_line"] == 12
    assert meta["content_hash"] == c.content_hash
    # extra metadata is spread in
    assert meta["complexity"] == 1
    assert meta["is_test"] == "false"


def test_enrich_chunks_with_fqn_java():
    from rag.core.chunker import chunk_code, ChunkType
    source = """package org.test;
import org.external.OtherClass;
import org.another.*;

class MyClass extends BaseClass {
    void doSomething() {
        OtherClass other = new OtherClass();
        WildcardClass wc = new WildcardClass();
    }
}
"""
    chunks = chunk_code(source, "MyClass.java", "java")
    for c in chunks:
        c.enrich_metadata()
    
    # 1. Verify class chunk
    class_chunks = [c for c in chunks if c.chunk_type == ChunkType.CLASS_DECLARATION]
    assert len(class_chunks) == 1
    c_class = class_chunks[0]
    meta_class = c_class.to_index_metadata()
    assert meta_class.get("defines_fqn") == "org.test.MyClass"
    assert "org.test.BaseClass" in meta_class.get("inherits_from", [])

    # 2. Verify method chunk
    method_chunks = [c for c in chunks if c.chunk_type == ChunkType.METHOD]
    assert len(method_chunks) == 1
    c_method = method_chunks[0]
    meta_method = c_method.to_index_metadata()
    assert "org.external.OtherClass" in meta_method.get("references_fqn", [])
    assert "org.another.WildcardClass" in meta_method.get("references_fqn", [])



def test_decorated_definitions_produce_chunks():
    from rag.core.chunker import chunk_code
    source = """import functools

@functools.lru_cache
def cached_fn(x):
    return x * 2

class Service:
    @property
    def value(self):
        return self._v
"""
    chunks = chunk_code(source, "svc.py", "python")
    names = {c.name for c in chunks}
    assert "cached_fn" in names
    assert "value" in names
    cached = next(c for c in chunks if c.name == "cached_fn")
    # span includes the decorator line
    assert cached.start_line == 3
    assert "@functools.lru_cache" in cached.content


def test_python_enrichment_populates_metadata():
    from rag.core.chunker import chunk_code
    source = """class Runner:
    async def run(self, a, b):
        for i in range(a):
            if i > b:
                return i
"""
    chunks = chunk_code(source, "runner.py", "python")
    run = next(c for c in chunks if c.name == "run")
    run.enrich_metadata()
    assert run.metadata["is_async"] is True
    assert run.metadata["complexity_cyclomatic"] >= 3
    assert run.metadata["parameter_count"] == 3
    assert run.metadata["nesting_depth"] >= 2


def test_typescript_export_statements_produce_chunks():
    from rag.core.chunker import chunk_code
    source = """export function exportedFn(a: number): number {
  return a + 1;
}

export class ExportedClass {
  method(): void {}
}
"""
    chunks = chunk_code(source, "mod.ts", "typescript")
    names = {c.name for c in chunks}
    assert "exportedFn" in names
    assert "ExportedClass" in names


def test_chunk_id_unique_across_chunk_types():
    from rag.core.chunker import chunk_code
    # class spans the whole file: file_summary and class share start/end lines
    source = "class Only:\n    def m(self):\n        return 1"
    chunks = chunk_code(source, "only.py", "python")
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_context_header_uses_python_comment_syntax():
    from rag.core.chunker import chunk_code
    source = "def f():\n    return 1\n"
    chunks = chunk_code(source, "f.py", "python")
    fn = next(c for c in chunks if c.name == "f")
    assert fn.content.startswith("# File: f.py")
    assert "//" not in fn.content


def test_kotlin_and_go_names_resolve():
    from rag.core.chunker import chunk_code
    kt = chunk_code("@Singleton\nclass Service {\n    fun run() = 1\n}\n", "A.kt", "kotlin")
    assert {c.name for c in kt} >= {"Service", "run"}
    go = chunk_code("package main\n\ntype Svc struct{}\n", "a.go", "go")
    assert any(c.name == "Svc" for c in go)
