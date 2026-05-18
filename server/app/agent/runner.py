"""The Google ADK diagnosis agent — ``darn_diagnostician``.

ADK 2.2.0 reality (introspected from the installed package):
- ``google.adk.agents.LlmAgent`` with ``tools=[FunctionTool(...)]`` and a
  Gemini model; ``google.adk.runners.InMemoryRunner`` drives it and yields
  events whose ``usage_metadata`` carries real token counts.
- ADK 2.2.0 DOES ship an MCP toolset with streamable-HTTP params
  (``google.adk.tools.mcp_tool.McpToolset`` +
  ``StreamableHTTPConnectionParams``). We deliberately do NOT route the agent
  through it: every Dynatrace call must go through
  ``app.integrations.dynatrace_mcp`` directly so receipts capture the verbatim
  query/result, the DQL budget is enforced deterministically, and scope
  failures surface as typed errors. So the agent is a genuine ADK ``LlmAgent``
  whose FunctionTools delegate to our ``DynatraceMcpClient`` — the documented
  fallback shape, chosen here as the primary for receipt fidelity.

Deterministic guardrails: the toolkit hard-caps DQL at the per-incident budget;
whatever the LLM decides, receipts only record REAL executed calls.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

from ..integrations.dynatrace_mcp import (
    DynatraceMcpClient,
    DynatraceMcpError,
    DynatraceScopeError,
    ToolResult,
)


# ------------------------------------------------------------------ results

class StackFrame(BaseModel):
    path: str = ""
    line: int = 0
    function: str = ""


class DiagnosisResult(BaseModel):
    """Structured output of the diagnosis agent."""

    problem_id: str = ""
    endpoint: str = ""  # e.g. "POST /api/checkout"
    exception_message: str = ""
    stack_frames: list[StackFrame] = Field(default_factory=list)
    onset: str = ""  # ISO-8601 timestamp of the first failure
    code_shaped: bool = True  # False => evidence does not point at code
    narrative: str = ""  # 2-4 plain sentences


@dataclass
class AdkRunStats:
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    llm_calls: int = 0


@dataclass
class CapturedCall:
    """One REAL executed tool call, captured verbatim for receipts + medic."""

    tool: str
    arguments: dict[str, Any]
    data: Any = None
    text: str = ""
    seconds: float = 0.0
    ok: bool = True
    error: str = ""
    scope_error: bool = False


CaptureFn = Callable[[CapturedCall], Optional[Awaitable[None]]]


class DiagnosisError(RuntimeError):
    pass


# ------------------------------------------------------------------ toolkit

class ForensicsToolkit:
    """Budgeted, captured access to the Dynatrace MCP gateway.

    Every method performs a REAL gateway call through DynatraceMcpClient and
    fires ``on_capture`` with the verbatim arguments and parsed result. The
    DQL budget is enforced HERE, not in the prompt: once spent, calls are
    refused without touching the gateway (and refusals are not captured,
    because nothing real happened).
    """

    def __init__(
        self,
        mcp: DynatraceMcpClient,
        *,
        dql_budget: int = 12,
        on_capture: Optional[CaptureFn] = None,
    ):
        self._mcp = mcp
        self.dql_budget = max(0, dql_budget)
        self.dql_used = 0
        self._on_capture = on_capture
        self.calls: list[CapturedCall] = []

    async def _capture(self, call: CapturedCall) -> None:
        self.calls.append(call)
        if self._on_capture is not None:
            result = self._on_capture(call)
            if inspect.isawaitable(result):
                await result

    async def _run(self, tool: str, arguments: dict[str, Any]) -> Any:
        try:
            result: ToolResult = await self._mcp.call_tool(tool, arguments)
        except DynatraceScopeError as e:
            await self._capture(
                CapturedCall(
                    tool=tool, arguments=arguments, ok=False,
                    error=str(e), scope_error=True,
                )
            )
            return {"error": f"Dynatrace scope error: {e}"}
        except DynatraceMcpError as e:
            await self._capture(
                CapturedCall(tool=tool, arguments=arguments, ok=False, error=str(e))
            )
            return {"error": str(e)}
        await self._capture(
            CapturedCall(
                tool=tool,
                arguments=arguments,
                data=result.data,
                text=result.text,
                seconds=result.seconds,
            )
        )
        return result.data if result.data is not None else result.text

    async def execute_dql(self, query: str) -> Any:
        if self.dql_used >= self.dql_budget:
            # Refused deterministically; no gateway call, no receipt.
            return {
                "error": (
                    f"DQL budget reached ({self.dql_budget} queries this incident). "
                    "Work with the evidence you already have."
                )
            }
        self.dql_used += 1
        return await self._run("execute-dql", {"dqlQueryString": query})

    async def get_problem(self, problem_id: str, history: str = "30m") -> Any:
        return await self._run(
            "get-problem-by-id", {"problemId": problem_id, "history": history}
        )

    async def get_entity_id(self, name: str, entity_type: str = "dt.entity.service") -> Any:
        return await self._run(
            "get-entity-id", {"entityType": entity_type, "entityNameFilter": name}
        )


# ---------------------------------------------------------------- the agent

DIAGNOSIS_INSTRUCTION = """\
You are darn_diagnostician, the forensic diagnosis agent inside Darn. A Davis
problem is open on a production service. Your job is to PROVE what broke, with
queries a human can re-run — not to guess.

