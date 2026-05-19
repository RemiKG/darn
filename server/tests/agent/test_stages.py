"""Full pipeline against fakes: receipts arrive in display order,
the tied-off path stops the pipeline, and the DQL budget is a hard wall."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.agent.runner import AdkRunStats, DiagnosisResult, ForensicsToolkit, StackFrame
from app.agent.stages import DarnPipeline
from app.integrations.vertex_gemini import FixFile, FixProposal, FixResult
from app.models import now_s

SERVICE = "loose-threads-shop"
ONSET_ISO = "2026-06-11T02:57:14Z"

PROBLEM = {
    "displayId": "P-25061123",
    "problemId": "8742349874PROBLEM",
    "title": "Failure rate increase",
    "status": "ACTIVE",
    "severityLevel": "ERROR",
    "impactLevel": "SERVICES",
    "startTime": None,  # filled per-test (must be >= incident start - 2 min)
    "affectedEntities": [{"name": SERVICE}],
}

DQL_NUMBERS = (
    "fetch spans, from: now() - 30m\n"
    f'| filter service.name == "{SERVICE}" and request.is_failed == true\n'
    "| summarize failures = count(), by: { endpoint.name }\n"
    "| sort failures desc"
)
DQL_LOGS = (
    "fetch logs, from: now() - 30m\n"
    f'| filter service.name == "{SERVICE}" and loglevel == "ERROR"\n'
    "| fields timestamp, content\n| limit 20"
)

SUSPECT_PATCH = (
    "@@ -110,12 +110,14 @@ class CheckoutService:\n"
    "     def total(self, cart):\n"
    "-        if cart is None:\n"
    "-            return 0\n"
    "+        # streamlined: carts are always present\n"
    "+        items = cart.items\n"
    "         ..."
)


class FakeMcp:
    """call_tool fake returning realistic parsed payloads."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.problem = dict(PROBLEM)
        self.problem_closed = False

    async def connect(self):
        return {}

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        if name == "query-problems":
            data = {"problems": [self.problem]}
        elif name == "get-problem-by-id":
            p = dict(self.problem)
            if self.problem_closed:
                p["status"] = "CLOSED"
                p["endTime"] = (now_s()) * 1000
            data = p
        elif name == "execute-dql":
            q = arguments["dqlQueryString"]
            if "fetch logs" in q:
                data = {
                    "records": [
                        {
                            "timestamp": ONSET_ISO,
                            "content": (
                                "AttributeError: 'NoneType' object has no attribute 'items'\n"
                                '  File "shop/app/checkout.py", line 118, in total'
                            ),
                        }
                    ]
                }
            else:
                data = {"records": [{"endpoint.name": "POST /api/checkout", "failures": 41}]}
        else:
            data = {}
        return SimpleNamespace(
            name=name, arguments=arguments or {}, data=data, text=json.dumps(data), seconds=0.01
        )


