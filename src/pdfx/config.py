"""Optional TOML config file for pdfx CLI defaults.

Precedence for every option is **flag → env var → config file → built-in
default**: the config file sits below command-line flags and ``PDFX_*``
environment variables, but above pdfx's built-in defaults. This module lives in
the CLI layer only — ``core`` never imports it, so the library and the future
MCP server stay free of config-file concerns.

The file is TOML (stdlib :mod:`tomllib`, no new dependencies). It is discovered,
in order:

1. an explicit path from ``--config PATH`` or ``$PDFX_CONFIG``;
2. the nearest ``pdfx.toml`` walking up from the current directory (project);
3. ``~/.config/pdfx/config.toml`` (user).

When both a project and a user file are found they are merged per key with the
project file winning. Layout::

    [default]
    command = "markdown"          # what `pdfx FILE.pdf` runs; omit → "index"

    [markdown]                    # per-command defaults
    ai = true
    engine = "pypdf"

    [vlm]                         # shared VLM settings (model/base_url/...)
    base_url = "https://openrouter.ai/api/v1"
    organization = "org-abc123"
    # the API key is intentionally NOT read from the config file — env only.

A VLM key set in a command section (e.g. ``[markdown].model``) overrides the
same key in ``[vlm]`` for that command.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pdfx import core

CONFIG_FILENAME = "pdfx.toml"
USER_CONFIG_PATH = Path.home() / ".config" / "pdfx" / "config.toml"
CONFIG_ENV_VAR = "PDFX_CONFIG"

# VLM settings fall back from a command section to the shared [vlm] section.
# The API key is deliberately absent: secrets stay in the environment.
_VLM_KEYS = frozenset({"model", "base_url", "organization", "cache_dir"})

# The default action run by `pdfx FILE.pdf` when no [default].command is set.
# A cheap, local, network-free command — config must opt in to costly paths.
DEFAULT_COMMAND = "index"


class ConfigError(core.PdfxError):
    """The config file could not be read or parsed."""


class Config:
    """Parsed pdfx config with precedence-aware lookups.

    An empty ``Config`` (no file found) is valid and makes every lookup fall
    through to the built-in default, so callers never special-case "no config".
    """

    def __init__(self, data: dict[str, Any], source: Path | None = None) -> None:
        self._data = data
        self.source = source

    def section(self, name: str) -> dict[str, Any]:
        value = self._data.get(name)
        return value if isinstance(value, dict) else {}

    def lookup(self, command: str | None, key: str) -> Any | None:
        """Config value for ``key`` under ``command``, or in ``[vlm]`` for VLM
        keys, or ``None`` if unset."""
        if command is not None:
            section = self.section(command)
            if key in section:
                return section[key]
        if key in _VLM_KEYS:
            vlm = self.section("vlm")
            if key in vlm:
                return vlm[key]
        return None

    def default_command(self) -> str | None:
        command = self.section("default").get("command")
        return command if isinstance(command, str) else None


def _walk_up_for_project_config(start: Path) -> Path | None:
    """Nearest ``pdfx.toml`` at ``start`` or any ancestor, else ``None``."""
    for directory in (start, *start.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in config file {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge per section; ``override`` (project) wins per key."""
    merged: dict[str, Any] = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def load(explicit_path: str | Path | None = None) -> Config:
    """Discover, parse, and merge the config file(s).

    An explicit path (from ``--config`` or ``$PDFX_CONFIG``) must exist and be
    valid — a missing/malformed explicit file is an error. Auto-discovered files
    that are absent are simply skipped; a malformed discovered file still errors,
    so a typo surfaces rather than being silently ignored.
    """
    explicit = explicit_path if explicit_path is not None else os.environ.get(CONFIG_ENV_VAR)
    if explicit:
        path = Path(explicit).expanduser()
        return Config(_read_toml(path), source=path)

    user = _read_toml(USER_CONFIG_PATH) if USER_CONFIG_PATH.is_file() else {}
    project_path = _walk_up_for_project_config(Path.cwd())
    project = _read_toml(project_path) if project_path is not None else {}
    if not user and not project:
        return Config({}, source=None)
    return Config(_merge(user, project), source=project_path or USER_CONFIG_PATH)


# The active config for this process, loaded once by the CLI callback so every
# command resolves against the same file(s).
_active: Config | None = None


def set_active(config: Config) -> None:
    global _active
    _active = config


def active() -> Config:
    return _active if _active is not None else Config({}, source=None)


def resolve(
    command: str | None,
    key: str,
    flag_value: Any | None,
    default: Any,
    *,
    env: str | None = None,
) -> Any:
    """Resolve one option by precedence: flag → env → config → default.

    ``flag_value`` is the value parsed from the command line, or ``None`` when
    the flag was not given (booleans use paired ``--x/--no-x`` flags so an
    omitted flag is genuinely ``None``, not ``False``). ``env`` names the
    environment variable to consult, if any (only the VLM settings and the
    cache dir have one). Config values come from the active config's ``command``
    section, falling back to ``[vlm]`` for VLM keys.
    """
    if flag_value is not None:
        return flag_value
    if env is not None:
        env_value = os.environ.get(env)
        if env_value:
            return env_value
    config_value = active().lookup(command, key)
    if config_value is not None:
        return config_value
    return default
