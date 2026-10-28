"""Probe tests: any HTTP response is reachable; only connection errors fail."""

from __future__ import annotations

import httpx
from langchain_core.language_models.chat_models import BaseChatModel

from agent.llm.reach import probe_model_connection
from tests.fakes import ScriptedChatModel


class UrlModel(BaseChatModel):
    """Minimal model shape to give the probe a base_url attribute."""

    base_url: str = ""

    @property
    def _llm_type(self) -> str:
        return "url-model"

    def _generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("the probe must not generate anything")


def _fake_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_reachable_on_any_http_status() -> None:
    for status in (200, 401, 404, 500):
        model = UrlModel(base_url="http://endpoint.test/")

        def handler(request: httpx.Request, status: int = status) -> httpx.Response:
            return httpx.Response(status)

        result = probe_model_connection(model, transport=_fake_transport(handler))
        assert result.ok is True, f"status {status} should count as reachable"
        assert result.base_url == "http://endpoint.test/"


def test_unreachable_when_connection_refused() -> None:
    model = UrlModel(base_url="http://closed.test/")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = probe_model_connection(model, transport=_fake_transport(handler))
    assert result.ok is False
    assert "agent model list" in result.detail  # actionable fix named


def test_timeout_counts_as_unreachable() -> None:
    model = UrlModel(base_url="http://slow.test/")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no answer in time", request=request)

    result = probe_model_connection(model, transport=_fake_transport(handler))
    assert result.ok is False


def test_model_without_endpoint_is_a_clean_skip() -> None:
    """Fake models (tests) with no base_url are probed trivially."""
    result = probe_model_connection(ScriptedChatModel(responses=[]))
    assert result.ok is True
    assert result.base_url == ""