Work in this order:
1. get_problem_details for the problem id you were given.
2. execute_dql — failures by endpoint over the last 30m for the service, e.g.:
   fetch spans, from: now() - 30m
   | filter service.name == "<service>" and request.is_failed == true
   | summarize failures = count(), by: { endpoint.name }
   | sort failures desc
3. execute_dql — the exception: messages and stack frames from logs, e.g.:
   fetch logs, from: now() - 30m
   | filter service.name == "<service>" and loglevel == "ERROR"
   | fields timestamp, content
   | sort timestamp desc
   | limit 20
4. execute_dql — onset: the earliest failure timestamp, e.g.:
   fetch spans, from: now() - 30m
   | filter service.name == "<service>" and request.is_failed == true
   | summarize onset = min(start_time)

Rules:
- You have a HARD budget of DQL queries; the tool refuses you beyond it. Make
  every query count. If a query errors, fix the field names once and move on.
- If field names are rejected, adapt (request.is_failed vs http.response.status_code >= 500;
  endpoint.name vs url.path). Tolerate schema drift.
- If the evidence does NOT point at code (no exceptions, no failing endpoint,
  infra-shaped signal), say so: set code_shaped=false and explain in narrative.

When done, reply with ONLY a JSON object (no markdown fences):
{"problem_id": "...", "endpoint": "VERB /path", "exception_message": "...",
 "stack_frames": [{"path": "app/checkout.py", "line": 118, "function": "total"}],
 "onset": "ISO-8601 timestamp", "code_shaped": true, "narrative": "2-4 sentences"}
"""


def build_vertex_model(model_name: str, project: str, location: str) -> Any:
    """A google.adk Gemini model pinned to Vertex with explicit project/location
    (the pattern documented in google.adk.models.google_llm)."""
    from google.adk.models.google_llm import Gemini

    class _VertexGemini(Gemini):
        @cached_property
        def api_client(self):  # type: ignore[override]
            from google.genai import Client

            return Client(vertexai=True, project=project, location=location)

    return _VertexGemini(model=model_name)


def build_diagnosis_agent(toolkit: ForensicsToolkit, model: Any) -> Any:
    """LlmAgent('darn_diagnostician') whose FunctionTools delegate to the
    budgeted toolkit (which delegates to DynatraceMcpClient)."""
    from google.adk.agents import LlmAgent
    from google.adk.tools import FunctionTool

    async def execute_dql(dql_query_string: str) -> dict:
        """Run one DQL query against Dynatrace Grail. Budgeted — every call counts.

        Args:
            dql_query_string: the complete DQL statement to execute.
        """
        return _jsonable(await toolkit.execute_dql(dql_query_string))

    async def get_problem_details(problem_id: str) -> dict:
        """Fetch the full Davis problem details by id (e.g. "P-123456").

        Args:
            problem_id: the Davis problem display id.
        """
        return _jsonable(await toolkit.get_problem(problem_id))

    async def find_service_entity(entity_name_filter: str) -> dict:
        """Resolve a monitored service entity id by (partial) name.

        Args:
            entity_name_filter: service name or fragment to look up.
        """
        return _jsonable(await toolkit.get_entity_id(entity_name_filter))

    return LlmAgent(
        name="darn_diagnostician",
        model=model,
        instruction=DIAGNOSIS_INSTRUCTION,
        tools=[
            FunctionTool(execute_dql),
            FunctionTool(get_problem_details),
            FunctionTool(find_service_entity),
        ],
    )


def _jsonable(value: Any) -> dict:
    """ADK FunctionTools must return a dict; wrap scalars/lists."""
    if isinstance(value, dict):
        return value
    return {"result": value}


def parse_diagnosis(text: str) -> DiagnosisResult:
    """Lenient parse of the agent's final message into DiagnosisResult."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"```\s*$", "", t).strip()
    # Find the outermost JSON object if the model added prose around it.
    if not t.startswith("{"):
        match = re.search(r"\{.*\}", t, re.DOTALL)
        if match:
            t = match.group(0)
    try:
        return DiagnosisResult.model_validate(json.loads(t))
    except (ValueError, TypeError) as e:
        raise DiagnosisError(f"Diagnosis agent did not return valid JSON: {e}") from e


