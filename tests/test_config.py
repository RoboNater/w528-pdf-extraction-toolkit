"""Tests for the optional TOML config file (pdfx.config) and its integration
with the CLI: discovery, the flag → env → config → default precedence matrix,
the `pdfx FILE` default action, and the guarantee that the API key is never
read from the config file.

The unit tests exercise pdfx.config directly (no subprocess). The integration
tests drive the installed `pdfx` entry point via subprocess with a controlled
working directory so config-file discovery is deterministic; they use the
`index` command and the `pypdf` text engine so no poppler binary is needed.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from pdfx import config
from pdfx.config import Config, ConfigError


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def restore_active():
    """Save/restore the process-wide active config around a test."""
    saved = config._active
    try:
        yield
    finally:
        config._active = saved


@pytest.fixture()
def clean_env(monkeypatch):
    for var in (
        "PDFX_VLM_MODEL",
        "PDFX_VLM_BASE_URL",
        "PDFX_VLM_ORG",
        "PDFX_CACHE_DIR",
        "PDFX_CONFIG",
    ):
        monkeypatch.delenv(var, raising=False)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def test_explicit_path_wins(tmp_path, clean_env):
    cfg = write(tmp_path / "custom.toml", '[default]\ncommand = "text"\n')
    loaded = config.load(cfg)
    assert loaded.source == cfg
    assert loaded.default_command() == "text"


def test_explicit_missing_path_errors(tmp_path, clean_env):
    with pytest.raises(ConfigError, match="not found"):
        config.load(tmp_path / "nope.toml")


def test_pdfx_config_env_var(tmp_path, clean_env, monkeypatch):
    cfg = write(tmp_path / "env.toml", '[text]\nengine = "pypdf"\n')
    monkeypatch.setenv("PDFX_CONFIG", str(cfg))
    assert config.load().lookup("text", "engine") == "pypdf"


def test_nearest_pdfx_toml_walking_up(tmp_path, clean_env, monkeypatch):
    write(tmp_path / "pdfx.toml", '[text]\nengine = "pypdf"\n')
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    # No user config in the picture.
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "no-user-config.toml")
    assert config.load().lookup("text", "engine") == "pypdf"


def test_no_config_anywhere_is_empty(tmp_path, clean_env, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "absent.toml")
    loaded = config.load()
    assert loaded.source is None
    assert loaded.default_command() is None
    assert loaded.lookup("text", "engine") is None


def test_project_overrides_user_per_key(tmp_path, clean_env, monkeypatch):
    user = write(tmp_path / "user.toml", '[text]\nengine = "pdfplumber"\nlayout = true\n')
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    write(project_dir / "pdfx.toml", '[text]\nengine = "pypdf"\n')
    monkeypatch.chdir(project_dir)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", user)
    loaded = config.load()
    # project wins for engine; user's layout survives (merged per key).
    assert loaded.lookup("text", "engine") == "pypdf"
    assert loaded.lookup("text", "layout") is True


def test_malformed_config_raises_configerror(tmp_path, clean_env):
    bad = write(tmp_path / "bad.toml", "[default\ncommand = 'text'\n")
    with pytest.raises(ConfigError, match="Invalid TOML"):
        config.load(bad)


# --------------------------------------------------------------------------- #
# lookup: command section vs shared [vlm]
# --------------------------------------------------------------------------- #
def test_vlm_key_falls_back_to_vlm_section():
    cfg = Config({"vlm": {"model": "shared"}})
    assert cfg.lookup("markdown", "model") == "shared"


def test_command_section_overrides_vlm_section():
    cfg = Config({"vlm": {"model": "shared"}, "markdown": {"model": "scoped"}})
    assert cfg.lookup("markdown", "model") == "scoped"
    assert cfg.lookup("validate-vlm-ocr", "model") == "shared"


def test_non_vlm_key_does_not_fall_back_to_vlm():
    cfg = Config({"vlm": {"engine": "pypdf"}})
    assert cfg.lookup("text", "engine") is None


# --------------------------------------------------------------------------- #
# resolve: full precedence matrix (flag > env > config > default)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def with_config(restore_active):
    def _set(data):
        config.set_active(Config(data))

    return _set


def test_flag_beats_everything(with_config, clean_env, monkeypatch):
    with_config({"markdown": {"model": "cfg"}})
    monkeypatch.setenv("PDFX_VLM_MODEL", "env")
    assert config.resolve("markdown", "model", "flag", None, env="PDFX_VLM_MODEL") == "flag"


def test_env_beats_config(with_config, clean_env, monkeypatch):
    with_config({"markdown": {"model": "cfg"}})
    monkeypatch.setenv("PDFX_VLM_MODEL", "env")
    assert config.resolve("markdown", "model", None, None, env="PDFX_VLM_MODEL") == "env"


def test_config_beats_default(with_config, clean_env):
    with_config({"markdown": {"model": "cfg"}})
    assert config.resolve("markdown", "model", None, "builtin", env="PDFX_VLM_MODEL") == "cfg"


def test_default_when_nothing_set(with_config, clean_env):
    with_config({})
    assert config.resolve("markdown", "model", None, "builtin", env="PDFX_VLM_MODEL") == "builtin"


def test_bool_tristate_config_turns_on(with_config, clean_env):
    with_config({"markdown": {"ai": True}})
    assert config.resolve("markdown", "ai", None, False) is True


def test_bool_negation_flag_beats_config(with_config, clean_env):
    with_config({"markdown": {"ai": True}})
    # --no-ai parses to False, which must override a config that enabled ai.
    assert config.resolve("markdown", "ai", False, False) is False


def test_int_option_from_config(with_config, clean_env):
    with_config({"markdown": {"dpi": 300}})
    assert config.resolve("markdown", "dpi", None, 150) == 300


def test_empty_env_var_is_ignored(with_config, clean_env, monkeypatch):
    with_config({"markdown": {"model": "cfg"}})
    monkeypatch.setenv("PDFX_VLM_MODEL", "")
    # An empty env var must not shadow the config value.
    assert config.resolve("markdown", "model", None, None, env="PDFX_VLM_MODEL") == "cfg"


# --------------------------------------------------------------------------- #
# Secrets: the API key is never sourced from the config file
# --------------------------------------------------------------------------- #
def test_api_key_not_read_from_config(tmp_path, clean_env, monkeypatch):
    """Even with an api_key in the file, VLM setup still demands the env key."""
    from pdfx.vlm_utils import VlmError, make_client

    write(tmp_path / "pdfx.toml", '[vlm]\napi_key = "sk-should-be-ignored"\nmodel = "m"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "USER_CONFIG_PATH", tmp_path / "absent.toml")
    config.set_active(config.load())
    monkeypatch.delenv("PDFX_VLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # No base_url and no env key → make_client must fail asking for the key,
    # proving the config's api_key was not picked up.
    with pytest.raises(VlmError, match="API key"):
        make_client("m", None)


# --------------------------------------------------------------------------- #
# Integration: the `pdfx FILE` default action + CLI precedence via subprocess
# --------------------------------------------------------------------------- #
def run_cli(*args, cwd=None, env=None):
    base = {
        k: v for k, v in __import__("os").environ.items() if not k.startswith(("PDFX_", "OPENAI_"))
    }
    if env:
        base.update(env)
    return subprocess.run(
        ["pdfx", *[str(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env=base,
    )


def test_default_action_without_config_runs_index(text_pdf, tmp_path):
    result = run_cli(text_pdf, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["page_count"] == 3  # index output


def test_default_action_uses_config_command(text_pdf, tmp_path):
    write(
        tmp_path / "pdfx.toml",
        '[default]\ncommand = "text"\n[text]\nengine = "pypdf"\npages = "2"\nplain = true\n',
    )
    result = run_cli(text_pdf, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Chapter Two" in result.stdout
    assert not result.stdout.lstrip().startswith(("[", "{"))  # plain, not JSON


def test_flag_overrides_config_command_option(text_pdf, tmp_path):
    write(
        tmp_path / "pdfx.toml",
        '[default]\ncommand = "text"\n[text]\nengine = "pypdf"\npages = "2"\nplain = true\n',
    )
    # --pages 1 on the command line overrides the config's pages = "2".
    result = run_cli(text_pdf, "--pages", "1", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Chapter One" in result.stdout


def test_explicit_subcommand_still_works_with_config(text_pdf, tmp_path):
    write(tmp_path / "pdfx.toml", '[default]\ncommand = "text"\n')
    result = run_cli("index", text_pdf, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["page_count"] == 3


def test_config_flag_points_at_explicit_file(text_pdf, tmp_path):
    cfg = write(tmp_path / "elsewhere.toml", '[default]\ncommand = "index"\n')
    # Run from a dir with no pdfx.toml; --config supplies the file.
    work = tmp_path / "work"
    work.mkdir()
    result = run_cli("--config", cfg, text_pdf, cwd=work)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["page_count"] == 3


def test_malformed_config_is_clean_cli_error(text_pdf, tmp_path):
    write(tmp_path / "pdfx.toml", "[default\ncommand = 'index'\n")
    result = run_cli("index", text_pdf, cwd=tmp_path)
    assert result.returncode == 1
    assert "Invalid TOML" in json.loads(result.stdout)["error"]
    assert "Traceback" not in result.stderr
