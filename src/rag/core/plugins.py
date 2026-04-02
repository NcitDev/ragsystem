"""Plugin system for custom pattern detectors and chunking strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml

from rag.config import RAG_HOME

logger = structlog.get_logger()

DEFAULT_PLUGIN_DIR = RAG_HOME / "plugins"


@dataclass
class Plugin:
    name: str
    version: str
    patterns: dict[str, list[str]] = field(default_factory=dict)
    chunk_config: dict[str, Any] = field(default_factory=dict)
    domain_keywords: dict[str, list[str]] = field(default_factory=dict)


def discover_plugins(plugin_dir: Path | None = None) -> list[Plugin]:
    """Scan plugin_dir (default ~/.rag/plugins/) for YAML manifests.

    Each plugin is a directory with a plugin.yaml file:
        name: my-plugin
        version: "1.0"
        patterns:
          my_pattern: [keyword1, keyword2]
        chunk_config:
          my_language:
            max_chars: 5000
        domains:
          my_domain: [term1, term2]
    """
    plugin_dir = plugin_dir or DEFAULT_PLUGIN_DIR
    plugins: list[Plugin] = []

    if not plugin_dir.is_dir():
        logger.debug("plugin_dir_not_found", path=str(plugin_dir))
        return plugins

    for entry in sorted(plugin_dir.iterdir()):
        manifest = None
        if entry.is_dir():
            manifest = entry / "plugin.yaml"
            if not manifest.exists():
                manifest = entry / "plugin.yml"
        elif entry.is_file() and entry.suffix in (".yaml", ".yml"):
            manifest = entry
        else:
            continue

        if manifest is None or not manifest.exists():
            continue

        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning("invalid_plugin_manifest", path=str(manifest))
                continue

            plugin = Plugin(
                name=data.get("name", entry.stem),
                version=str(data.get("version", "0.0")),
                patterns=data.get("patterns", {}),
                chunk_config=data.get("chunk_config", {}),
                domain_keywords=data.get("domains", {}),
            )
            plugins.append(plugin)
            logger.info("plugin_discovered", name=plugin.name, version=plugin.version)
        except yaml.YAMLError as exc:
            logger.warning("plugin_yaml_error", path=str(manifest), error=str(exc))
        except Exception as exc:
            logger.warning("plugin_load_error", path=str(manifest), error=str(exc))

    return plugins


def apply_plugins(plugins: list[Plugin]) -> None:
    """Merge plugin patterns/domains into the global detection dicts."""
    from rag.core.patterns import DOMAIN_KEYWORDS, NAME_PATTERNS

    for plugin in plugins:
        for pattern_name, keywords in plugin.patterns.items():
            if pattern_name in NAME_PATTERNS:
                existing = set(NAME_PATTERNS[pattern_name])
                NAME_PATTERNS[pattern_name].extend(
                    kw for kw in keywords if kw not in existing
                )
            else:
                NAME_PATTERNS[pattern_name] = list(keywords)
            logger.debug(
                "plugin_patterns_applied",
                plugin=plugin.name,
                pattern=pattern_name,
                keywords=keywords,
            )

        for domain_name, keywords in plugin.domain_keywords.items():
            if domain_name in DOMAIN_KEYWORDS:
                existing = set(DOMAIN_KEYWORDS[domain_name])
                DOMAIN_KEYWORDS[domain_name].extend(
                    kw for kw in keywords if kw not in existing
                )
            else:
                DOMAIN_KEYWORDS[domain_name] = list(keywords)
            logger.debug(
                "plugin_domains_applied",
                plugin=plugin.name,
                domain=domain_name,
                keywords=keywords,
            )

    if plugins:
        logger.info("plugins_applied", count=len(plugins))
