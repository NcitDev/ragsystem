"""Warm Serena server — boots the LSP agent ONCE and stays alive.

Serena's language servers take ~4 minutes to boot. Re-booting them on every
benchmark run is the slowest part of the suite. This tiny stdlib HTTP server
boots SerenaAgent once and serves symbol lookups, so benchmark_all_tools.py
(and anything else) can reuse a warm instance.

Start it (it takes ~4 min to come up, then stays warm):
    python tools/serena_server.py --project /path/to/Signal-Android &

Query it:
    curl -s localhost:7899/health
    curl -s -XPOST localhost:7899/find_symbol -d '{"name":"Recipient"}'

Stop it later:
    curl -s -XPOST localhost:7899/shutdown      # graceful (frees LSP servers)
    # or just kill the process.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_AGENT = None
_FIND_SYMBOL = None
_FIND_USAGES = None
_READY = threading.Event()


def _boot(project: str) -> None:
    global _AGENT, _FIND_SYMBOL, _FIND_USAGES
    print(f"[serena-server] booting SerenaAgent for {project} (~4 min)...", flush=True)
    from serena.agent import SerenaAgent

    _AGENT = SerenaAgent(project=project)
    _AGENT.execute_task(lambda: None, name="WaitForLspInit")
    _FIND_SYMBOL = _AGENT.get_tool_by_name("find_symbol")
    _FIND_USAGES = _AGENT.get_tool_by_name("find_referencing_symbols")
    _READY.set()
    print("[serena-server] READY — language servers warm.", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):  # quiet
        pass

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"ready": _READY.is_set()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "bad json"})
            return

        if self.path == "/shutdown":
            self._send(200, {"ok": True})
            if _AGENT is not None:
                try:
                    _AGENT.on_shutdown()
                except Exception:
                    pass
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        if not _READY.is_set():
            self._send(503, {"error": "still booting"})
            return

        try:
            if self.path == "/find_symbol":
                res = _FIND_SYMBOL.apply(
                    name_path_pattern=req["name"],
                    include_body=bool(req.get("include_body", False)),
                )
                self._send(200, {"result": res})
            elif self.path == "/find_usages":
                res = _FIND_USAGES.apply(
                    name_path=req["name_path"], relative_path=req["relative_path"],
                )
                self._send(200, {"result": res})
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001 — surface tool errors to the client
            self._send(500, {"error": str(e)})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--port", type=int, default=7899)
    args = ap.parse_args()

    threading.Thread(target=_boot, args=(args.project,), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[serena-server] listening on http://127.0.0.1:{args.port} "
          f"(/health, /find_symbol, /find_usages, /shutdown)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