class AdkDiagnosisRunner:
    """Runs the ADK agent for one diagnosis and returns (result, stats).

    Implements the ``DiagnosisRunner`` seam used by stages.py:
        async diagnose(*, toolkit, problem_id, service_name, context_note="")
    """

    def __init__(
        self,
        *,
        project: str = "",
        location: str = "global",
        model_name: str = "gemini-3-flash-preview",
        model: Any = None,
        max_wait_s: float = 240.0,
    ):
        self._project = project
        self._location = location
        self._model_name = model_name
        self._model = model
        self._max_wait_s = max_wait_s

    def _build_model(self) -> Any:
        if self._model is not None:
            return self._model
        return build_vertex_model(self._model_name, self._project, self._location)

    async def diagnose(
        self,
        *,
        toolkit: ForensicsToolkit,
        problem_id: str,
        service_name: str,
        context_note: str = "",
    ) -> tuple[DiagnosisResult, AdkRunStats]:
        from google.adk.runners import InMemoryRunner
        from google.genai import types as genai_types

        agent = build_diagnosis_agent(toolkit, self._build_model())
        runner = InMemoryRunner(agent=agent, app_name="darn")
        session_id = f"diag-{uuid.uuid4().hex[:8]}"
        await runner.session_service.create_session(
            app_name=runner.app_name, user_id="darn", session_id=session_id
        )
        prompt = (
            f"Davis problem {problem_id} is open on service \"{service_name}\". "
            f"{context_note} Investigate and return the JSON diagnosis."
        )
        stats = AdkRunStats()
        final_text = ""
        started = time.monotonic()

        async def _consume() -> None:
            nonlocal final_text
            async for event in runner.run_async(
                user_id="darn",
                session_id=session_id,
                new_message=genai_types.Content(
                    role="user", parts=[genai_types.Part(text=prompt)]
                ),
            ):
                usage = getattr(event, "usage_metadata", None)
                if usage is not None:
                    stats.llm_calls += 1
                    stats.tokens_in += int(getattr(usage, "prompt_token_count", 0) or 0)
                    stats.tokens_out += int(
                        getattr(usage, "candidates_token_count", 0) or 0
                    ) + int(getattr(usage, "thoughts_token_count", 0) or 0)
                content = getattr(event, "content", None)
                if content is not None and getattr(content, "parts", None):
                    texts = [p.text for p in content.parts if getattr(p, "text", None)]
                    if texts and event.is_final_response():
                        final_text = "".join(texts)

        try:
            await asyncio.wait_for(_consume(), timeout=self._max_wait_s)
        except asyncio.TimeoutError as e:
            raise DiagnosisError(
                f"Diagnosis agent exceeded {self._max_wait_s:.0f}s"
            ) from e
        finally:
            stats.seconds = time.monotonic() - started
            try:
                await runner.close()
            except Exception:
                pass

        if not final_text:
            raise DiagnosisError("Diagnosis agent produced no final response")
        return parse_diagnosis(final_text), stats
