"""Gemini on Vertex AI (google-genai in Vertex mode) — the fix writer.

The client is built explicitly with ``genai.Client(vertexai=True, project=...,
location=...)``. Verified working today: ``gemini-3-flash-preview`` on location
``global``; ``gemini-2.5-pro`` on ``us-central1`` is the fallback.

Cost: the optional env vars ``GEMINI_PRICE_IN_PER_1M`` and
``GEMINI_PRICE_OUT_PER_1M`` (USD per 1M tokens, floats) turn measured token
counts into ``cost_usd``. When either is unset, cost is ``None`` and the UI
omits it — a number is only published when it is actually computed from
configured prices and measured tokens.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

PRICE_IN_ENV = "GEMINI_PRICE_IN_PER_1M"
PRICE_OUT_ENV = "GEMINI_PRICE_OUT_PER_1M"


def _price(env_name: str) -> Optional[float]:
    raw = os.environ.get(env_name, "").strip().replace("$", "")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def compute_cost(tokens_in: int, tokens_out: int) -> Optional[float]:
    """USD cost from measured tokens, or None when prices are not configured."""
    pin = _price(PRICE_IN_ENV)
    pout = _price(PRICE_OUT_ENV)
    if pin is None or pout is None:
        return None
    return round((tokens_in * pin + tokens_out * pout) / 1_000_000, 6)


# ------------------------------------------------------------------ schema

class FixFile(BaseModel):
    path: str
    new_content: str


class PrBodySection(BaseModel):
    heading: str
    body_markdown: str


class FixProposal(BaseModel):
    files: list[FixFile] = Field(default_factory=list)
    rationale: str = ""  # 2-3 sentences, quoted verbatim in the incident view
    pr_title: str = ""
    pr_body_sections: list[PrBodySection] = Field(default_factory=list)


@dataclass
class FixResult:
    proposal: FixProposal
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: Optional[float]
    seconds: float


class VertexGeminiError(RuntimeError):
    pass


_FIX_SYSTEM = (
    "You are Darn's fix writer. You receive an evidence dossier (a Davis problem, "
    "verbatim DQL receipts and results, a trace excerpt, a timing ruler, and the "
    "suspect commit hunk) plus the CURRENT content of the implicated files. "
    "Write the SMALLEST correct fix.\n"
    "Rules:\n"
    "- Only change what the evidence implicates. Keep the diff minimal.\n"
    "- files[].new_content must be the COMPLETE new file content, not a fragment.\n"
    "- rationale: 2-3 plain sentences explaining why this fixes the failure, "
    "grounded in the receipts. No hedging, no marketing.\n"
    "- pr_title: imperative, <= 70 chars, prefixed 'Mend: '.\n"
    "- pr_body_sections: ordered sections for the PR dossier body. Do NOT repeat "
    "the receipts; they are appended separately.\n"
    "Return ONLY the JSON object."
)


class VertexGemini:
    """Async wrapper. ``on_call(name, seconds, ok=..., tokens_in=, tokens_out=)``
    is the medic hook; it fires with measured wall time and token usage."""

    def __init__(
        self,
        project: str,
        location: str = "global",
        model: str = "gemini-3-flash-preview",
        *,
        client: Any = None,
        on_call: Optional[Callable[..., None]] = None,
    ):
        self.project = project
        self.location = location
        self.model = model
        self._client = client
        self._on_call = on_call

    @property
    def client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True, project=self.project, location=self.location
            )
        return self._client

    @staticmethod
    def _usage(resp: Any) -> tuple[int, int]:
        usage = getattr(resp, "usage_metadata", None)
        tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)
        tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0) + int(
            getattr(usage, "thoughts_token_count", 0) or 0
        )
        return tokens_in, tokens_out

    async def _generate(self, contents: str, config: Any) -> tuple[Any, int, int, float]:
        started = time.monotonic()
        ok = False
        tokens_in = tokens_out = 0
        try:
            resp = await self.client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )
            tokens_in, tokens_out = self._usage(resp)
            ok = True
            return resp, tokens_in, tokens_out, time.monotonic() - started
        finally:
            if self._on_call is not None:
                try:
                    self._on_call(
                        self.model,
                        time.monotonic() - started,
                        ok=ok,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )
                except Exception:
                    pass

    async def generate_fix(self, briefing: str, *, max_output_tokens: Optional[int] = None) -> FixResult:
        """Structured fix proposal via response_schema JSON. Token counts and
        wall time are measured from the actual response."""
        from google.genai import types as genai_types

        config = genai_types.GenerateContentConfig(
            system_instruction=_FIX_SYSTEM,
            response_mime_type="application/json",
            response_schema=FixProposal,
            temperature=0.2,
            max_output_tokens=max_output_tokens,
        )
        resp, tokens_in, tokens_out, seconds = await self._generate(briefing, config)
        proposal: Optional[FixProposal] = None
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, FixProposal):
            proposal = parsed
        else:
            text = getattr(resp, "text", "") or ""
            try:
                proposal = FixProposal.model_validate_json(_strip_fences(text))
            except Exception as e:
                raise VertexGeminiError(f"Gemini fix response was not valid JSON: {e}") from e
        if not proposal.files:
            raise VertexGeminiError("Gemini proposed no file changes")
        return FixResult(
            proposal=proposal,
            model=self.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=compute_cost(tokens_in, tokens_out),
            seconds=seconds,
        )

    async def smoke(self, prompt: str = "Reply with exactly: ok", max_output_tokens: int = 16) -> dict:
        """Tiny live check used by the verification harness — measures usage."""
        from google.genai import types as genai_types

        config = genai_types.GenerateContentConfig(max_output_tokens=max_output_tokens)
        resp, tokens_in, tokens_out, seconds = await self._generate(prompt, config)
        return {
            "text": (getattr(resp, "text", "") or "").strip(),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": compute_cost(tokens_in, tokens_out),
            "seconds": seconds,
        }


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
        if t.lower().startswith("json"):
            t = t[4:]
    return t.strip()
