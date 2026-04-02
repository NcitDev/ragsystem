"""Tests for tree-sitter code chunking."""

from rag.core.chunker import (
    Chunk,
    ChunkType,
    chunk_code,
    chunk_document,
    detect_language,
    supported_languages,
    supported_extensions,
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
