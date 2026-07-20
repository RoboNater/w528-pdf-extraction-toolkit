"""Tests for shared VLM configuration resolution (pdfx.vlm_utils.make_client),
including the organization option added for OpenAI-hosted, org-scoped accounts.

No network: make_client builds an OpenAI client but does not call it, so these
tests inspect the constructed client. The end-to-end test that the organization
reaches the wire as a header lives in test_ocr.py against the fake endpoint.
"""

from __future__ import annotations

import pytest

from pdfx.vlm_utils import VlmError, make_client


@pytest.fixture()
def clean_env(monkeypatch):
    """Clear every env var make_client reads, including the OpenAI SDK's own
    organization vars, so resolution is deterministic."""
    for var in (
        "PDFX_VLM_MODEL",
        "PDFX_VLM_BASE_URL",
        "PDFX_VLM_ORG",
        "PDFX_VLM_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "OPENAI_ORGANIZATION",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # so key resolution passes


def test_organization_none_by_default(clean_env):
    client, _ = make_client("m", "http://x/v1")
    assert client.organization is None


def test_organization_from_argument(clean_env):
    client, _ = make_client("m", "http://x/v1", organization="org-arg")
    assert client.organization == "org-arg"


def test_organization_from_env(clean_env, monkeypatch):
    monkeypatch.setenv("PDFX_VLM_ORG", "org-env")
    client, _ = make_client("m", "http://x/v1")
    assert client.organization == "org-env"


def test_organization_argument_wins_over_env(clean_env, monkeypatch):
    monkeypatch.setenv("PDFX_VLM_ORG", "org-env")
    client, _ = make_client("m", "http://x/v1", organization="org-arg")
    assert client.organization == "org-arg"


def test_model_and_base_url_still_resolve_from_env(clean_env, monkeypatch):
    monkeypatch.setenv("PDFX_VLM_MODEL", "env-model")
    monkeypatch.setenv("PDFX_VLM_BASE_URL", "http://env/v1")
    client, model = make_client(None, None)
    assert model == "env-model"
    assert str(client.base_url).rstrip("/") == "http://env/v1"


def test_missing_model_raises(clean_env):
    with pytest.raises(VlmError, match="model"):
        make_client(None, None)


def test_feature_name_in_error(clean_env):
    with pytest.raises(VlmError, match="OCR needs a model"):
        make_client(None, None, feature="OCR")
