"""Project, memory management and persisted Skill review APIs."""
from __future__ import annotations
import asyncio
import difflib
from functools import wraps
from app.project_learning import skill_version
from app.skill_learning.models import SkillCandidate, SkillCandidateStatus
from app.skill_learning.service import _render_candidate_body
from app.skills import SkillScope
from app.skills.store import _render_skill_document, render_skill_update
from ..protocol import JsonRpcError, INVALID_STATE, RESOURCE_NOT_FOUND


def guarded(method):
    @wraps(method)
    async def wrapper(params, ctx):
        try:
            return await method(params, ctx)
        except KeyError as exc:
            raise JsonRpcError(RESOURCE_NOT_FOUND, str(exc)) from exc
        except (ValueError, TypeError, OSError) as exc:
            raise JsonRpcError(INVALID_STATE, str(exc)) from exc
    return wrapper


async def services(params, ctx):
    app = ctx.application
    identifier = params.get("project_id")
    if identifier is None and params.get("task_id"):
        task = await app.task_store.get(params["task_id"])
        if task:
            identifier = task.project_id
    if identifier is None and params.get("candidate_id"):
        for project in await app.projects.list():
            service = await app.project_services.get(project.id)
            if await service.learning.get_candidate(params["candidate_id"]):
                identifier = project.id
                break
    return await app.project_services.get(identifier)


async def notify(ctx, method, params):
    callback = getattr(ctx.application, "change_broadcaster", None)
    if callback:
        try:
            await callback(method, params)
        except Exception:
            pass


def skill_lock(ctx):
    app = ctx.application
    if not hasattr(app, "_skill_mutation_lock"):
        app._skill_mutation_lock = asyncio.Lock()
    return app._skill_mutation_lock


@guarded
async def project_list(params, ctx):
    return {"projects": await ctx.application.projects.list(), "default_project_id": ctx.application.projects.default_id}


@guarded
async def project_register(params, ctx):
    return {"project": await ctx.application.projects.register(params["path"])}


@guarded
async def memory_edit(params, ctx):
    service = await services(params, ctx)
    manager = service.memory
    if params.get("scope", "project") not in {"user", "project"}:
        raise ValueError("无效记忆作用域")
    if params.get("scope") == "user":
        expected = params["expected_version"]
        if params.get("action") == "edit_legacy":
            await manager.core.edit_legacy(params["value"], expected_version=expected)
            manager.core.manual_generation += 1
            await notify(ctx, "memory.changed", {"scope": "user", "id": "legacy", "project_id": service.project.id})
            return {"entry": None}
        if params.get("action") == "delete":
            if params.get("confirmed") is not True:
                raise ValueError("删除用户偏好需要确认")
            result = await manager.core.remove(params["key"], expected_version=expected)
        else:
            result, _ = await manager.core.upsert(key=params["key"], value=params["value"],
                reason="用户在记忆设置中编辑", source_statement=params["value"], expected_version=expected)
        manager.core.manual_generation += 1
        await notify(ctx, "memory.changed", {"scope": "user", "id": result.key, "project_id": service.project.id})
    else:
        manager.manual_generation += 1
        if params.get("action", "edit") == "edit":
            result = await manager.update_if_revision(params["memory_id"], expected_revision=params["expected_revision"],
                title=params["title"], summary=params["summary"], content=params["content"], reason="用户手动编辑")
        else:
            if params["action"] == "delete" and params.get("confirmed") is not True:
                raise ValueError("删除记忆需要确认")
            result = await manager.manage(params["memory_id"], action=params["action"], expected_revision=params["expected_revision"])
    return {"entry": result}


@guarded
async def learning_list(params, ctx):
    service = await services(params, ctx)
    candidates = await service.learning.list_candidates()
    conversation_id = params.get("conversation_id")
    if conversation_id:
        conversation = await ctx.application.conversation_store.get(conversation_id)
        if not conversation or conversation.project_id != service.project.id:
            raise ValueError("会话不属于当前项目")
        candidates = tuple(c for c in candidates if c.source_conversation_id == conversation_id)
    return {"candidates": candidates, "enabled": ctx.application.learning_worker.enabled,
            "scan": await service.learning.candidate_store.load_watermark()}


