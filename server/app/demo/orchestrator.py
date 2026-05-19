"""The demo state machine.

Owns: the single-incident lock, the needle (holder + presence), the spectator
count, the cooldown timer, the approve-timeout, and the seam calls into the
agent layer. Every transition is persisted through the Store and the full
incident is published over SSE.

Single-process writer: the live incident is held canonically in memory
(`self._live`) and written through on every change; the store is the resume
source after a restart.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from app.config import settings
from app.demo.defects import defect_exists, defect_title
from app.demo.seams import (
    AgentPipeline,
    NotConfiguredError,
    SabotageBackend,
)
from app.models import (
    ApprovalReceipt,
    Incident,
    KnotReceipt,
    MedicTrace,
    Needle,
    NoteReceipt,
    Receipt,
    STAGE_KEYS,
    WallClockSummary,
    summarize,
)
from app.sse import SseHub
from app.store import Store
from app.views import incident_to_json

log = logging.getLogger("darn.demo")

PRESENCE_WINDOW_S = 30  # a watcher counts if they posted presence this recently


# ----------------------------------------------------------------- errors

class DemoError(Exception):
    pass


class UnknownDefectError(DemoError):
    pass


class LockedError(DemoError):
    def __init__(self, incident_id: str):
        self.incident_id = incident_id
        super().__init__("locked")


class CooldownError(DemoError):
    def __init__(self, until: float):
        self.until = until
        super().__init__("cooldown")


class NotHolderError(DemoError):
    pass


class WrongStageError(DemoError):
    pass


class NotFoundError(DemoError):
    pass


class HeldError(DemoError):
    pass


# ----------------------------------------------------------------- emitter

class Emitter:
    """Concrete StageEmitter — persists + publishes on every call."""

    def __init__(self, orch: "DemoOrchestrator", incident: Incident):
        self._orch = orch
        self.incident = incident

    async def save(self) -> None:
        await self._orch.store.put_incident(self.incident)
        await self._orch.hub.publish(
            "incident", incident_to_json(self.incident), incident_id=self.incident.id
        )

    async def stage_started(self, key: str) -> None:
        stage = self.incident.stage(key)
        stage.state = "active"
        if stage.started_at is None:
            stage.started_at = time.time()
        self.incident.stage_index = STAGE_KEYS.index(key)
        await self.save()

    async def stage_done(self, key: str) -> None:
        stage = self.incident.stage(key)
        stage.state = "done"
        if stage.started_at is None:
            stage.started_at = time.time()
        stage.done_at = time.time()
        await self.save()

    async def emit_receipt(self, stage_key: str, receipt: Receipt) -> None:
        self.incident.stage(stage_key).receipts.append(receipt)
        await self.save()

    async def set_medic(self, trace: MedicTrace) -> None:
        self.incident.medic = trace
        await self._orch.store.put_incident(self.incident)
        await self._orch.hub.publish(
            "medic", trace.model_dump(mode="json"), incident_id=self.incident.id
        )
        await self._orch.hub.publish(
            "incident", incident_to_json(self.incident), incident_id=self.incident.id
        )

    async def fail(self, reason: str, evidence: str = "") -> None:
        """Tie the incident off honestly: knot on the current stage, the rest
        skipped, lock released, cooldown started. The receipts stay."""
        inc = self.incident
        if inc.status != "live":
            return
        now = time.time()
        current = next(
            (s for s in inc.stages if s.state in ("pending", "active")),
            inc.stages[-1],
        )
        if current.started_at is None:
            current.started_at = now
        current.done_at = now
        current.state = "tied_off"
        current.receipts.append(
            KnotReceipt(reason=reason, evidence=evidence, label="Tied off")
        )
        past_current = False
        for s in inc.stages:
            if s is current:
                past_current = True
                continue
            if past_current and s.state == "pending":
                s.state = "skipped"
        inc.status = "tied_off"
        await self.save()
        await self._orch._finish(inc)


# ------------------------------------------------------------- orchestrator

class DemoOrchestrator:
    def __init__(
        self,
        store: Store,
        hub: SseHub,
        sabotage: SabotageBackend,
        pipeline: AgentPipeline,
    ):
        self.store = store
        self.hub = hub
        self.sabotage = sabotage
        self.pipeline = pipeline
        # Optional async callable returning the /api/state dict; set by main.
        self.state_provider: Optional[Callable[[], Awaitable[dict]]] = None

        self._live: Optional[Incident] = None
        self._presence: dict[str, dict[str, float]] = {}
        self._tear_gate = asyncio.Lock()
        self._pipeline_task: Optional[asyncio.Task] = None
        self._approve_task: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.Task] = None
        self._cooldown_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------- helpers

    async def get_incident(self, incident_id: str) -> Optional[Incident]:
        if self._live is not None and self._live.id == incident_id:
            return self._live
        return await self.store.get_incident(incident_id)

    async def _publish_incident(self, inc: Incident) -> None:
        await self.hub.publish(
            "incident", incident_to_json(inc), incident_id=inc.id
        )

    async def _publish_state(self) -> None:
        if self.state_provider is None:
            return
        try:
            state = await self.state_provider()
        except Exception:
            log.exception("state publish failed")
            return
        await self.hub.publish("state", state)

    @staticmethod
    def _cancel(task: Optional[asyncio.Task]) -> None:
        if task is not None and not task.done():
            task.cancel()

    # ------------------------------------------------------------------ tear

    async def tear(self, session: str, defect_key: str) -> Incident:
        if not defect_exists(defect_key):
            raise UnknownDefectError(defect_key)
        async with self._tear_gate:
            now = time.time()
            ds = await self.store.get_demo_state()
            if ds.lock.active and ds.lock.incident_id:
                raise LockedError(ds.lock.incident_id)
            if ds.cooldown.until is not None and ds.cooldown.until > now:
                raise CooldownError(ds.cooldown.until)

            # The real commit happens before anything locks: if GitHub is not
            # configured this raises NotConfiguredError and nothing changes.
            commit = await self.sabotage.commit_defect(defect_key)

            inc = Incident(
                kind="demo",
                defect_key=defect_key,
                title=defect_title(defect_key),
                service_name=settings.demo_service_name,
                repo=settings.github_repo,
                sabotage_sha=str(commit.get("sha") or "") or None,
                needle=Needle(holder_session=session, last_seen=now),
                watching=1,
            )
            detected = inc.stage("detected")
            detected.state = "active"
            detected.started_at = now
            inc.stage_index = 0
            sha = str(commit.get("sha") or "")[:7]
            message = str(commit.get("message") or "").strip()
            detected.receipts.append(
                NoteReceipt(
                    label="the bad commit",
                    text=f"commit {sha} pushed — {message}".strip(" —"),
                )
            )

            ds.lock.active = True
            ds.lock.incident_id = inc.id
            await self.store.put_incident(inc)
            await self.store.put_demo_state(ds)
            self._live = inc
            self._presence[inc.id] = {session: now}

            await self._publish_incident(inc)
            await self._publish_state()
            self._pipeline_task = asyncio.create_task(self._run_pipeline(inc.id))
            return inc

    # -------------------------------------------------------------- pipeline

    async def _run_pipeline(self, incident_id: str) -> None:
        inc = await self.get_incident(incident_id)
        if inc is None:
            return
        emitter = Emitter(self, inc)
        try:
            if inc.stage("detected").state != "done":
                await self.pipeline.run_detect(inc, emitter)
            if inc.status != "live":
                return
            if inc.stage("detected").state != "done":
                # The pipeline returned without detecting. Stay honest: the
                # stage keeps waiting; nothing is fabricated.
                log.warning("run_detect returned without completing detection")
                return
            if inc.stage("pr_open").state != "done":
                await self.pipeline.run_diagnose_fix_pr(inc, emitter)
            if inc.status != "live":
                return
            pr_stage = inc.stage("pr_open")
            if pr_stage.state == "done" and inc.stage("approved").state == "pending":
                # The oversight beat: the PR is open and a human holds the
                # needle. Stage 5 is the CURRENT stage now (live strip says
                # "stage 5 of 6", the approve panel is the expanded card).
                approved = inc.stage("approved")
                approved.state = "active"
                approved.started_at = time.time()
                inc.stage_index = STAGE_KEYS.index("approved")
                await emitter.save()
                await self._publish_state()
                deadline = (pr_stage.done_at or time.time()) + float(
                    settings.approve_timeout_seconds
                )
                self._schedule_approve_timeout(inc.id, deadline)
        except asyncio.CancelledError:
            raise
        except NotConfiguredError as e:
            await emitter.fail(
                "a required integration is not configured",
                evidence=", ".join(e.missing),
            )
        except Exception as e:
            log.exception("agent pipeline failed")
            await emitter.fail(f"the agent hit an error: {e}")

    # ------------------------------------------------------------- presence

    async def presence(self, session: str, incident_id: str) -> dict:
        inc = await self.get_incident(incident_id)
        if inc is None:
            raise NotFoundError(incident_id)
        now = time.time()
        watchers = self._presence.setdefault(incident_id, {})
        watchers[session] = now
        cutoff = now - PRESENCE_WINDOW_S
        for sid, seen in list(watchers.items()):
            if seen < cutoff:
                del watchers[sid]
        watching = len(watchers)
        count_changed = watching != inc.watching
        inc.watching = watching

        needle_changed = False
        holder_heartbeat = False
        if inc.status == "live" and inc.needle is not None:
            if inc.needle.holder_session == session:
                inc.needle.last_seen = now
                holder_heartbeat = True
            elif (
                inc.needle.holder_session is not None
                and inc.needle.last_seen is not None
                and now - inc.needle.last_seen
                > float(settings.needle_lapse_seconds)
            ):
                # The holder walked away; the needle is free for pickup.
                inc.needle.holder_session = None
                needle_changed = True

        if inc.status == "live" and (
            count_changed or needle_changed or holder_heartbeat
        ):
            await self.store.put_incident(inc)
        if count_changed:
            await self.hub.publish(
                "presence",
                {"incident_id": incident_id, "watching": watching},
                incident_id=incident_id,
            )
        if needle_changed:
            await self._publish_incident(inc)

        holder = bool(inc.needle and inc.needle.holder_session == session)
        can_pickup = (
            inc.status == "live"
            and inc.needle is not None
            and inc.needle.holder_session is None
            and not holder
        )
        label = inc.needle.holder_label if inc.needle else "the needle-holder"
        return {
            "watching": watching,
            "holder": holder,
            "holder_label": label,
            "can_pickup": can_pickup,
        }

    async def pickup(self, session: str, incident_id: str) -> dict:
        inc = await self.get_incident(incident_id)
        if inc is None:
            raise NotFoundError(incident_id)
        if inc.status != "live":
            raise WrongStageError()
        now = time.time()
        if inc.needle is None:
            inc.needle = Needle()
        if inc.needle.holder_session == session:
            return {"holder": True}
        lapsed = (
            inc.needle.last_seen is not None
            and now - inc.needle.last_seen > float(settings.needle_lapse_seconds)
        )
        if inc.needle.holder_session is not None and not lapsed:
            raise HeldError()
        inc.needle.holder_session = session
        inc.needle.last_seen = now
        await self.store.put_incident(inc)
        await self._publish_incident(inc)
        return {"holder": True}

    # -------------------------------------------------------------- approve

    def _require_holder(self, inc: Incident, session: str) -> None:
        now = time.time()
        if (
            inc.needle is not None
            and inc.needle.holder_session is not None
            and inc.needle.last_seen is not None
            and now - inc.needle.last_seen > float(settings.needle_lapse_seconds)
        ):
            inc.needle.holder_session = None
        if inc.needle is None or inc.needle.holder_session != session:
            raise NotHolderError()

    @staticmethod
    def _approval_given(inc: Incident) -> bool:
        return any(
            getattr(r, "type", "") == "approval"
            for r in inc.stage("approved").receipts
        )

    @classmethod
    def _require_approve_window(cls, inc: Incident) -> None:
        if inc.status != "live":
            raise WrongStageError()
        if (
            inc.stage("pr_open").state != "done"
            or inc.stage("approved").state not in ("pending", "active")
            or cls._approval_given(inc)
        ):
            raise WrongStageError()

    async def approve(self, session: str, incident_id: str) -> None:
        inc = await self.get_incident(incident_id)
        if inc is None:
            raise NotFoundError(incident_id)
        if inc.status != "live":
            raise WrongStageError()
        self._require_holder(inc, session)
        self._require_approve_window(inc)
        self._cancel(self._timeout_task)
        approved = inc.stage("approved")
        approved.state = "active"
        if approved.started_at is None:
            approved.started_at = time.time()
        inc.stage_index = STAGE_KEYS.index("approved")
        await self.store.put_incident(inc)
        await self._publish_incident(inc)
        self._approve_task = asyncio.create_task(self._approve_flow(inc))

    async def _approve_flow(self, inc: Incident, *, skip_merge: bool = False) -> None:
        emitter = Emitter(self, inc)
        try:
            approved = inc.stage("approved")
            if approved.state != "done":
                if not skip_merge:
                    try:
                        await self.sabotage.merge_pr(inc)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        await emitter.fail(f"merging the PR failed: {e}")
                        return
                label = inc.needle.holder_label if inc.needle else "the needle-holder"
                approved.receipts.append(ApprovalReceipt(by=label, label="approved"))
                approved.state = "done"
                approved.done_at = time.time()
                await emitter.save()
            try:
                await self.pipeline.run_verify(inc, emitter)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("verification failed")
                await emitter.fail(f"verification failed: {e}")
                return
            if inc.status != "live":
                return  # the pipeline tied it off
            if inc.stage("verified").state != "done":
                await emitter.fail("verification did not complete")
                return
            inc.status = "verified_closed"
            inc.wall_clock_summary = self._summary(inc)
            await self._finish(inc)
        except asyncio.CancelledError:
            raise

    # -------------------------------------------------------------- decline

    async def decline(self, session: str, incident_id: str) -> None:
        inc = await self.get_incident(incident_id)
        if inc is None:
            raise NotFoundError(incident_id)
        if inc.status != "live":
            raise WrongStageError()
        self._require_holder(inc, session)
        self._require_approve_window(inc)
        self._cancel(self._timeout_task)
        await self._close_out(
            inc,
            status="declined_reverted",
            note="Declined — PR closed, bad commit reverted. The receipts stay.",
        )

    async def _close_out(self, inc: Incident, status: str, note: str) -> None:
        now = time.time()
        approved = inc.stage("approved")
        if approved.started_at is None:
            approved.started_at = now
        approved.done_at = now
        approved.state = "tied_off"
        approved.receipts.append(NoteReceipt(text=note, label="declined"))
        verified = inc.stage("verified")
        if verified.state == "pending":
            verified.state = "skipped"
        try:
            await self.sabotage.close_pr(inc)
            revert_sha = await self.sabotage.revert(inc)
            approved.receipts.append(
                NoteReceipt(
                    text=f"bad commit reverted — revert {str(revert_sha)[:7]}",
                    label="revert",
                )
            )
        except asyncio.CancelledError:
            raise
        except NotConfiguredError:
            pass  # nothing real to tidy on an unconfigured deployment
        except Exception as e:
            log.exception("decline tidy-up failed")
            approved.receipts.append(
                NoteReceipt(text=f"tidy-up hit an error: {e}", label="revert")
            )
        inc.status = status  # type: ignore[assignment]
        await self._finish(inc)

    # -------------------------------------------------------------- timers

    def _schedule_approve_timeout(self, incident_id: str, deadline: float) -> None:
        self._cancel(self._timeout_task)
        delay = max(0.0, deadline - time.time())
        self._timeout_task = asyncio.create_task(
            self._approve_timeout(incident_id, delay)
        )

    async def _approve_timeout(self, incident_id: str, delay: float) -> None:
        await asyncio.sleep(delay)
        inc = await self.get_incident(incident_id)
        if inc is None or inc.status != "live":
            return
        if (
            inc.stage("pr_open").state != "done"
            or inc.stage("approved").state not in ("pending", "active")
            or self._approval_given(inc)
        ):
            return
        log.info("approve window expired for %s — auto-declining", incident_id)
        await self._close_out(
            inc,
            status="declined_timeout",
            note=(
                "No approval within the window — PR closed, bad commit reverted. "
                "The receipts stay."
            ),
        )

    async def _cooldown_watch(self, until: float) -> None:
        await asyncio.sleep(max(0.0, until - time.time()))
        await self.hub.publish("cooldown", {"until": None})
        await self._publish_state()

    # -------------------------------------------------------------- finish

    def _summary(self, inc: Incident) -> WallClockSummary:
        detected = inc.stage("detected")
        pr_open = inc.stage("pr_open")
        approved = inc.stage("approved")
        verified = inc.stage("verified")
        s = WallClockSummary()
        if detected.done_at is not None and pr_open.done_at is not None:
            s.detected_to_pr_s = pr_open.done_at - detected.done_at
        # "approved → verified closed" counts from the human's approval, not
        # from when the approve window opened.
        approved_at = next(
            (
                getattr(r, "at", None)
                for r in approved.receipts
                if getattr(r, "type", "") == "approval"
            ),
            approved.done_at,
        )
        if approved_at is not None and verified.done_at is not None:
            s.approved_to_verified_s = verified.done_at - approved_at
        s.dql_receipts = sum(
            1
            for stage in inc.stages
            for r in stage.receipts
            if getattr(r, "type", "") == "dql"
        )
        if inc.medic is not None:
            s.token_cost_usd = inc.medic.cost_usd
        return s

    async def _finish(self, inc: Incident) -> None:
        """Common epilogue: release the lock, start the cooldown, persist,
        publish. Runs for verified, declined, timeout and tied-off ends."""
        self._cancel(self._timeout_task)
        now = time.time()
        if inc.ended_at is None:
            inc.ended_at = now
        ds = await self.store.get_demo_state()
        ds.lock.active = False
        ds.lock.incident_id = None
        until = now + float(settings.cooldown_seconds)
        ds.cooldown.until = until
        if inc.status == "verified_closed":
            ds.last_mend = summarize(inc)
        await self.store.put_demo_state(ds)
        await self.store.put_incident(inc)
        if self._live is not None and self._live.id == inc.id:
            self._live = None
        await self._publish_incident(inc)
        await self.hub.publish("cooldown", {"until": until})
        await self._publish_state()
        self._cancel(self._cooldown_task)
        self._cooldown_task = asyncio.create_task(self._cooldown_watch(until))

    # -------------------------------------------------------------- resume

    async def resume(self) -> None:
        """Boot-time recovery: reload the live incident and restart its timers."""
        ds = await self.store.get_demo_state()
        inc = await self.store.get_live_incident()
        now = time.time()
        if inc is None:
            if ds.lock.active:
                ds.lock.active = False
                ds.lock.incident_id = None
                await self.store.put_demo_state(ds)
                log.info("released a stale demo lock at boot")
            if ds.cooldown.until is not None and ds.cooldown.until > now:
                self._cooldown_task = asyncio.create_task(
                    self._cooldown_watch(ds.cooldown.until)
                )
            return

        self._live = inc
        self._presence.setdefault(inc.id, {})
        if not ds.lock.active or ds.lock.incident_id != inc.id:
            ds.lock.active = True
            ds.lock.incident_id = inc.id
            await self.store.put_demo_state(ds)

        approved = inc.stage("approved")
        pr_open = inc.stage("pr_open")
        verified = inc.stage("verified")
        if approved.state == "done" and verified.state != "done":
            log.info("resuming %s at verification", inc.id)
            self._approve_task = asyncio.create_task(
                self._approve_flow(inc, skip_merge=True)
            )
        elif approved.state == "active" and self._approval_given(inc):
            log.info("resuming %s mid-approval", inc.id)
            self._approve_task = asyncio.create_task(self._approve_flow(inc))
        elif pr_open.state == "done" and approved.state in ("pending", "active"):
            deadline = (pr_open.done_at or now) + float(
                settings.approve_timeout_seconds
            )
            log.info("resuming %s in the approve window", inc.id)
            self._schedule_approve_timeout(inc.id, deadline)
        else:
            log.info("resuming %s in the agent pipeline", inc.id)
            self._pipeline_task = asyncio.create_task(self._run_pipeline(inc.id))

    async def shutdown(self) -> None:
        for task in (
            self._pipeline_task,
            self._approve_task,
            self._timeout_task,
            self._cooldown_task,
        ):
            self._cancel(task)
