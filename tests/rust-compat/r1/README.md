# Phase R1 Rust Compatibility Fixtures

`python-rag-home` is a copied fixture shaped like Python-created `~/.rag`.
The SQLite files in this directory use the Python table names and columns that
R1 is allowed to read. Tests copy the fixture into temporary directories before
opening it, so Rust never reads or writes a real user `~/.rag`.
