"""HealthSource — the live health card for the shop floor.

Error rate / p95 / req-min and a 30-point sparkline come from REAL DQL over
spans. When the token lacks Grail read scopes (today's known state), the card
degrades to an honest ``unavailable`` with a plain-language reason — numbers
are never invented. The last-deploy line comes from GitHub (last commit on the
default branch touching shop/), which works independently of Dynatrace scopes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ..integrations.dynatrace_mcp import (
    DynatraceMcpClient,
    DynatraceMcpError,
    DynatraceScopeError,
)
from ..integrations.github_client import GitHubClient, GitHubError
from ..models import HealthCard, SparkPoint, now_s

log = logging.getLogger("darn.agent.health")

SCOPE_REASON = "Dynatrace token lacks Grail read scopes on this deployment"


def _to_epoch(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            try:
                v = float(value)
                return v / 1000.0 if v > 1e11 else v
            except ValueError:
                return None
    return None


def _records(data: Any) -> list[dict]:
    if isinstance(data, dict):
        for key in ("records", "results", "rows", "data"):
            if isinstance(data.get(key), list):
                return [r for r in data[key] if isinstance(r, dict)]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _num(record: dict, *names: str) -> Optional[float]:
    for name in names:
        for key, value in record.items():
            if key.lower() == name.lower() and isinstance(value, (int, float)):
                return float(value)
    return None


def _ms(value: Optional[float]) -> Optional[float]:
    """Grail span durations are nanoseconds; tolerate ms-shaped values."""
    if value is None:
        return None
    return round(value / 1_000_000, 1) if value > 100_000 else round(value, 1)


class DqlHealthSource:
    """Implements the HealthSource seam: ``async health_card() -> HealthCard``."""

    SUMMARY_QUERY = (
        "fetch spans, from: now() - 30m\n"
        '| filter service.name == "{service}"\n'
        "| summarize total = count(), failures = countIf(request.is_failed == true), "
        "p95 = percentile(duration, 95)"
    )
    SPARK_QUERY = (
        "fetch spans, from: now() - 30m\n"
        '| filter service.name == "{service}"\n'
        "| summarize total = count(), failures = countIf(request.is_failed == true), "
        "by: { interval = bin(start_time, 1m) }\n"
        "| sort interval asc"
    )

    def __init__(
        self,
        mcp: Optional[DynatraceMcpClient],
        github: Optional[GitHubClient] = None,
        *,
        service_name: str,
        torn_error_rate: float = 5.0,
    ):
        self._mcp = mcp
        self._github = github
        self._service = service_name
        self._torn_error_rate = torn_error_rate

    async def health_card(self) -> HealthCard:
        card = await self._dql_card()
        await self._fill_last_deploy(card)
        return card

    async def _dql_card(self) -> HealthCard:
        if self._mcp is None:
            return HealthCard(
                status="unavailable",
                source="unavailable",
                reason="Dynatrace is not configured on this deployment",
            )
        try:
            summary = await self._mcp.call_tool(
                "execute-dql",
                {"dqlQueryString": self.SUMMARY_QUERY.format(service=self._service)},
            )
            records = _records(summary.data)
            if not records:
                return HealthCard(
                    status="unavailable",
                    source="unavailable",
                    reason=f"No span data for service \"{self._service}\" in the last 30 minutes",
                )
            row = records[0]
            total = _num(row, "total") or 0.0
            failures = _num(row, "failures") or 0.0
            error_rate = round(100.0 * failures / total, 2) if total else None
            p95_ms = _ms(_num(row, "p95"))
            rpm = round(total / 30.0, 1) if total else None
            sparkline = await self._sparkline()
            status = "ok"
            if error_rate is not None and error_rate >= self._torn_error_rate:
                status = "torn"
            return HealthCard(
                status=status,
                error_rate=error_rate,
                p95_ms=p95_ms,
                rpm=rpm,
                sparkline=sparkline,
                source="dql",
            )
        except DynatraceScopeError as e:
            log.info("health: scope error: %s", e)
            return HealthCard(status="unavailable", source="unavailable", reason=SCOPE_REASON)
        except DynatraceMcpError as e:
            log.warning("health: gateway error: %s", e)
            return HealthCard(
                status="unavailable",
                source="unavailable",
                reason=f"Dynatrace DQL query failed: {e}",
            )

    async def _sparkline(self) -> list[SparkPoint]:
        try:
            result = await self._mcp.call_tool(
                "execute-dql",
                {"dqlQueryString": self.SPARK_QUERY.format(service=self._service)},
            )
        except (DynatraceScopeError, DynatraceMcpError):
            return []
        points: list[SparkPoint] = []
        for record in _records(result.data)[:30]:
            t = None
            for key, value in record.items():
                if "interval" in key.lower() or "time" in key.lower():
                    t = _to_epoch(value)
                    break
            total = _num(record, "total") or 0.0
            failures = _num(record, "failures") or 0.0
            rate = round(100.0 * failures / total, 2) if total else 0.0
            points.append(
                SparkPoint(
                    t=t if t is not None else now_s(),
                    v=rate,
                    anomalous=rate >= self._torn_error_rate,
                )
            )
        return points

    async def _fill_last_deploy(self, card: HealthCard) -> None:
        if self._github is None:
            return
        try:
            branch = await self._github.get_repo_default_branch()
            commits = await self._github.list_commits(branch, path="shop", per_page=1)
            if not commits:
                commits = await self._github.list_commits(branch, per_page=1)
            if commits:
                card.last_deploy_sha = commits[0]["sha"][:7]
                epoch = _to_epoch(commits[0]["date"])
                if epoch is not None:
                    card.last_deploy_ago_s = max(0.0, round(now_s() - epoch, 0))
        except GitHubError as e:
            log.info("health: last deploy lookup failed: %s", e)
