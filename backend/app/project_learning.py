"""Durable rolling discovery shared by desktop and CLI completion handling."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import uuid4

from app.skill_learning.models import SkillCandidateStatus, SkillCandidateAction
from app.skill_learning.service import SkillLearningOutcome, _to_card
from app.skill_learning.store import InflightBatch
from app.task import TaskStatus

logger = logging.getLogger(__name__)


def skill_version(skill):
    return hashlib.sha256(skill.metadata.location.read_bytes()).hexdigest()


async def prepare_candidate(service, candidate, *, conversation_id=None, workflow_key=None, snapshot=None):
    updates = {"project_id": getattr(service, "project_id", None),
               "source_conversation_id": conversation_id or candidate.source_conversation_id,
               "workflow_key": workflow_key or candidate.workflow_key}
    if candidate.action == SkillCandidateAction.UPDATE:
        target = await (snapshot or service.skill_store).load(candidate.existing_skill_name)
        if target is None:
            raise ValueError("更新目标不存在")
        updates.update(scope=target.metadata.scope.value, target_version=(snapshot.versions[target.metadata.name] if snapshot else skill_version(target)))
    return candidate.model_copy(update=updates)


async def mine_project(service):
    lock = getattr(service, "_mining_lock", None)
    if lock is None:
        service._mining_lock = lock = asyncio.Lock()
    async with lock:
        if not service.settings.skill_learning_enabled:
            return SkillLearningOutcome(skipped_reason="disabled")
        tasks = await service.task_store.list(status=TaskStatus.COMPLETED, limit=50)
        # A task_update may precede trace persistence while its Run is still active.
        # Leave those tasks eligible for the completion wakeup instead of marking
        # an evidence-less window as scanned forever.
        run_store = getattr(service, "run_store", None)
        if run_store:
            ready = []
            for task in tasks:
                latest_run = await run_store.get(task.run_ids[-1]) if task.run_ids else None
                if latest_run is None or latest_run.status.value not in {"running", "pending"}:
                    ready.append(task)
            tasks = tuple(ready)
        ids = tuple(t.id for t in tasks)
        watermark = await service.candidate_store.load_watermark()
        if len(ids) < 5:
            return SkillLearningOutcome(skipped_reason="not_enough_tasks", pending_count=len(ids))
        if set(ids) == set(watermark.processed_task_ids) and watermark.inflight is None:
            return SkillLearningOutcome(skipped_reason="unchanged")
        inflight = watermark.inflight
        if inflight and set(inflight.task_ids) == set(ids):
            if inflight.attempt >= service.settings.skill_learning_max_attempts:
                return SkillLearningOutcome(skipped_reason="retry_exhausted", error=inflight.last_error)
        else:
            inflight = InflightBatch(batch_id=uuid4().hex, task_ids=ids, started_at=datetime.now(UTC))
        await service.candidate_store.save_watermark(watermark.model_copy(update={"inflight": inflight}))
        created = 0
        try:
            mining = await service.miner.mine(tuple(_to_card(t) for t in tasks))
            if mining.error:
                raise RuntimeError(mining.error)
            by_id = {t.id: t for t in tasks}
            existing = await service.candidate_store.list()
            from app.skills.snapshot import SkillSnapshot
            snapshot = await SkillSnapshot.capture(service.skill_store)
            catalog = await snapshot.catalog()
            for cluster in mining.clusters:
                cluster_ids = set(cluster.task_ids)
                if len(cluster_ids) < 5 or not cluster_ids <= set(ids):
                    continue
                key = " ".join(cluster.id.casefold().split())
                if any((cluster_ids <= set(c.source_task_ids) and c.status != SkillCandidateStatus.REJECTED)
                       or (c.workflow_key == key and (c.status == SkillCandidateStatus.PENDING or c.suppressed))
                       or (c.suppressed and len(cluster_ids & set(c.source_task_ids)) >= 5)
                       for c in existing):
                    continue
                evidence, run_ids = {}, {}
                for identifier in cluster.task_ids:
                    task = by_id[identifier]
                    events = await service._load_task_events(task)
                    # A completed label alone is not execution evidence.
                    successful_execution = any(getattr(e, "tool_result", None)
                        and e.tool_result.success and getattr(e, "tool_call", None)
                        and not e.tool_call.name.startswith(("task_", "memory_", "core_memory_", "skill_")) for e in events)
                    if not successful_execution or not task.run_ids:
                        break
                    evidence[identifier] = service.evidence_builder.build(task, events)
                    run_ids[identifier] = task.run_ids
                if len(evidence) < 5:
                    continue
                outcome = await service.distiller.distill(cluster, evidence=evidence, run_ids=run_ids,
                            catalog=catalog, pending_candidates=tuple(c for c in existing if c.status == SkillCandidateStatus.PENDING),
                            skill_loader=snapshot.load)
                if outcome.error:
                    raise RuntimeError(outcome.error)
                if outcome.candidate is None:
                    continue
                candidate = await prepare_candidate(service, outcome.candidate,
                                 conversation_id=tasks[0].owner_conversation_id, workflow_key=key, snapshot=snapshot)
                if any(c.proposed_name == candidate.proposed_name and
                       (c.status == SkillCandidateStatus.PENDING or c.suppressed) for c in existing):
                    continue
                async with getattr(service, "review_lock", nullcontext()):
                    if not service.settings.skill_learning_enabled:
                        return SkillLearningOutcome(skipped_reason="disabled", candidate_count=created)
                    # Human rejection/deletion or another manual draft may have
                    # occurred while the distillation model was running.
                    latest = await service.candidate_store.list()
                    if any((c.workflow_key == key and (c.status == SkillCandidateStatus.PENDING or c.suppressed))
                           or (c.suppressed and len(cluster_ids & set(c.source_task_ids)) >= 5)
                           or (c.proposed_name == candidate.proposed_name and (c.status == SkillCandidateStatus.PENDING or c.suppressed))
                           for c in latest):
                        continue
                    await service.candidate_store.create(candidate)
                existing += (candidate,)
                created += 1
            await service.candidate_store.save_watermark(watermark.model_copy(update={
                "processed_task_ids": ids, "pending_task_ids": (), "inflight": None,
                "last_error": None, "last_mining_at": datetime.now(UTC)}))
            return SkillLearningOutcome(triggered=True, scanned_task_count=len(ids), candidate_count=created)
        except Exception as exc:
            await service.candidate_store.save_watermark(watermark.model_copy(update={
                "inflight": inflight.model_copy(update={"attempt": inflight.attempt + 1, "last_error": str(exc)}),
                "last_error": str(exc), "last_mining_at": datetime.now(UTC)}))
            logger.warning("Project %s discovery failed: %s", service.project_id, exc)
            return SkillLearningOutcome(triggered=True, candidate_count=created, error=str(exc))


class ProjectLearningWorker:
    def __init__(self, application):
        self.app = application
        self.wake = asyncio.Event()
        self.job = None
        self.settings_path = application.database.parent / "learning-settings.json"
        self.enabled = application.skill_learning.settings.skill_learning_enabled
        if self.settings_path.exists():
            self.enabled = json.loads(self.settings_path.read_text(encoding="utf-8")).get("enabled", self.enabled)

    def start(self):
        self.job = asyncio.create_task(self._loop())

    async def completed(self, run, *, core_generation=None):
        self.wake.set()
        if self.app.memory_reflection_enabled:
            from app.memory.preferences import extract_preferences
            generation = self.app.memory_manager.core.manual_generation if core_generation is None else core_generation
            self.app.post_run_processor.submit(lambda: extract_preferences(self.app, run, generation))

    async def set_enabled(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        temporary = self.settings_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
        temporary.replace(self.settings_path)
        self.enabled = enabled
        for service in self.app.project_services._services.values():
            service.learning.settings.skill_learning_enabled = enabled
        self.wake.set()

    async def _loop(self):
        while True:
            try:
                self.wake.clear()
                for project in await self.app.projects.list():
                    service = await self.app.project_services.get(project.id)
                    service.learning.settings.skill_learning_enabled = self.enabled
                    outcome = await service.learning.maybe_run_mining()
                    notify = getattr(self.app, "change_broadcaster", None)
                    if outcome.candidate_count and notify:
                        await notify("skill_learning.changed", {"project_id": project.id})
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background discovery iteration failed")
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=30)
            except TimeoutError:
                pass

    async def close(self):
        if self.job:
            self.job.cancel()
            try:
                await self.job
            except asyncio.CancelledError:
                pass
