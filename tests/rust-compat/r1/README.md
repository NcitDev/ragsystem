# Phase R1 Rust Compatibility Fixtures

`python-rag-home` is a copied fixture shaped like Python-created `~/.rag`.
`repos.sql` and `rag.sql` deterministically materialize the SQLite databases
with the Python table names and columns that R1 is allowed to read. Tests build
the databases and copy the text fixtures into temporary directories before
opening them, so a clean clone is reproducible and Rust never mutates this
source fixture or a real user `~/.rag`.
