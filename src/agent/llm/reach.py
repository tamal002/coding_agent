"""Cheap reachability probe for the configured model's endpoint.

Before a run or the TUI opens, the interface layers probe the endpoint
the built model object says it uses. One short HTTP GET decides:
**any** HTTP response proves the server is there (a 401/404 is still a
reachable server — it would answer with an auth error at call time).
Only connection errors and timeouts count as "unreachable".

Provider-neutral: the probe only reads the model's ``base_url`` attribute
and never names a provider.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from langchain_core.language_models.chat_models import BaseChatModel

# Short on purpose: the check must fail fast, not hang the interface.
PROBE_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class ProbeResult:
    """What the reachability check found."""

    ok: bool
    detail: str  # used for status lines and error messages
    base_url: str  # the endpoint that was checked ("" if none)


def probe_model_connection(
    model: BaseChatModel,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = PROBE_TIMEOUT_S,
) -> ProbeResult:
    """GET the endpoint the model object reports; fail only on no connection."""
    url = str(getattr(model, "base_url", "") or "")
    if not url:
        # Model integrations that do not expose an endpoint (fake models in
        # tests) have nothing to probe; treat that as fine.
        return ProbeResult(ok=True, detail="nothing to probe", base_url="")
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(url)
    except httpx.RequestError as exc:
        return ProbeResult(
            ok=False,
            detail=(
                f"model endpoint {url} unreachable ({exc.__class__.__name__}). "
                "Start the model server, or check the saved base URL with "
                "'agent model list'."
            ),
            base_url=url,
        )
    return ProbeResult(
        ok=True,
        detail=f"{response.status_code} from {url}",
        base_url=url,
    )
