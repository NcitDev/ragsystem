# Linux deployment (systemd)

`rag service install` is macOS-only (launchd). On Linux, supervise the daemon
with systemd. The daemon already writes rotated structured logs to
`~/.rag/logs/daemon.jsonl` (10 MB × 5 backups, ~50 MB cap), so no `logrotate`
config is required for those — only the systemd journal captures stdout/stderr.

## User-level unit (recommended)

Save as `~/.config/systemd/user/rag-daemon.service`:

```ini
[Unit]
Description=RAG code-search daemon
After=network.target

[Service]
Type=simple
# Adjust to your install path.
ExecStart=%h/.local/bin/rag start
Restart=always
RestartSec=3
# Ollama / git must be on PATH for indexing + LLM planning.
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
# Optional: forward Ollama host if not the default 127.0.0.1:11434.
# Environment=OLLAMA_HOST=127.0.0.1:11434
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now rag-daemon.service
systemctl --user status rag-daemon.service
journalctl --user -u rag-daemon.service -f   # follow logs
```

To survive logout (run without an active session):

```bash
sudo loginctl enable-linger "$USER"
```

## Notes

- The daemon binds `127.0.0.1:7890` by default — keep it that way. Do **not**
  set `host = "0.0.0.0"` in `~/.rag/config.toml` (the config rejects it; expose
  via a reverse proxy with TLS + the bearer token instead).
- Bearer token lives at `~/.rag/token` (mode 0600). Back it up on an encrypted
  volume.
- `Restart=always` mirrors launchd `KeepAlive=true`.
