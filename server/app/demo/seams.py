"""Seams between the core server and the agent/integrations layer.

The core server (orchestrator, API, SSE, stores) is built against these
Protocols only. The agent layer provides real implementations via
`app.agent.wiring.build_backends`; until that exists, honest NotConfigured
fallbacks are used (see app.demo.fallbacks). The core never imports
app.agent or app.integrations at module load.

Wiring contract (for app/agent/wiring.py):

    def build_backends() -> Backends   # sync or async — both are accepted

  - Called once at startup, inside a try/except; any ImportError/Exception
    falls back to the NotConfigured implementations.
  - The return value may be the Backends dataclass below, or any object with
    attributes `sabotage`, `pipeline`, `health`, `byo_validator`. Attributes
    left as None fall back individually.
  - Pipeline note: after a server restart the orchestrator resumes a live
    incident by re-invoking the appropriate run_* method. Implementations
    should check stage states on the passed Incident and skip work already
    done (stages marked "done" stay done; receipts are append-only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable

from app.models import HealthCard, Incident, MedicTrace, Receipt


class NotConfiguredError(Exception):
    """A live dependency is missing. The API answers 503 {error: not_configured}."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(
            "not configured; missing: " + (", ".join(missing) or "unknown")
        )


class ByoValidationError(Exception):
    """Tenant validation failed in a way the user can fix. API answers 422."""

    def __init__(self, message: str, hint: str = ""):
        self.message = message
        self.hint = hint
        super().__init__(message)


@runtime_checkable
class StageEmitter(Protocol):
    """Provided BY the orchestrator TO the pipeline. Every call persists the
    incident through the Store and pushes the full incident over SSE."""

    async def stage_started(self, key: str) -> None: ...
    async def stage_done(self, key: str) -> None: ...
    async def emit_receipt(self, stage_key: str, receipt: Receipt) -> None: ...
    async def set_medic(self, trace: MedicTrace) -> None: ...
    async def fail(self, reason: str, evidence: str = "") -> None: ...


class SabotageBackend(Protocol):
    """Real GitHub actions for the demo path."""

    async def commit_defect(self, defect_key: str) -> dict[str, Any]:
        """Commit the defect's sabotaged files to GITHUB_REPO main.
        Returns {"sha": str, "message": str, "files": list[str]}.
        Raises NotConfiguredError when GitHub/the repo is not configured."""
        ...

    async def revert(self, incident: Incident) -> str:
        """Restore pre-sabotage content as a new commit; returns the revert sha."""
        ...

    async def merge_pr(self, incident: Incident) -> None: ...
    async def close_pr(self, incident: Incident) -> None: ...


class AgentPipeline(Protocol):
    """The agent's three movements. Each emits receipts/stage transitions via
    the emitter; each may call emitter.fail(...) to tie the incident off."""

    async def run_detect(self, incident: Incident, emitter: StageEmitter) -> None: ...
    async def run_diagnose_fix_pr(self, incident: Incident, emitter: StageEmitter) -> None: ...
    async def run_verify(self, incident: Incident, emitter: StageEmitter) -> None: ...


class HealthSource(Protocol):
    async def health_card(self) -> HealthCard: ...


class ByoValidator(Protocol):
    """Validates a BYO tenant by a REAL MCP initialize + tools/list round trip."""

    async def validate(
        self, tenant_url: str, platform_token: str
    ) -> list[dict[str, str]]:
        """Returns discovered services: [{"name": ..., "health": ...}].
        Raises ByoValidationError (user-fixable) or NotConfiguredError."""
        ...

    async def github_install_url(self) -> Optional[str]:
        """The GitHub App installation URL, or None when no App is configured."""
        ...


@dataclass
class Backends:
    sabotage: SabotageBackend
    pipeline: AgentPipeline
    health: HealthSource
    byo_validator: ByoValidator