class FakeGitHub:
    repo = "remikg/loose-threads"

    def __init__(self, *, sabotage_sha="9b1f2e3aa0d4c5b6e7f8091a2b3c4d5e6f708192", commits=None):
        self.sabotage_sha = sabotage_sha
        self.commits = commits
        self.created_branches: list[tuple[str, str]] = []
        self.committed: list[tuple[dict, str, str]] = []
        self.prs: list[dict] = []
        self.comments: list[tuple[int, str]] = []

    async def get_repo_default_branch(self):
        return "main"

    async def get_branch_sha(self, branch):
        return "main-head-sha"

    async def get_commit(self, sha):
        return {
            "sha": sha,
            "message": "chore: simplify checkout maths",
            "date": "2026-06-11T02:56:36Z",
            "parents": ["parent-sha"],
            "files": [],
        }

    async def compare(self, base, head):
        return {
            "commits": [{"sha": head, "message": "chore: simplify checkout maths"}],
            "files": [{"filename": "shop/app/checkout.py", "status": "modified", "patch": SUSPECT_PATCH}],
        }

    async def list_commits(self, branch, since=None, path=None, per_page=20):
        if self.commits is not None:
            return self.commits
        return [{"sha": self.sabotage_sha, "message": "chore", "date": "2026-06-11T02:56:36Z"}]

    async def get_file(self, path, ref=None):
        return {"content": "def total(self, cart):\n    items = cart.items\n", "sha": "blob"}

    async def create_branch(self, from_sha, name):
        self.created_branches.append((from_sha, name))
        return name

    async def commit_files(self, files, message, branch):
        self.committed.append((files, message, branch))
        return "fix-commit-sha"

    async def create_pr(self, title, body, head, base):
        self.prs.append({"title": title, "body": body, "head": head, "base": base})
        return {"number": 48, "url": "https://github.com/remikg/loose-threads/pull/48"}

    async def get_pr(self, number):
        return {"number": number, "merged": True, "merge_commit_sha": "merge-sha", "state": "closed"}

    async def get_checks_for_ref(self, sha):
        return [{"name": "deploy", "status": "completed", "conclusion": "success"}]

    async def comment_pr(self, number, body):
        self.comments.append((number, body))
        return "https://github.com/c/1"


class FakeGemini:
    model = "gemini-test"

    async def generate_fix(self, briefing):
        assert "receipts" in briefing  # briefed with the receipts
        return FixResult(
            proposal=FixProposal(
                files=[
                    FixFile(
                        path="shop/app/checkout.py",
                        new_content="def total(self, cart):\n    if cart is None:\n        return 0\n    items = cart.items\n",
                    )
                ],
                rationale="The deploy removed the None-cart guard; restoring it stops the AttributeError.",
                pr_title="Mend: null cart at checkout",
                pr_body_sections=[],
            ),
            model=self.model,
            tokens_in=18412,
            tokens_out=1207,
            cost_usd=None,
            seconds=2.0,
        )


class FakeDiagnosisRunner:
    """Calls the budgeted toolkit like the real ADK agent would."""

    def __init__(self, *, code_shaped=True, queries=2):
        self.code_shaped = code_shaped
        self.queries = queries

    async def diagnose(self, *, toolkit: ForensicsToolkit, problem_id, service_name, context_note=""):
        await toolkit.get_problem(problem_id)
        if self.queries >= 1:
            await toolkit.execute_dql(DQL_NUMBERS)
        if self.queries >= 2:
            await toolkit.execute_dql(DQL_LOGS)
        result = DiagnosisResult(
            problem_id=problem_id,
            endpoint="POST /api/checkout",
            exception_message="AttributeError: 'NoneType' object has no attribute 'items'",
            stack_frames=[StackFrame(path="shop/app/checkout.py", line=118, function="total")],
            onset=ONSET_ISO,
            code_shaped=self.code_shaped,
            narrative="Checkout fails on empty carts since the last deploy.",
        )
        return result, AdkRunStats(tokens_in=1000, tokens_out=200, seconds=3.0, llm_calls=3)


