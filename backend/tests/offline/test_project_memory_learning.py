"""Offline acceptance tests for scoped runtimes and persisted human review."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import json
import pytest
from pydantic import SecretStr

from app.application import Application
from app.models.adapter import ModelAdapter
from app.models.config import ModelSettings, ProviderConfig
from app.models.registry import ModelAdapterRegistry
from app.models.types import ApiStyle, Message, MessageRole, ModelResponse, ToolCall, ToolResult
from app.memory import MemoryReflectionConfig, MemoryMaintenanceConfig
from app.skill_learning import SkillLearningSettings, SkillCandidate, SkillCandidateOrigin, SkillCandidateAction
from app.skill_learning.models import TaskPatternCluster
from app.skill_learning.miner import PatternMiningOutcome
from app.skill_learning.distiller import DistillationOutcome
from app.task import TaskStatus
from app.skills import SkillScope
from app.skills.snapshot import SkillSnapshot
from app.project_learning import prepare_candidate
from app.server.rpc.methods import project_flows, memories, skill_learning
from app.server.rpc.protocol import JsonRpcError


class Fake(ModelAdapter):
    async def complete(self, request):
        return ModelResponse(id="fake", provider="fake", model="fake-model",
            message=Message(role=MessageRole.ASSISTANT, content="完成"))
    async def close(self):
        pass


def application(path):
    config = ProviderConfig(provider="fake", model="fake-model", api_key=SecretStr("offline"), api_style=ApiStyle.CHAT_COMPLETIONS)
    registry = ModelAdapterRegistry(ModelSettings(_env_file=None))
    adapter = Fake(config)
    registry.register("fake", lambda _: adapter, config=config)
    return Application(provider="fake", model="fake-model", registry=registry,
        database=path / "pluto.db", tasks_dir=path / "tasks", memory_dir=path / "memory",
        mcp_config=path / "mcp.json", workspace_root=path, skills_user_dir=path / "user-skills",
        skills_project_dir=path / "project-skills",
        memory_reflection_config=MemoryReflectionConfig(_env_file=None, enabled=False),
        memory_maintenance_config=MemoryMaintenanceConfig(_env_file=None, enabled=False),
        skill_learning_settings=SkillLearningSettings(_env_file=None, skill_learning_enabled=False, skill_learning_data_dir=path / "learning"))


@pytest.fixture
async def app(tmp_path):
    instance = application(tmp_path)
    await instance.start()
    await instance.learning_worker.close()
    yield instance
    await instance.close()


def candidate(**overrides):
    values = dict(id="a" * 32, origin=SkillCandidateOrigin.PATTERN_MINING, action=SkillCandidateAction.CREATE,
        proposed_name="api-check", description="检查接口", reason="五个任务验证了同一流程", procedure=("读取接口定义", "发送请求", "验证业务结果"),
        verification=("响应满足约定",), source_task_ids=("1" * 32,), created_at=datetime.now(UTC))
    return SkillCandidate(**(values | overrides))


async def second_project(app, path):
    path.mkdir()
    project = await app.projects.register(str(path))
    return project, await app.project_services.get(project.id)


@pytest.mark.asyncio
async def test_project_path_identity_and_runtime_isolation(app, tmp_path):
    a = await app.project_services.get()
    b_project, b = await second_project(app, tmp_path / "b")
    again = await app.projects.register(str(tmp_path / "b" / ".." / "b"))
    assert again.id == b_project.id
    c_a = await app.conversation_store.create()
    c_b = await app.conversation_store.create(project_id=b_project.id)
    record = await a.memory.create(title="A 接口", summary="A 项目约定", content="A 的接口只能在 A 召回")
    await a.memory.upsert_core(key="communication.language", value="中文", reason="用户明确要求", source_statement="以后默认使用中文")
    assert await b.memory.read(record.id) is None
    assert "中文" in await b.memory.core.load()
    assert c_a.project_id == a.project.id and c_b.project_id == b_project.id
    tasks = await asyncio.gather(a.tasks.create(title="A 任务", owner_conversation_id=c_a.id), b.tasks.create(title="B 任务", owner_conversation_id=c_b.id))
    assert [t.project_id for t in tasks] == [a.project.id, b_project.id]
    assert await b.tasks.get(tasks[0].id) is None
    runtimes = await asyncio.gather(app.project_services.runtime(a.project.id), app.project_services.runtime(b_project.id))
    assert runtimes[0].tool_executor is not runtimes[1].tool_executor
    # Scoped filesystem tool actually reads the respective working directory.
    for root, value in ((tmp_path, "A"), (tmp_path / "b", "B")):
        (root / "scope.txt").write_text(value, encoding="utf-8")
    for runtime, value in zip(runtimes, ("A", "B")):
        registry = runtime._loop._tool_registry
        tool = registry.get("file_read") if "file_read" in registry.names() else registry.get("read_file")
        output = await tool.execute({"path": "scope.txt"})
        assert value in str(output)
    dispatch = await app.conversation_service.dispatch(conversation_id=c_b.id, content="你好")
    assert dispatch.run.project_id == b_project.id


@pytest.mark.asyncio
async def test_memory_edits_conflicts_archive_restore_capacity(app):
    service = await app.project_services.get()
    ctx = SimpleNamespace(application=app)
    record = await service.memory.create(title="接口", summary="摘要", content="原约定")
    params = {"project_id": service.project.id, "scope": "project", "memory_id": record.id,
              "expected_revision": record.revision, "title": "接口", "summary": "新摘要", "content": "用户新约定"}
    result = await project_flows.memory_edit(params, ctx)
    with pytest.raises(JsonRpcError, match="conflict"):
        await project_flows.memory_edit(params, ctx)
    archived = await service.memory.manage(record.id, action="archive", expected_revision=result["entry"].revision)
    assert await service.memory.read(record.id) is None
    service.memory.max_active = 1
    await service.memory.create(title="另一接口", summary="另一摘要", content="约定")
    with pytest.raises(ValueError, match="容量"):
        await service.memory.manage(record.id, action="restore", expected_revision=archived.revision)
    active = (await service.memory.list())[0]
    await service.memory.manage(active.id, action="delete", expected_revision=active.revision)
    restored = await service.memory.manage(record.id, action="restore", expected_revision=archived.revision)
    assert restored.revision > archived.revision
    assert (service.memory.memory_dir / "deleted" / f"{active.id}.md").is_file()
    core = await memories.memory_list({}, ctx)
    await project_flows.memory_edit({"scope": "user", "key": "communication.language", "value": "中文", "expected_version": core["core_version"]}, ctx)
    with pytest.raises(JsonRpcError, match="版本冲突"):
        await project_flows.memory_edit({"scope": "user", "key": "communication.language", "value": "英文", "expected_version": core["core_version"]}, ctx)


@pytest.mark.asyncio
async def test_draft_gate_edit_accept_scope_and_conflicts(app):
    service = await app.project_services.get()
    ctx = SimpleNamespace(application=app)
    await service.learning.candidate_store.create(candidate(project_id=service.project.id))
    assert not await service.skills.catalog()
    edited = (await project_flows.learning_edit({"candidate_id": "a" * 32, "project_id": service.project.id,
        "expected_revision": 1, "proposed_name": "api-check", "description": "修改后的用途", "scope": "user"}, ctx))["candidate"]
    await skill_learning.skill_learning_accept({"candidate_id": edited.id, "project_id": service.project.id,
        "expected_revision": edited.revision, "scope": "user", "confirmed": True}, ctx)
    installed = await service.skills.load_managed("api-check", SkillScope.USER)
    assert installed.metadata.description == "修改后的用途"
    assert service.skills.origin("api-check", SkillScope.USER) == "automatic"
    snapshot = await SkillSnapshot.capture(service.skills)
    update = await prepare_candidate(service.learning, candidate(id="b" * 32, action=SkillCandidateAction.UPDATE,
        existing_skill_name="api-check"), snapshot=snapshot)
    await service.learning.candidate_store.create(update)
    await service.skills.update(name="api-check", scope=SkillScope.USER, description="人工较新版本", instructions="新流程")
    with pytest.raises(ValueError, match="已被修改"):
        await service.learning.accept(update.id, scope="user")
    assert (await snapshot.load("api-check")).metadata.description == "修改后的用途"
    assert (await service.skills.load("api-check")).metadata.description == "人工较新版本"


@pytest.mark.asyncio
async def test_same_named_user_and_project_skills_edit_correct_target(app):
    skills = (await app.project_services.get()).skills
    await skills.install(name="shared-name", description="用户", instructions="用户正文", scope=SkillScope.USER)
    await skills.install(name="shared-name", description="项目", instructions="项目正文", scope=SkillScope.PROJECT)
    await skills.set_enabled(name="shared-name", scope=SkillScope.USER, enabled=False)
    await skills.update(name="shared-name", description="用户修改", instructions="新用户正文", scope=SkillScope.USER, enabled=False)
    assert (await skills.load_managed("shared-name", SkillScope.USER, False)).metadata.description == "用户修改"
    assert (await skills.load("shared-name")).metadata.description == "项目"


@pytest.mark.asyncio
async def test_rolling_fifth_task_history_dedup_dismiss_reject_and_retry(app):
    service = await app.project_services.get()
    learning = service.learning
    learning.settings.skill_learning_enabled = True
    conversation = await app.conversation_store.create()
    tasks = []
    async def complete():
        task = await service.tasks.create(title="接口检查", owner_conversation_id=conversation.id, run_ids=(f"run-{len(tasks)}",))
        task = await app.task_store.set_status(task.id, TaskStatus.COMPLETED)
        tasks.append(task)
    for _ in range(4):
        await complete()
    learning.miner.mine = AsyncMock()
    assert (await learning.maybe_run_mining()).skipped_reason == "not_enough_tasks"
    learning.miner.mine.assert_not_awaited()
    await complete()
    cluster = TaskPatternCluster(id="api-flow", task_ids=tuple(t.id for t in tasks), pattern_name="接口检查", description="接口检查",
        similarity_reason="步骤相同", reusable_value="可重复验证")
    learning.miner.mine = AsyncMock(return_value=PatternMiningOutcome(clusters=(cluster,)))
    execution = SimpleNamespace(tool_call=ToolCall(id="tool", name="http_request", arguments={}),
        tool_result=ToolResult(tool_call_id="tool", tool_name="http_request", success=True, duration_ms=1, output="ok"))
    learning._load_task_events = AsyncMock(return_value=(execution,))
    learning.evidence_builder.build = lambda *_: "发送请求成功，业务断言通过"
    draft = candidate(source_task_ids=cluster.task_ids, source_run_ids=tuple(t.run_ids[0] for t in tasks))
    learning.distiller.distill = AsyncMock(return_value=DistillationOutcome(candidate=draft))
    assert (await learning.maybe_run_mining()).candidate_count == 1
    assert (await learning.maybe_run_mining()).skipped_reason == "unchanged"
    ctx = SimpleNamespace(application=app)
    result = await project_flows.learning_list({"project_id": service.project.id, "conversation_id": conversation.id}, ctx)
    assert len(result["candidates"]) == 1
    saved = result["candidates"][0]
    await project_flows.learning_edit({"candidate_id": saved.id, "expected_revision": saved.revision, "action": "dismiss"}, ctx)
    assert (await learning.get_candidate(saved.id)).dismissed
    assert (await learning.get_candidate(saved.id)).status.value == "pending"
    await learning.reject(saved.id)
    await complete()
    assert (await learning.maybe_run_mining()).candidate_count == 0
    learning.miner.mine = AsyncMock(return_value=PatternMiningOutcome(error="model offline"))
    await complete()
    assert (await learning.maybe_run_mining()).error == "model offline"
    watermark = await learning.candidate_store.load_watermark()
    assert watermark.inflight.attempt == 1
    assert len(watermark.inflight.task_ids) == 7


@pytest.mark.asyncio
async def test_migration_backup_and_restart_persist_project_card(tmp_path):
    app = application(tmp_path)
    await app.start()
    service = await app.project_services.get()
    conversation = await app.conversation_store.create()
    project_id = service.project.id
    await service.learning.candidate_store.create(candidate(project_id=project_id, source_conversation_id=conversation.id))
    await app.close()
    app2 = application(tmp_path)
    await app2.start()
    try:
        assert app2.projects.default_id == project_id
        result = await project_flows.learning_list({"project_id": project_id, "conversation_id": conversation.id}, SimpleNamespace(application=app2))
        assert len(result["candidates"]) == 1
        assert result["candidates"][0].project_id == project_id
        assert (tmp_path / "migration-backup-v2" / "pluto.db").exists()
    finally:
        await app2.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["unrelated", "duplicate_ids", "no_execution"])
async def test_five_completed_tasks_without_similar_evidence_do_not_generate(app, reason):
    service = await app.project_services.get()
    learning = service.learning
    learning.settings.skill_learning_enabled = True
    conversation = await app.conversation_store.create()
    tasks = []
    for i in range(5):
        task = await service.tasks.create(title=f"任务 {i}", owner_conversation_id=conversation.id, run_ids=(f"run-{i}",))
        tasks.append(await app.task_store.set_status(task.id, TaskStatus.COMPLETED))
    ids = tuple(t.id for t in tasks)
    cluster = TaskPatternCluster(id="pattern", task_ids=ids if reason != "duplicate_ids" else (ids[0],) * 5,
        pattern_name="流程", description="流程", similarity_reason="类似", reusable_value="复用")
    learning.miner.mine = AsyncMock(return_value=PatternMiningOutcome(clusters=() if reason == "unrelated" else (cluster,)))
    learning._load_task_events = AsyncMock(return_value=())
    learning.distiller.distill = AsyncMock()
    results = await asyncio.gather(*(learning.maybe_run_mining() for _ in range(3)))
    assert all(not result.candidate_count for result in results)
    learning.miner.mine.assert_awaited_once()
    learning.distiller.distill.assert_not_awaited()
    assert not await learning.list_candidates()


@pytest.mark.asyncio
async def test_manual_generation_still_available_when_automatic_learning_disabled(app):
    service = await app.project_services.get()
    conversation = await app.conversation_store.create()
    task = await service.tasks.create(title="显式生成", owner_conversation_id=conversation.id)
    service.learning._load_task_events = AsyncMock(return_value=())
    service.learning.evidence_builder.build = lambda *_: "人工入口的执行证据"
    service.learning.distiller.distill = AsyncMock(return_value=DistillationOutcome(candidate=candidate(source_task_ids=(task.id,))))
    draft, created, _ = await service.learning.generate_for_task(task.id)
    assert created and draft.project_id == service.project.id
    assert draft.origin.value == "manual_task"
    assert not await service.skills.catalog()


@pytest.mark.asyncio
async def test_stale_background_cannot_overwrite_user_preferences_or_project_memory(app):
    from app.memory.core import core_generation
    service = await app.project_services.get()
    old_generation = service.memory.core.manual_generation
    ctx = SimpleNamespace(application=app)
    _, _, version = await service.memory.core.snapshot()
    await project_flows.memory_edit({"scope": "user", "key": "communication.language", "value": "中文",
        "expected_version": version}, ctx)
    token = core_generation.set(old_generation)
    try:
        with pytest.raises(ValueError, match="旧 Run"):
            await service.memory.upsert_core(key="communication.language", value="英文", reason="旧任务",
                source_statement="以后英文")
    finally:
        core_generation.reset(token)
    assert (await service.memory.core.entries())[0].value == "中文"
    service.memory.manual_generation += 1
    with pytest.raises(ValueError, match="旧后台"):
        await service.memory.create_if_capacity(title="旧决定", summary="旧摘要", content="过期结果", expected_generation=0)


@pytest.mark.asyncio
async def test_approval_interrupted_after_file_write_can_resume_without_duplicate_install(app, monkeypatch):
    service = await app.project_services.get()
    await service.learning.candidate_store.create(candidate(project_id=service.project.id))
    original = service.learning.candidate_store.update
    async def crash_after_install(draft):
        if draft.status.value == "accepted":
            raise OSError("simulated restart after skill file write")
        return await original(draft)
    monkeypatch.setattr(service.learning.candidate_store, "update", crash_after_install)
    with pytest.raises(OSError, match="simulated restart"):
        await service.learning.accept("a" * 32)
    assert (await service.learning.get_candidate("a" * 32)).approval_revision == 1
    monkeypatch.setattr(service.learning.candidate_store, "update", original)
    draft, path = await service.learning.accept("a" * 32)
    assert draft.status.value == "accepted" and path.is_file()
    assert len(await service.skills.catalog()) == 1


@pytest.mark.asyncio
async def test_update_preview_matches_installed_file_and_preserves_resources(app):
    service = await app.project_services.get()
    installed = await service.skills.install(name="api-check", description="旧版本", instructions="旧流程")
    raw = installed.metadata.location.read_text(encoding="utf-8")
    installed.metadata.location.write_text(raw.replace("---\n", "---\nlicense: MIT\n", 1), encoding="utf-8")
    reference = installed.metadata.location.parent / "references" / "api.txt"
    reference.parent.mkdir()
    reference.write_text("接口资料", encoding="utf-8")
    draft = await prepare_candidate(service.learning, candidate(action=SkillCandidateAction.UPDATE, existing_skill_name="api-check"))
    await service.learning.candidate_store.create(draft)
    preview = await project_flows.learning_get({"candidate_id": draft.id}, SimpleNamespace(application=app))
    _, path = await service.learning.accept(draft.id)
    assert path.read_text(encoding="utf-8") == preview["markdown"]
    assert "license: MIT" in preview["markdown"]
    assert reference.read_text(encoding="utf-8") == "接口资料"


@pytest.mark.asyncio
async def test_learning_switch_persisted_across_restart_and_retry_reset(tmp_path):
    app = application(tmp_path)
    await app.start()
    await app.learning_worker.set_enabled(False)
    await app.close()
    restored = application(tmp_path)
    await restored.start()
    try:
        await restored.learning_worker.close()
        assert not restored.learning_worker.enabled
        service = await restored.project_services.get()
        watermark = await service.learning.candidate_store.load_watermark()
        await service.learning.candidate_store.save_watermark(watermark.model_copy(update={"last_error": "offline"}))
        await project_flows.learning_settings({"project_id": service.project.id, "retry": True}, SimpleNamespace(application=restored))
        assert (await service.learning.candidate_store.load_watermark()).last_error is None
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_legacy_migration_backups_preserve_originals_and_are_idempotent(tmp_path):
    from app.conversation.store import SQLiteConversationStore
    from app.run.store import SQLiteRunStore
    from app.task.store import FileTaskStore
    from app.memory.manager import MemoryManager
    from app.skill_learning.store import SkillCandidateStore
    import sqlite3
    conversations = SQLiteConversationStore(tmp_path / "pluto.db")
    await conversations.initialize()
    old_conversation = await conversations.create(title="旧会话")
    runs = SQLiteRunStore(tmp_path / "pluto.db")
    await runs.initialize()
    old_run = await runs.create(conversation_id=old_conversation.id)
    tasks = FileTaskStore(tmp_path / "tasks")
    await tasks.initialize()
    old_task = await tasks.create(title="旧任务", owner_conversation_id=old_conversation.id)
    memory = MemoryManager(tmp_path / "memory")
    await memory.initialize()
    old_record = await memory.create(title="旧接口", summary="旧摘要", content="原始约定")
    await memory.core.update("# Core Memory\n\n默认中文交流")
    await memory.close()
    candidates = SkillCandidateStore(tmp_path / "learning")
    await candidates.initialize()
    await candidates.create(candidate())
    task_bytes = (tmp_path / "tasks" / f"{old_task.id}.json").read_bytes()
    record_bytes = (tmp_path / "memory" / "active" / f"{old_record.id}.md").read_bytes()
    for _ in range(2):
        migrated = application(tmp_path)
        await migrated.start()
        try:
            service = await migrated.project_services.get()
            assert (await migrated.conversation_store.get(old_conversation.id)).project_id == service.project.id
            assert (await migrated.run_store.get(old_run.id)).project_id == service.project.id
            assert (await migrated.task_store.get(old_task.id)).project_id == service.project.id
            assert (await service.memory.read(old_record.id)).project_id == service.project.id
            assert (await service.learning.get_candidate("a" * 32)).project_id == service.project.id
            assert "默认中文交流" in await service.memory.core.load()
            backup = tmp_path / "migration-backup-v2"
            assert (backup / "tasks" / f"{old_task.id}.json").read_bytes() == task_bytes
            assert (backup / "memory" / "active" / f"{old_record.id}.md").read_bytes() == record_bytes
            with sqlite3.connect(backup / "pluto.db") as db:
                assert db.execute("SELECT project_id FROM conversations WHERE id=?", (old_conversation.id,)).fetchone()[0] is None
        finally:
            await migrated.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["user", "tool", "assistant", "stale"])
async def test_project_reflection_verifies_provenance_and_rejects_stale_results(app, source):
    from app.agent.memory_post_run import PostRunMemoryCoordinator
    from app.memory.reflection_models import MemoryReflectionInput, MemoryReflectionProposal, ReflectionDecision
    service = await app.project_services.get()
    quote = "本项目接口使用 REST"
    reflector = SimpleNamespace(provider_hint="fake", model_hint="fake-model", decide=AsyncMock(return_value=MemoryReflectionProposal(
        decision=ReflectionDecision(action="create", kind="project_interface", title="接口", summary="接口约定", content=quote,
            reason="明确的项目约定", source_statement=quote))))
    coordinator = PostRunMemoryCoordinator(manager=service.memory, reflector=reflector, maintenance_reflector=None, task_context_provider=None, submit=None)
    if source == "stale":
        service.memory.manual_generation += 1
    reflection = MemoryReflectionInput(run_id="run", user_input=quote if source in {"user", "stale"} else "检查接口",
        final_answer=quote, tool_context=(json.dumps({"success": True, "output": quote}),) if source == "tool" else ())
    emitter = SimpleNamespace(emit=AsyncMock())
    await coordinator._run_reflection(reflector=reflector, manager=service.memory, reflection_input=reflection,
        recalled_revisions={}, emitter=emitter)
    records = await service.memory.list()
    assert bool(records) == (source in {"user", "tool"})
    if records:
        assert records[0].kind == "project_interface"
        assert records[0].source["statement"] == quote
        assert records[0].source["run_id"] == "run"


@pytest.mark.asyncio
async def test_editing_legacy_core_preserves_structured_preferences(app):
    service = await app.project_services.get()
    await service.memory.core.update("# Core Memory\n\n旧的用户偏好")
    await service.memory.upsert_core(key="communication.language", value="中文", reason="明确陈述", source_statement="默认中文")
    ctx = SimpleNamespace(application=app)
    overview = await memories.memory_list({}, ctx)
    assert overview["legacy_core"] == "旧的用户偏好"
    await project_flows.memory_edit({"scope": "user", "action": "edit_legacy", "value": "新的旧格式偏好", "expected_version": overview["core_version"]}, ctx)
    updated = await memories.memory_list({}, ctx)
    assert updated["legacy_core"] == "新的旧格式偏好"
    assert updated["preferences"][0].value == "中文"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "temporary", "invented_source", "stale"])
async def test_preference_extraction_source_and_stable_key_rules(app, case, monkeypatch):
    from app.memory.preferences import extract_preferences
    service = await app.project_services.get()
    text = "以后默认中文回答" if case != "temporary" else "这次临时使用默认的英文模板"
    entries = [{"key": "communication.language", "value": "中文",
        "source_statement": text if case != "invented_source" else "从未说过的偏好"}]
    adapter = app.registry.get("fake")
    monkeypatch.setattr(adapter, "complete", AsyncMock(return_value=ModelResponse(id="extract", provider="fake", model="fake-model",
        message=Message(role=MessageRole.ASSISTANT, content=json.dumps({"preferences": entries}, ensure_ascii=False)))))
    run = SimpleNamespace(user_message=text, project_id=service.project.id, started_at=datetime.now(UTC), created_at=datetime.now(UTC))
    if case == "stale":
        service.memory.core.manual_generation += 1
    await extract_preferences(app, run, expected_generation=0)
    assert bool(await service.memory.core.entries()) == (case == "valid")


@pytest.mark.asyncio
async def test_scan_waits_for_run_trace_to_finish_before_marking_window_processed(app):
    service = await app.project_services.get()
    service.learning.settings.skill_learning_enabled = True
    conversation = await app.conversation_store.create()
    last_run = None
    for i in range(5):
        run = await app.run_store.create(conversation_id=conversation.id, project_id=service.project.id)
        await app.run_store.mark_started(run.id)
        task = await service.tasks.create(title="接口检查", owner_conversation_id=conversation.id, run_ids=(run.id,))
        await app.task_store.set_status(task.id, TaskStatus.COMPLETED)
        if i != 4:
            await app.run_store.mark_completed(run.id)
        last_run = run
    service.learning.miner.mine = AsyncMock(return_value=PatternMiningOutcome(clusters=()))
    assert (await service.learning.maybe_run_mining()).skipped_reason == "not_enough_tasks"
    service.learning.miner.mine.assert_not_awaited()
    await app.run_store.mark_completed(last_run.id)
    assert (await service.learning.maybe_run_mining()).scanned_task_count == 5
    service.learning.miner.mine.assert_awaited_once()


@pytest.mark.asyncio
async def test_registered_rpc_end_to_end_project_review_and_installed_management(app, tmp_path):
    from app.server.rpc.methods import build_dispatcher
    rpc = build_dispatcher()
    ctx = SimpleNamespace(application=app)
    root = tmp_path / "rpc-project"
    root.mkdir()
    project = (await rpc.dispatch("project.register", {"path": str(root)}, ctx))["project"]
    conversation = (await rpc.dispatch("conversation.create", {"project_id": project.id}, ctx))["conversation"]
    dispatched = await app.conversation_service.dispatch(conversation_id=conversation.id, content="检查接口")
    assert dispatched.run.project_id == project.id
    service = await app.project_services.get(project.id)
    await service.learning.candidate_store.create(candidate(project_id=project.id, source_conversation_id=conversation.id))
    listed = await rpc.dispatch("skill_learning.list", {"project_id": project.id, "conversation_id": conversation.id}, ctx)
    assert len(listed["candidates"]) == 1
    assert not (await app.project_services.get()).skills.project_dir.joinpath("api-check").exists()
    edited = (await rpc.dispatch("skill_learning.edit", {"project_id": project.id, "candidate_id": "a" * 32,
        "expected_revision": 1, "description": "经用户修改的流程"}, ctx))["candidate"]
    accepted = await rpc.dispatch("skill_learning.accept", {"project_id": project.id, "candidate_id": edited.id,
        "expected_revision": edited.revision, "scope": "project", "confirmed": True}, ctx)
    assert accepted["candidate"]["status"] == "accepted"
    detail = await rpc.dispatch("skill.get", {"project_id": project.id, "name": "api-check", "scope": "project"}, ctx)
    assert detail["skill"].metadata.description == "经用户修改的流程"
    await rpc.dispatch("skill.set_enabled", {"project_id": project.id, "name": "api-check", "scope": "project", "enabled": False}, ctx)
    assert await service.skills.load("api-check") is None
    with pytest.raises(JsonRpcError):
        await rpc.dispatch("skill.get", {"project_id": app.projects.default_id, "name": "api-check", "scope": "project"}, ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disabled", "rejected"])
async def test_inflight_discovery_respects_later_human_choice(app, change):
    service = await app.project_services.get()
    learning = service.learning
    learning.settings.skill_learning_enabled = True
    conversation = await app.conversation_store.create()
    tasks = []
    for i in range(5):
        task = await service.tasks.create(title="接口检查", owner_conversation_id=conversation.id, run_ids=(f"run-{i}",))
        tasks.append(await app.task_store.set_status(task.id, TaskStatus.COMPLETED))
    cluster = TaskPatternCluster(id="flow", task_ids=tuple(t.id for t in tasks), pattern_name="接口检查", description="接口检查",
        similarity_reason="相同步骤", reusable_value="验证接口")
    learning.miner.mine = AsyncMock(return_value=PatternMiningOutcome(clusters=(cluster,)))
    execution = SimpleNamespace(tool_call=ToolCall(id="tool", name="http_request", arguments={}),
        tool_result=ToolResult(tool_call_id="tool", tool_name="http_request", success=True, duration_ms=1, output="ok"))
    learning._load_task_events = AsyncMock(return_value=(execution,))
    learning.evidence_builder.build = lambda *_: "请求和断言成功"
    async def distill(*args, **kwargs):
        if change == "disabled":
            learning.settings.skill_learning_enabled = False
        else:
            suppressed = candidate(id="b" * 32, project_id=service.project.id, source_task_ids=cluster.task_ids)
            await learning.candidate_store.create(suppressed)
            await learning.reject(suppressed.id)
        return DistillationOutcome(candidate=candidate(source_task_ids=cluster.task_ids))
    learning.distiller.distill = distill
    result = await learning.maybe_run_mining()
    assert result.candidate_count == 0
    assert await learning.get_candidate("a" * 32) is None
