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

    async def start(self) -> bool:
        """Start the LSP server process."""
        if self._language not in LSP_SERVERS:
            return False

        server = LSP_SERVERS[self._language]
        binary = shutil.which(server["binary"])
        if not binary:
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
            )
            self._reader_task = asyncio.create_task(self._read_responses())

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
            self._process = None
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        logger.info("lsp_stopped", language=self._language)

    async def get_references(self, file_path: str, line: int, character: int) -> list[dict]:
        """Find all references to a symbol at the given position."""
        uri = f"file://{Path(self._repo_path) / file_path}"
        try:
            result = await self._send_request("textDocument/references", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": False},
            })
            return result or []
        except Exception:
            return []

    async def get_definition(self, file_path: str, line: int, character: int) -> list[dict]:
        """Go to definition of a symbol."""
        uri = f"file://{Path(self._repo_path) / file_path}"
        try:
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
        """Find implementations of an interface/trait."""
        uri = f"file://{Path(self._repo_path) / file_path}"
        try:
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

        except (asyncio.CancelledError, ConnectionError):
            pass
        except Exception as e:
            logger.debug("lsp_reader_error", error=str(e))


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
    servers_to_start = [s for s in available if s.found]

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

    for i, chunk in enumerate(chunks):
        lang = chunk.get("language", "")
        if lang not in clients:
            continue

        client = clients[lang]
        file_path = chunk.get("file_path", "")
        start_line = chunk.get("start_line", 0)
        name = chunk.get("name", "")

        if not file_path or not name:
            continue

        try:
            # Get references to this symbol (fan_in)
            refs = await client.get_references(file_path, start_line, 4)
            chunk["fan_in"] = len(refs)
            chunk["called_by"] = [
                f"{r.get('uri', '').replace('file://', '')}:{r.get('range', {}).get('start', {}).get('line', 0)}"
                for r in refs[:10]
            ]

            # If no references found, it might be dead code
            chunk_type = chunk.get("chunk_type", "")
            is_public = chunk.get("is_public", True)
            if len(refs) == 0 and is_public and chunk_type in ("function", "method"):
                chunk["dead_code_candidate"] = True

            enriched += 1

        except Exception as e:
            logger.debug("lsp_enrich_error", file=file_path, name=name, error=str(e))

        if on_progress and (i + 1) % 10 == 0:
            on_progress(lang, i + 1, total)

    # Shut down all LSP servers
    for client in clients.values():
        await client.stop()

    logger.info("lsp_enrichment_complete", enriched=enriched, total=total)
    return chunks