def _shop_transport():
    state = {"healthy": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["healthy"]:
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(500, text="AttributeError")

    return state, httpx.MockTransport(handler)


def _pipeline(fake_settings, mcp, github, gemini, runner, shop_transport):
    return DarnPipeline(
        mcp=mcp,
        github=github,
        gemini=gemini,
        events=None,
        telemetry=None,
        diagnosis_runner=runner,
        settings_obj=fake_settings,
        http=httpx.AsyncClient(transport=shop_transport),
        settle_seconds=0,
        check_poll_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_full_pipeline_receipt_order(fake_settings, make_incident, fake_emitter_factory):
    incident = make_incident()
    emitter = fake_emitter_factory(incident)
    mcp = FakeMcp()
    mcp.problem["startTime"] = (incident.started_at + 60) * 1000
    github = FakeGitHub()
    shop_state, transport = _shop_transport()
    pipeline = _pipeline(fake_settings, mcp, github, FakeGemini(), FakeDiagnosisRunner(), transport)

    # --- stage 1: detect (completes only on the REAL matching problem)
    await pipeline.run_detect(incident, emitter)
    assert emitter.failure is None
    assert emitter.receipt_types("detected") == ["davis_problem"]
    davis = incident.stage("detected").receipts[0]
    assert davis.problem_id == "P-25061123"
    # link uses the long internal problemId in the new Davis problems app
    assert davis.dynatrace_link and davis.dynatrace_link.endswith(
        "/ui/apps/dynatrace.davis.problems/problem/8742349874PROBLEM"
    )
    assert incident.stage("detected").state == "done"

    # --- stages 2-4
    await pipeline.run_diagnose_fix_pr(incident, emitter)
    assert emitter.failure is None
    assert emitter.receipt_types("diagnosed") == [
        "dql", "dql_result",          # The numbers
        "dql", "dql_result",          # The exception
        "timing_ruler",               # The timing
        "suspect_hunk",               # The suspect
        "note",                       # stage footer with measured DQL count
    ]
    dqls = [r for r in incident.stage("diagnosed").receipts if r.type == "dql"]
    assert dqls[0].query == DQL_NUMBERS  # verbatim
    assert dqls[0].group == "numbers" and dqls[1].group == "exception"
    timing = next(r for r in incident.stage("diagnosed").receipts if r.type == "timing_ruler")
    assert timing.deploy_sha == incident.sabotage_sha
    assert timing.gap_s == 38.0  # 02:56:36 -> 02:57:14, measured
    assert "deploy `9b1f2e3`" in timing.note
    suspect = next(r for r in incident.stage("diagnosed").receipts if r.type == "suspect_hunk")
    assert suspect.path == "shop/app/checkout.py"
    assert "checkout.py:118" in suspect.caption
    footer = incident.stage("diagnosed").receipts[-1]
    assert "DQL queries this diagnosis: 2" in footer.text

    assert emitter.receipt_types("fix_written") == ["proposed_diff", "rationale", "model_meta"]
    diff = incident.stage("fix_written").receipts[0]
    assert "+    if cart is None:" in diff.diff  # difflib current-vs-proposed
    meta = incident.stage("fix_written").receipts[2]
    assert meta.tokens_in == 18412 and meta.cost_usd is None

    assert emitter.receipt_types("pr_open") == ["pr"]
    pr = incident.stage("pr_open").receipts[0]
    assert pr.number == 48 and pr.branch == "darn/fix-checkout-null"
    assert pr.toc[0] == "Problem" and pr.toc[-1] == "How to verify"
    assert any(t.startswith("Receipts (DQL ×") for t in pr.toc)
    assert incident.pr_number == 48
    body = github.prs[0]["body"]
    assert DQL_NUMBERS in body  # copy-pasteable receipts travel with the fix
    assert "```diff" in body

    # --- stage 6: verify (after the core merged the PR)
    incident.stage("approved").state = "done"
    incident.stage("approved").started_at = now_s()
    incident.stage("approved").done_at = now_s()
    shop_state["healthy"] = True
    mcp.problem_closed = True
    await pipeline.run_verify(incident, emitter)
    assert emitter.failure is None
    assert emitter.receipt_types("verified") == [
        "replay", "dql", "dql_result", "note", "closure",
    ]
    replay = incident.stage("verified").receipts[0]
    assert replay.before_status == 500 and replay.after_status == 200  # both measured
    closure = incident.stage("verified").receipts[-1]
    assert closure.problem_id == "P-25061123" and closure.pr_comment_posted
    assert closure.annotation_sent is False  # no DT_API_TOKEN -> honest skip note
    note = incident.stage("verified").receipts[3]
    assert "DT_API_TOKEN" in note.text

    assert incident.status == "verified_closed"
    summary = incident.wall_clock_summary
    assert summary is not None and summary.dql_receipts == 3
    assert github.comments and "P-25061123" in github.comments[0][1]
    assert emitter.medic is not None
    gemini_rows = [r for r in emitter.medic.rows if r.kind == "gemini"]
    assert gemini_rows and gemini_rows[0].tokens_in == 1000


@pytest.mark.asyncio
async def test_tied_off_path_stops_pipeline(fake_settings, make_incident, fake_emitter_factory):
    incident = make_incident(defect_key=None, sabotage_sha=None, kind="byo")
    emitter = fake_emitter_factory(incident)
    mcp = FakeMcp()
    mcp.problem["startTime"] = (incident.started_at + 30) * 1000
    github = FakeGitHub(commits=[])  # no deploys in the window
    _, transport = _shop_transport()
    pipeline = _pipeline(
        fake_settings, mcp, github, FakeGemini(),
        FakeDiagnosisRunner(code_shaped=False), transport,
    )
    await pipeline.run_detect(incident, emitter)
    await pipeline.run_diagnose_fix_pr(incident, emitter)

    assert incident.status == "tied_off"
    assert incident.stage("diagnosed").state == "tied_off"
    knot = incident.stage("diagnosed").receipts[-1]
    assert knot.type == "knot"
    assert knot.reason == "This hole isn't in the code."
    assert "No PR. No guessing." in knot.evidence
    # stages 3-6 never started
    assert incident.stage("fix_written").state == "pending"
    assert incident.stage("pr_open").receipts == []
    assert github.prs == []


@pytest.mark.asyncio
async def test_dql_budget_is_a_hard_wall(fake_settings):
    mcp = FakeMcp()
    captured = []
    toolkit = ForensicsToolkit(mcp, dql_budget=2, on_capture=captured.append)
    out1 = await toolkit.execute_dql(DQL_NUMBERS)
    out2 = await toolkit.execute_dql(DQL_LOGS)
    out3 = await toolkit.execute_dql("fetch spans | limit 1")
    out4 = await toolkit.execute_dql("fetch logs | limit 1")
    assert "records" in out1 and "records" in out2
    assert out3.get("error", "").startswith("DQL budget reached")
    assert out4.get("error", "").startswith("DQL budget reached")
    # only REAL executed calls reached the gateway and were captured
    assert len([c for c in mcp.calls if c[0] == "execute-dql"]) == 2
    assert len([c for c in captured if c.tool == "execute-dql"]) == 2
    assert toolkit.dql_used == 2


@pytest.mark.asyncio
async def test_detect_emits_honest_note_on_scope_error_then_recovers(
    fake_settings, make_incident, fake_emitter_factory
):
    from app.integrations.dynatrace_mcp import DynatraceScopeError

    incident = make_incident()
    emitter = fake_emitter_factory(incident)

    class ScopedThenOkMcp(FakeMcp):
        def __init__(self):
            super().__init__()
            self.n = 0

        async def call_tool(self, name, arguments=None):
            if name == "query-problems":
                self.n += 1
                if self.n == 1:
                    raise DynatraceScopeError(
                        "Tool error: Insufficient permission to access table (events)."
                    )
            return await super().call_tool(name, arguments)

    mcp = ScopedThenOkMcp()
    mcp.problem["startTime"] = (incident.started_at + 30) * 1000
    fake_settings.poll_seconds = 0.05  # keep the retry sleep tiny for the test
    _, transport = _shop_transport()
    pipeline = _pipeline(fake_settings, mcp, FakeGitHub(), FakeGemini(), FakeDiagnosisRunner(), transport)
    await pipeline.run_detect(incident, emitter)
    types = emitter.receipt_types("detected")
    assert types == ["note", "davis_problem"]
    note = incident.stage("detected").receipts[0]
    assert "Grail read scopes" in note.text
    assert "Insufficient permission" in note.text  # raw gateway message surfaced
