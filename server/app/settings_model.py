"""The /api/settings document — section defaults.

The wire shape is sectioned (detection / diagnosis / fix_policy / oversight /
budgets / data / medic) and mirrors web/src/lib/api.ts `DarnSettings`.

Four toggles are constants, not settings; the server enforces them on every
read and rejects writes that try to flip them:
  oversight.darn_can_merge          locked OFF — Darn never merges by itself
  diagnosis.stop_when_not_code      locked ON  — Darn never guesses
  medic.self_traces                 locked ON  — the medic keeps the monitor on
  fix_policy.one_open_pr_per_service locked ON — no PR storms
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QuietHours(BaseModel):
    enabled: bool = False
    start: str = "22:00"
    end: str = "07:00"
    timezone: str = "UTC"


class Detection(BaseModel):
    poll_seconds: int = Field(default=30, ge=10, le=300)
    problem_scope: Literal["deploy_linked", "any_code_smell"] = "deploy_linked"
    quiet_hours: QuietHours = Field(default_factory=QuietHours)


class Diagnosis(BaseModel):
    dql_budget_per_incident: int = Field(default=12, ge=1, le=100)
    lookback_minutes: int = Field(default=30, ge=5, le=240)
    stop_when_not_code: bool = True  # locked on


class FixPolicy(BaseModel):
    branch_prefix: str = "darn/fix-"
    pr_labels: list[str] = Field(default_factory=lambda: ["darn", "auto-mend"])
    draft_prs: bool = False
    max_changed_files: int = Field(default=5, ge=1, le=20)
    max_diff_lines: int = Field(default=120, ge=10, le=1000)
    path_denylist: list[str] = Field(
        default_factory=lambda: ["migrations/", "infra/", ".github/"]
    )
    one_open_pr_per_service: bool = True  # locked on


class Oversight(BaseModel):
    darn_can_merge: bool = False  # locked off
    decline_tidy: bool = True
    webhook_url: str = ""


class Budgets(BaseModel):
    token_budget_per_fix: int = Field(default=40_000, ge=1_000, le=1_000_000)
    monthly_spend_cap_usd: float = Field(default=25.0, ge=0)
    dql_budget_per_day: int = Field(default=200, ge=1, le=10_000)


class DataPrivacy(BaseModel):
    retention: Literal["forever", "30d", "90d", "365d"] = "forever"


class Medic(BaseModel):
    self_traces: bool = True  # locked on
    share_timings_with_demo: bool = False


class DarnSettings(BaseModel):
    detection: Detection = Field(default_factory=Detection)
    diagnosis: Diagnosis = Field(default_factory=Diagnosis)
    fix_policy: FixPolicy = Field(default_factory=FixPolicy)
    oversight: Oversight = Field(default_factory=Oversight)
    budgets: Budgets = Field(default_factory=Budgets)
    data: DataPrivacy = Field(default_factory=DataPrivacy)
    medic: Medic = Field(default_factory=Medic)


# (section, field) -> (locked constant, the on-page caption explaining why)
LOCKED_FIELDS: dict[tuple[str, str], tuple[bool, str]] = {
    ("oversight", "darn_can_merge"): (
        False,
        "Never. A human with merge rights approves on GitHub. "
        "This switch exists to show you it's off.",
    ),
    ("diagnosis", "stop_when_not_code"): (
        True,
        "Not a setting. Darn never guesses.",
    ),
    ("medic", "self_traces"): (
        True,
        "The medic doesn't get to take off the monitor.",
    ),
    ("fix_policy", "one_open_pr_per_service"): (True, "No PR storms. Ever."),
}


def enforce_locked(values: DarnSettings) -> DarnSettings:
    for (section, field), (constant, _hint) in LOCKED_FIELDS.items():
        setattr(getattr(values, section), field, constant)
    return values


def merge_sections(current: dict, body: dict) -> dict:
    """One-level-deep section merge: a partial PUT updates only the fields it
    names; everything else keeps its current value."""
    merged = dict(current)
    for key, value in body.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged
