"""LSP integration for index-time enrichment.

Detects installed LSP servers and enriches chunks with type resolution,
call graphs, and cross-file references. Servers are started at index time
and killed after enrichment completes.

Protocol: JSON-RPC over stdio using the Language Server Protocol.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from rag.config import get_settings

logger = structlog.get_logger()

# Known LSP servers per language
LSP_SERVERS: dict[str, dict[str, str]] = {
    "python": {
        "binary": "pyright-langserver",
        "name": "pyright",
        "install": "npm install -g pyright",
        "args": "--stdio",
    },
    "typescript": {
        "binary": "typescript-language-server",
        "name": "tsserver",
        "install": "npm install -g typescript-language-server typescript",
        "args": "--stdio",
    },
    "go": {
        "binary": "gopls",
        "name": "gopls",
        "install": "go install golang.org/x/tools/gopls@latest",
        "args": "serve",
    },
    "rust": {
        "binary": "rust-analyzer",
        "name": "rust-analyzer",
        "install": "rustup component add rust-analyzer",
        "args": "",
    },
    "java": {
        "binary": "jdtls",
        "name": "jdtls",
        "install": "brew install jdtls",
        "args": "",
    },
    "c": {
        "binary": "clangd",
        "name": "clangd",
        "install": "brew install llvm",
        "args": "--background-index",
    },
    "cpp": {
        "binary": "clangd",
        "name": "clangd",
        "install": "brew install llvm",
        "args": "--background-index",
    },
    "dart": {
        # Invoked as: `dart language-server --protocol=lsp`
        "binary": "dart",
        "name": "dart language-server",
        "install": "Install Dart SDK: https://dart.dev/get-dart",
        "args": "language-server --protocol=lsp",
    },
    "kotlin": {
        "binary": "kotlin-language-server",
        "name": "kotlin-language-server",
        "install": "brew install kotlin-language-server",
        "args": "",
    },
}


@dataclass
class LSPServerStatus:
    language: str
    name: str
    found: bool
    install_hint: str


@dataclass
class LSPEnrichment:
    """LSP-derived metadata for a chunk."""

    resolved_types: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    implements: str = ""
    fan_in: int = 0
    fan_out: int = 0
    dead_code_candidate: bool = False


def detect_lsp_servers(languages: list[str] | None = None) -> list[LSPServerStatus]:
    """Check which LSP servers are installed on PATH."""
    results: list[LSPServerStatus] = []
    check_langs = languages or list(LSP_SERVERS.keys())

    for lang in check_langs:
        if lang not in LSP_SERVERS:
            continue
        server = LSP_SERVERS[lang]
        found = shutil.which(server["binary"]) is not None
        results.append(LSPServerStatus(
            language=lang,
            name=server["name"],
            found=found,
            install_hint=server["install"],
        ))

    return results


class LSPClient:
    """Minimal LSP client over stdio for index-time enrichment."""

    def __init__(self, language: str, repo_path: str):
        self._language = language
        self._repo_path = repo_path
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._opened_files: set[str] = set()

    def _build_env(self) -> dict[str, str]:
        """Server env with a Homebrew JDK on PATH if present (jdtls/kotlin need it).
        Copies rather than mutating the daemon's own environment."""
        import os
        env = dict(os.environ)
        for openjdk_path in (
            "/opt/homebrew/opt/openjdk@21",
            "/usr/local/opt/openjdk@21",
            "/opt/homebrew/opt/openjdk",
            "/usr/local/opt/openjdk",
        ):
            openjdk_bin = f"{openjdk_path}/bin"
            if os.path.exists(openjdk_bin):
                paths = env.get("PATH", "").split(os.pathsep)
                if openjdk_bin not in paths:
                    env["PATH"] = os.pathsep.join([openjdk_bin, *paths])
                env["JAVA_HOME"] = openjdk_path
                break
        return env

    async def start(self) -> bool:
        """Start the LSP server process."""
        if self._language not in LSP_SERVERS:
            return False

        server = LSP_SERVERS[self._language]
        binary = shutil.which(server["binary"])
        if not binary:
            logger.info(
                "lsp_server_missing",
                language=self._language,
                install_hint=server.get("install", ""),
            )
            return False

        cmd = [binary]
        if server["args"]:
            cmd.extend(server["args"].split())

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._repo_path,
                env=self._build_env(),
            )
            self._reader_task = asyncio.create_task(self._read_responses())
            self._stderr_task = asyncio.create_task(self._drain_stderr())

            # Initialize
            await self._send_request("initialize", {
                "processId": None,
                "rootUri": f"file://{self._repo_path}",
                "capabilities": {
                    "textDocument": {
                        "definition": {"dynamicRegistration": False},
                        "references": {"dynamicRegistration": False},
                        "typeDefinition": {"dynamicRegistration": False},
                        "implementation": {"dynamicRegistration": False},
                    },
                },
            })
            await self._send_notification("initialized", {})
            logger.info("lsp_started", language=self._language, binary=binary)
            return True

        except Exception as e:
            logger.warning("lsp_start_failed", language=self._language, error=str(e))
            return False

    async def stop(self) -> None:
        """Shut down the LSP server."""
        if self._process:
            try:
                await self._send_request("shutdown", None)
                await self._send_notification("exit", None)
            except Exception:
                pass
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except Exception:
                self._process.kill()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5)
                except Exception:
                    logger.warning("lsp_kill_wait_failed", language=self._language)
            self._process = None
        for task_attr in ("_reader_task", "_stderr_task"):
            task = getattr(self, task_attr)
            if task:
                task.cancel()
                setattr(self, task_attr, None)
        self._opened_files.clear()
        logger.info("lsp_stopped", language=self._language)

    async def ensure_open(self, file_path: str) -> None:
        """Send textDocument/didOpen for a file (once). Several servers only
        answer position queries for documents that were explicitly opened."""
        if file_path in self._opened_files:
            return
        self._opened_files.add(file_path)
        full_path = Path(self._repo_path) / file_path
        try:
            text = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        await self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": f"file://{full_path}",
                "languageId": self._language,
                "version": 1,
                "text": text,
            },
        })

    async def get_references(self, file_path: str, line: int, character: int) -> list[dict]:
        """Find all references to a symbol at the given position (0-based)."""
        uri = f"file://{Path(self._repo_path) / file_path}"
        try:
            await self.ensure_open(file_path)
            result = await self._send_request("textDocument/references", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": False},
            })
            return result or []
        except Exception:
            return []

    async def get_definition(self, file_path: str, line: int, character: int) -> list[dict]:
        """Go to definition of a symbol (0-based position)."""
        uri = f"file://{Path(self._repo_path) / file_path}"
        try:
            await self.ensure_open(file_path)
            result = await self._send_request("textDocument/definition", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            })
            if isinstance(result, dict):
                return [result]
            return result or []
        except Exception:
            return []

    async def get_implementations(self, file_path: str, line: int, character: int) -> list[dict]:
        """Find implementations of an interface/trait (0-based position)."""
        uri = f"file://{Path(self._repo_path) / file_path}"
        try:
            await self.ensure_open(file_path)
            result = await self._send_request("textDocument/implementation", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            })
            if isinstance(result, dict):
                return [result]
            return result or []
        except Exception:
            return []

    async def _send_request(self, method: str, params: Any) -> Any:
        """Send a JSON-RPC request and wait for response."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("LSP server not running")

        self._request_id += 1
        req_id = self._request_id
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        content = json.dumps(msg)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        self._process.stdin.write((header + content).encode())
        await self._process.stdin.drain()

        try:
            result = await asyncio.wait_for(future, timeout=10)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            return None

    async def _send_notification(self, method: str, params: Any) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return

        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        content = json.dumps(msg)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        self._process.stdin.write((header + content).encode())
        await self._process.stdin.drain()

    async def _read_responses(self) -> None:
        """Read JSON-RPC responses from LSP server stdout."""
        if not self._process or not self._process.stdout:
            return

        try:
            while True:
                # Read headers
                headers = {}
                while True:
                    line = await self._process.stdout.readline()
                    if not line:
                        return
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        break
                    if ":" in line_str:
                        key, value = line_str.split(":", 1)
                        headers[key.strip()] = value.strip()

                content_length = int(headers.get("Content-Length", 0))
                if content_length == 0:
                    continue

                body = await self._process.stdout.readexactly(content_length)
                msg = json.loads(body.decode("utf-8"))

                # Handle response
                if "id" in msg and msg["id"] in self._pending:
                    future = self._pending.pop(msg["id"])
                    if not future.done():
                        if "error" in msg:
                            future.set_result(None)
                        else:
                            future.set_result(msg.get("result"))
                elif "id" in msg and "method" in msg:
                    # Server-initiated request (workspace/configuration,
                    # client/registerCapability, ...). Reply with an empty
                    # result so the server doesn't stall waiting on us.
                    await self._send_response(msg["id"], None)

        except (asyncio.CancelledError, ConnectionError):
            pass
        except Exception as e:
            logger.debug("lsp_reader_error", error=str(e))

    async def _send_response(self, req_id: Any, result: Any) -> None:
        """Answer a server-initiated JSON-RPC request."""
        if not self._process or not self._process.stdin:
            return
        msg = {"jsonrpc": "2.0", "id": req_id, "result": result}
        content = json.dumps(msg)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        self._process.stdin.write((header + content).encode())
        await self._process.stdin.drain()

    async def _drain_stderr(self) -> None:
        """Discard server stderr so a chatty server can't fill the pipe and
        deadlock the process."""
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    return
        except (asyncio.CancelledError, ConnectionError):
            pass


_ENRICHABLE_CHUNK_TYPES = (
    "class_declaration", "interface_declaration", "method", "function", "class", "interface",
)


async def _enrich_one_chunk(client: LSPClient, chunk: dict, lsp_timeout: float) -> bool:
    """Query references for one chunk and record fan-in metadata.
    Returns True when the chunk was enriched."""
    file_path = chunk.get("file_path", "")
    name = chunk.get("name", "")
    if not file_path or not name:
        return False

    # Prefer the exact 0-based name position recorded by the chunker; fall back
    # to the declaration line (start_line is 1-based, LSP wants 0-based).
    line = chunk.get("name_line")
    character = chunk.get("name_col")
    if line is None:
        line = max(0, int(chunk.get("start_line", 1)) - 1)
        character = 4
    try:
        refs = await asyncio.wait_for(
            client.get_references(file_path, int(line), int(character or 0)),
            timeout=lsp_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("lsp_enrich_timeout", file=file_path, name=name)
        return False
    except Exception as e:
        logger.debug("lsp_enrich_error", file=file_path, name=name, error=str(e))
        return False

    chunk["fan_in"] = len(refs)
    chunk["called_by"] = [
        f"{r.get('uri', '').replace('file://', '')}:{r.get('range', {}).get('start', {}).get('line', 0)}"
        for r in refs[:10]
    ]

    # Only flag dead-code candidates from a *precise* position: the legacy
    # line-guess produced empty reference lists for live symbols.
    is_public = chunk.get("is_public", True)
    if (
        len(refs) == 0
        and is_public
        and chunk.get("name_line") is not None
        and chunk.get("chunk_type", "") in ("function", "method")
    ):
        chunk["dead_code_candidate"] = True
    return True


async def enrich_chunks_with_lsp(
    repo_path: str,
    chunks: list[dict],
    languages: list[str],
    on_progress: Any = None,
) -> list[dict]:
    """Enrich chunks with LSP data at index time.

    Starts LSP servers for detected languages, queries for references
    and definitions, then kills the servers.

    Args:
        repo_path: Path to the repository
        chunks: List of chunk metadata dicts (mutated in place)
        languages: Languages present in the repo
        on_progress: Optional callback(language, current, total)

    Returns:
        The enriched chunks
    """
    available = detect_lsp_servers(languages)
    servers_to_start = available

    if not servers_to_start:
        logger.info("lsp_enrichment_skipped", reason="no LSP servers available")
        return chunks

    clients: dict[str, LSPClient] = {}
    for server in servers_to_start:
        client = LSPClient(server.language, repo_path)
        if await client.start():
            clients[server.language] = client

    if not clients:
        logger.info("lsp_enrichment_skipped", reason="no LSP servers started successfully")
        return chunks

    # Give servers time to index
    await asyncio.sleep(2)

    enriched = 0
    total = len(chunks)

    lsp_timeout = get_settings().lsp.timeout / 1000  # ms → seconds
    for i, chunk in enumerate(chunks):
        lang = chunk.get("language", "")
        if lang not in clients:
            continue
        # Only query LSP references for structural symbol declarations
        if chunk.get("chunk_type", "") not in _ENRICHABLE_CHUNK_TYPES:
            continue

        if await _enrich_one_chunk(clients[lang], chunk, lsp_timeout):
            enriched += 1

        if on_progress and (i + 1) % 10 == 0:
            on_progress(lang, i + 1, total)

    # Shut down all LSP servers
    for client in clients.values():
        await client.stop()

    logger.info("lsp_enrichment_complete", enriched=enriched, total=total)
    return chunks


async def enrich_chunks_with_running_clients(
    chunks: list[dict],
    clients: dict[str, LSPClient],
) -> list[dict]:
    """Enrich chunks using pre-started persistent LSP clients."""
    lsp_timeout = get_settings().lsp.timeout / 1000
    for chunk in chunks:
        lang = chunk.get("language", "")
        if lang not in clients:
            continue
        if chunk.get("chunk_type", "") not in _ENRICHABLE_CHUNK_TYPES:
            continue
        await _enrich_one_chunk(clients[lang], chunk, lsp_timeout)

    return chunks