@guarded
async def learning_get(params, ctx):
    service = await services(params, ctx)
    candidate = await service.learning.get_candidate(params["candidate_id"])
    if candidate is None:
        raise KeyError("候选不存在")
    if params.get("draft"):
        draft = params["draft"]
        candidate = SkillCandidate.model_validate(candidate.model_dump() | {
            key: draft[key] for key in ("proposed_name", "description", "procedure", "pitfalls", "verification") if key in draft})
    body = _render_candidate_body(candidate)
    markdown = _render_skill_document(candidate.proposed_name, candidate.description, body)
    diff = ""
    if candidate.existing_skill_name:
        skill = await service.skills.load_managed(candidate.existing_skill_name, SkillScope(candidate.scope))
        if skill:
            markdown = render_skill_update(skill, candidate.description, body)
            diff = "\n".join(difflib.unified_diff(skill.metadata.location.read_text(encoding="utf-8").splitlines(),
                            markdown.splitlines(), fromfile="当前版本", tofile="候选版本", lineterm=""))
    tasks = [await service.tasks.get(identifier) for identifier in candidate.source_task_ids]
    return {"candidate": candidate, "markdown": markdown, "diff": diff, "tasks": [t for t in tasks if t]}


@guarded
async def learning_edit(params, ctx):
    async with skill_lock(ctx):
        service = await services(params, ctx)
        candidate = await service.learning.get_candidate(params["candidate_id"])
        if candidate is None:
            raise KeyError("候选不存在")
        if candidate.revision != params["expected_revision"]:
            raise ValueError("草稿版本冲突，请刷新后重试")
        action = params.get("action", "edit")
        changes = {"revision": candidate.revision + 1}
        if action == "dismiss":
            changes["dismissed"] = True
        elif action == "restore_recommendation":
            changes["suppressed"] = False
            watermark = await service.learning.candidate_store.load_watermark()
            await service.learning.candidate_store.save_watermark(watermark.model_copy(update={"processed_task_ids": (), "inflight": None}))
        elif action == "edit":
            if candidate.status != SkillCandidateStatus.PENDING:
                raise ValueError("只能编辑待审核草稿")
            for key in ("proposed_name", "description", "procedure", "pitfalls", "verification", "scope"):
                if key in params:
                    changes[key] = params[key]
            if changes.get("scope", candidate.scope) not in {"project", "user"}:
                raise ValueError("无效 Skill 作用域")
        else:
            raise ValueError("无效候选操作")
        candidate = SkillCandidate.model_validate(candidate.model_dump() | changes)
        await service.learning.candidate_store.update(candidate)
        await notify(ctx, "skill_learning.changed", {"project_id": service.project.id})
        return {"candidate": candidate}


@guarded
async def learning_settings(params, ctx):
    if "enabled" in params:
        async with skill_lock(ctx):
            await ctx.application.learning_worker.set_enabled(params["enabled"])
    if params.get("retry") is True:
        service = await services(params, ctx)
        watermark = await service.learning.candidate_store.load_watermark()
        await service.learning.candidate_store.save_watermark(watermark.model_copy(update={
            "inflight": None, "processed_task_ids": (), "last_error": None}))
        ctx.application.learning_worker.wake.set()
    return {"enabled": ctx.application.learning_worker.enabled}


@guarded
async def skill_get(params, ctx):
    service = await services(params, ctx)
    skill = await service.skills.load_managed(params["name"], SkillScope(params["scope"]), params.get("enabled", True))
    if skill is None:
        raise KeyError("Skill 不存在")
    return {"skill": skill, "version": skill_version(skill)}


@guarded
async def skill_update(params, ctx):
    async with skill_lock(ctx):
        service = await services(params, ctx)
        scope = SkillScope(params["scope"])
        skill = await service.skills.load_managed(params["name"], scope, params.get("enabled", True))
        if skill is None:
            raise KeyError("Skill 不存在")
        if skill_version(skill) != params["expected_version"]:
            raise ValueError("Skill 版本冲突，请刷新后重试")
        updated = await service.skills.update(name=params["name"], description=params["description"],
                   instructions=params["instructions"], scope=scope, enabled=params.get("enabled", True))
        await notify(ctx, "skill_learning.changed", {"project_id": service.project.id})
        return {"skill": updated, "version": skill_version(updated)}


def register(dispatcher):
    for name, handler in (("project.list", project_list), ("project.register", project_register),
            ("memory.edit", memory_edit), ("skill_learning.list", learning_list),
            ("skill_learning.get", learning_get), ("skill_learning.edit", learning_edit),
            ("skill_learning.settings", learning_settings), ("skill.get", skill_get), ("skill.update", skill_update)):
        dispatcher.register(name, handler)
