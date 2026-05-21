"""Integrations: Claude Code slash commands + OS service supervisor."""

from rag.integration.claude_code import generate_slash_command, install_claude_code_hook
from rag.integration.supervisor import (
    install_service,
    service_status,
    uninstall_service,
)

__all__ = [
    "generate_slash_command",
    "install_claude_code_hook",
    "install_service",
    "uninstall_service",
    "service_status",
]
