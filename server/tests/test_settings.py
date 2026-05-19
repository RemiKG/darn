"""Settings API: section defaults, ranges, locked toggles.

Wire shape is sectioned (detection / diagnosis / fix_policy / oversight /
budgets / data / medic), mirroring web/src/lib/api.ts `DarnSettings`.
"""

from __future__ import annotations

from tests.conftest import app_client


async def test_defaults():
    async with app_client() as (client, _app):
        r = await client.get("/api/settings")
        assert r.status_code == 200
        s = r.json()
        assert s["detection"]["poll_seconds"] == 30
        assert s["detection"]["problem_scope"] == "deploy_linked"
        assert s["detection"]["quiet_hours"] == {
            "enabled": False,
            "start": "22:00",
            "end": "07:00",
            "timezone": "UTC",
        }
        assert s["diagnosis"]["dql_budget_per_incident"] == 12
        assert s["diagnosis"]["lookback_minutes"] == 30
        assert s["fix_policy"]["branch_prefix"] == "darn/fix-"
        assert s["fix_policy"]["pr_labels"] == ["darn", "auto-mend"]
        assert s["fix_policy"]["draft_prs"] is False
        assert s["fix_policy"]["max_changed_files"] == 5
        assert s["fix_policy"]["max_diff_lines"] == 120
        assert s["fix_policy"]["path_denylist"] == [
            "migrations/",
            "infra/",
            ".github/",
        ]
        assert s["oversight"]["decline_tidy"] is True
        assert s["oversight"]["webhook_url"] == ""
        assert s["budgets"]["token_budget_per_fix"] == 40_000
        assert s["budgets"]["monthly_spend_cap_usd"] == 25.0
        assert s["budgets"]["dql_budget_per_day"] == 200
        assert s["data"]["retention"] == "forever"
        assert s["medic"]["share_timings_with_demo"] is False
        # the locked four
        assert s["oversight"]["darn_can_merge"] is False
        assert s["diagnosis"]["stop_when_not_code"] is True
        assert s["medic"]["self_traces"] is True
        assert s["fix_policy"]["one_open_pr_per_service"] is True


async def test_put_saves_and_roundtrips():
    async with app_client() as (client, _app):
        r = await client.put(
            "/api/settings",
            json={
                "detection": {"poll_seconds": 60},
                "fix_policy": {"pr_labels": ["darn"], "draft_prs": True},
            },
        )
        assert r.status_code == 200
        assert r.json()["detection"]["poll_seconds"] == 60
        r2 = await client.get("/api/settings")
        s = r2.json()
        assert s["detection"]["poll_seconds"] == 60
        assert s["fix_policy"]["pr_labels"] == ["darn"]
        assert s["fix_policy"]["draft_prs"] is True
        # untouched fields keep defaults — across and within sections
        assert s["diagnosis"]["dql_budget_per_incident"] == 12
        assert s["fix_policy"]["max_diff_lines"] == 120
        assert s["detection"]["problem_scope"] == "deploy_linked"


async def test_put_range_validation():
    async with app_client() as (client, _app):
        for bad in (
            {"detection": {"poll_seconds": 5}},
            {"detection": {"poll_seconds": 301}},
        ):
            r = await client.put("/api/settings", json=bad)
            assert r.status_code == 422
        r2 = await client.put(
            "/api/settings", json={"fix_policy": {"max_diff_lines": 5}}
        )
        assert r2.status_code == 422
        # the failed writes changed nothing
        s = (await client.get("/api/settings")).json()
        assert s["detection"]["poll_seconds"] == 30


async def test_locked_toggles_are_rejected():
    async with app_client() as (client, _app):
        for section, field, flipped in (
            ("oversight", "darn_can_merge", True),
            ("diagnosis", "stop_when_not_code", False),
            ("medic", "self_traces", False),
            ("fix_policy", "one_open_pr_per_service", False),
        ):
            r = await client.put("/api/settings", json={section: {field: flipped}})
            assert r.status_code == 422, f"{section}.{field}"
            assert "locked" in r.json()["error"]
            assert r.json()["hint"]
        # sending the locked value unchanged is fine
        r2 = await client.put(
            "/api/settings", json={"oversight": {"darn_can_merge": False}}
        )
        assert r2.status_code == 200


async def test_put_rejects_non_object():
    async with app_client() as (client, _app):
        r = await client.put("/api/settings", content=b"[1,2,3]")
        assert r.status_code == 422
