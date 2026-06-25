# Setting up serena on Ubuntu (for the benchmark)

serena is an LSP-backed symbol search tool. `benchmark_all_tools.py` /
`benchmark_real_fixes.py` drive it via a **warm HTTP server** (`tools/serena_server.py`,
port 7899) so its slow LSP boot happens once.

**Hard prerequisite:** the project must be **Gradle-built first** (see
build-signal-ubuntu.md). Without `app/build/` + a resolved classpath, the language
servers never finish indexing — we saw kotlin-language-server run >29 min and
jdtls >25 min without ever resolving a symbol on an unbuilt Signal checkout.

## 1. Install serena into the rag venv

```bash
cd ~/development/ragsystem
.venv/bin/pip install "git+https://github.com/oraios/serena.git"
.venv/bin/python -c "from serena.agent import SerenaAgent; print('serena OK')"
```
(github is IPv4-reachable, so this install works on the box.)

## 2. Copy the warm-server helper

```bash
scp tools/serena_server.py nikita@192.168.3.49:~/development/serena_server.py
# CLI: --project <path>  --port 7899 (default)
```

## 3. Configure timeouts and language

- **Increase the LS timeout** (default 240 s is too short for a big project) in
  `~/.serena/serena_config.yml`:
  ```yaml
  tool_timeout: 1800
  ```
- **Pick the language** in `<project>/.serena/project.yml` (auto-detect picks the
  majority language). Signal is mostly Kotlin, so it defaults to:
  ```yaml
  languages:
  - kotlin
  ```
  - `kotlin` → uses kotlin-language-server (slowest; needs a fully built project).
  - `java` → uses eclipse **jdtls** (more robust). To benchmark Java symbols,
    set `languages: [java]`. To cover both, list both (boot is slower).
  > On Signal, **both** only work once the Gradle build has populated the classpath.

## 4. Boot the warm server

```bash
cd ~/development/ragsystem
nohup .venv/bin/python ~/development/serena_server.py \
  --project ~/development/Signal-Android > /tmp/serena_server.log 2>&1 &
```

## 5. Confirm it actually resolves (don't trust /health alone)

`/health` returns `{"ready":true}` shallowly — it can lie while the LS is still
indexing. Test a **real** lookup:
```bash
# pick a symbol that matches the configured language:
curl -s -m120 -XPOST http://127.0.0.1:7899/find_symbol -d '{"name":"ContactRepository"}'   # java
curl -s -m120 -XPOST http://127.0.0.1:7899/find_symbol -d '{"name":"Recipient"}'           # kotlin
```
- A JSON result with `.java`/`.kt` paths → serena is ready; run the benchmark.
- `"language server manager is not initialized ... timed out"` → the LS failed to
  index (almost always because the project isn't built — go back to the Gradle build).

## 6. Run the benchmark with serena

```bash
cd ~/development
RAG_BENCH_ROOT=~/development/Signal-Android \
  python3 benchmark_real_fixes.py "serena"            # serena only
# or include it in the full set:
RAG_BENCH_ROOT=~/development/Signal-Android \
  python3 benchmark_real_fixes.py "vanilla-rg,ast-index,graphify,serena,rag-agentic,rag-agentic-pool"
```

## Teardown
```bash
curl -s -XPOST http://127.0.0.1:7899/shutdown    # graceful (frees LSP servers)
pkill -9 -f serena_server.py ; pkill -9 -f KotlinLanguageServer ; pkill -9 -f "org.eclipse.jdt.ls"
```

## Known-good vs known-bad
- ✅ Works on the Mac: Signal there is fully Android-Studio-synced (`.idea`, `build/`
  119 MB) → LSP indexes in ~4 min.
- ❌ Failed on the box: Signal there was only cloned + RAG-indexed (`app/build` missing)
  → LSP can't resolve the classpath. Build first.
