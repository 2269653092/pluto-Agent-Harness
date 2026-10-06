"""Folder identities and project-scoped service factory (local single user)."""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import aiosqlite
from pydantic import BaseModel


class Project(BaseModel):
    id: str
    name: str
    path: str


class ProjectStore:
    def __init__(self, database: Path):
        self.database = database
        self.default_id: str | None = None

    async def initialize(self, workspace: Path):
        async with aiosqlite.connect(self.database) as db:
            await db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE)")
            await db.commit()
        project = await self.register(str(workspace), name="默认工作区")
        self.default_id = project.id
        async with aiosqlite.connect(self.database) as db:
            await db.execute("UPDATE conversations SET project_id=? WHERE project_id IS NULL", (project.id,))
            await db.execute("UPDATE runs SET project_id=COALESCE((SELECT project_id FROM conversations WHERE id=runs.conversation_id), ?) WHERE project_id IS NULL", (project.id,))
            await db.commit()
        return project

    async def register(self, path: str, *, name: str | None = None) -> Project:
        requested = Path(path).expanduser()
        if not requested.is_absolute():
            raise ValueError("项目文件夹必须使用绝对路径")
        root = requested.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("项目必须绑定已存在的文件夹")
        normalized = os.path.normcase(str(root))
        identifier = hashlib.sha256(normalized.encode()).hexdigest()[:32]
        async with aiosqlite.connect(self.database) as db:
            await db.execute("INSERT OR IGNORE INTO projects VALUES (?, ?, ?)", (identifier, name or root.name or str(root), normalized))
            await db.commit()
        return await self.require(identifier)

    async def list(self) -> tuple[Project, ...]:
        async with aiosqlite.connect(self.database) as db:
            cursor = await db.execute("SELECT id,name,path FROM projects ORDER BY name,id")
            return tuple(Project(id=r[0], name=r[1], path=r[2]) for r in await cursor.fetchall())

    async def require(self, identifier: str | None) -> Project:
        for project in await self.list():
            if project.id == (identifier or self.default_id):
                return project
        raise KeyError("项目不存在")


def backup_legacy(database: Path, paths: dict[str, Path]) -> None:
    """Backup BEFORE schema or file changes; keep originals for rollback."""
    backup = database.parent / "migration-backup-v2"
    backup.mkdir(parents=True, exist_ok=True)
    target = backup / "pluto.db"
    if database.is_file() and not target.exists():
        with sqlite3.connect(database) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
    for name, path in paths.items():
        destination = backup / name
        if path.is_dir() and not destination.exists():
            shutil.copytree(path, destination, symlinks=True)


class ProjectTaskStore:
    """A fail-closed view of the shared task store, not a global current project."""
    def __init__(self, store, project_id: str):
        self.store, self.project_id = store, project_id

    async def list(self, **kwargs):
        limit = kwargs.pop("limit", 50)
        tasks = [t for t in await self.store.list(limit=1_000_000, **kwargs) if t.project_id == self.project_id]
        if kwargs.get("status") and kwargs["status"].value == "completed":
            tasks.sort(key=lambda t: t.completed_at or t.created_at, reverse=True)
        return tuple(tasks[:limit])

    async def get(self, identifier):
        task = await self.store.get(identifier)
        return task if task and task.project_id == self.project_id else None

    async def resolve(self, identifier, **kwargs):
        task = await self.store.resolve(identifier, **kwargs)
        return task if task and task.project_id == self.project_id else None

    async def create(self, **kwargs):
        if await self.store.project_resolver(kwargs["owner_conversation_id"]) != self.project_id:
            raise ValueError("任务会话不属于当前项目")
        return await self.store.create(**kwargs)

    async def update(self, identifier, *args, **kwargs):
        if await self.get(identifier) is None:
            raise KeyError("任务不属于当前项目")
        return await self.store.update(identifier, *args, **kwargs)

    async def apply_patch(self, identifier, *args, **kwargs):
        if await self.get(identifier) is None:
            raise KeyError("任务不属于当前项目")
        return await self.store.apply_patch(identifier, *args, **kwargs)

    async def active_for_conversation(self, identifier):
        if await self.store.project_resolver(identifier) != self.project_id:
            return None
        return await self.store.active_for_conversation(identifier)

    def __getattr__(self, name):
        # Other methods use ownership checks in Task tools; never expose raw get/list.
        return getattr(self.store, name)


@dataclass
class ProjectServices:
    project: Project
    memory: object
    skills: object
    learning: object
    tasks: object
    artifacts: object


class ProjectServiceFactory:
    def __init__(self, application):
        self.app = application
        self._services = {}
        self._lock = asyncio.Lock()
        self._mcp = []

    async def get(self, identifier: str | None = None) -> ProjectServices:
        from app.memory.manager import MemoryManager
        from app.skills import SkillStore
        from app.skill_learning.service import SkillLearningService
        from app.skill_learning.store import SkillCandidateStore
        from app.artifact import ArtifactService

        project = await self.app.projects.require(identifier)
        async with self._lock:
            if project.id in self._services:
                return self._services[project.id]
            tasks = ProjectTaskStore(self.app.task_store, project.id)
            if project.id == self.app.projects.default_id:
                memory, skills, learning, artifacts = (self.app.memory_manager, self.app.skill_store,
                                                        self.app.skill_learning, self.app.artifact_service)
                learning.task_store = tasks
            else:
                data = self.app.database.parent / "projects" / project.id
                memory = MemoryManager(memory_dir=data / "memory", embedding=self.app.memory_embedding_adapter,
                                       search_settings=self.app.memory_manager.search_settings)
                memory.core = self.app.memory_manager.core
                await memory.initialize()
                skills = SkillStore(user_dir=self.app.skill_store.user_dir, project_dir=data / "skills")
                await skills.initialize()
                settings = self.app.skill_learning.settings.model_copy(update={"skill_learning_data_dir": data / "skill-learning"})
                candidates = SkillCandidateStore(settings.skill_learning_data_dir)
                await candidates.initialize()
                learning = SkillLearningService(tasks, self.app.trace_store, skills, candidates, self.app.registry,
                                                settings=settings, default_provider=self.app.provider, default_model=self.app.model)
                artifacts = ArtifactService(self.app.artifact_store, Path(project.path),
                                             managed_dir=self.app.database.parent / "artifacts")
            learning.project_id = project.id
            learning.run_store = self.app.run_store
            if not hasattr(self.app, "_skill_mutation_lock"):
                self.app._skill_mutation_lock = asyncio.Lock()
            learning.review_lock = self.app._skill_mutation_lock
            learning.candidate_store.project_id = project.id
            memory.store.project_id = project.id
            memory.manual_generation = 0
            for record in (*await memory.list(), *await memory.list_archived()):
                if record.project_id is None:
                    updated = record.model_copy(update={"project_id": project.id})
                    directory = memory.store.active_dir if record.status.value == "active" else memory.store.archive_dir
                    await asyncio.to_thread(memory.store._write_bytes, updated.render_markdown(), directory / f"{record.id}.md")
            for candidate in await learning.candidate_store.list():
                if candidate.project_id is None:
                    from app.project_learning import prepare_candidate
                    try:
                        migrated = await prepare_candidate(learning, candidate)
                    except ValueError:
                        migrated = candidate.model_copy(update={"project_id": project.id})
                    await learning.candidate_store.update(migrated)
                if candidate.status.value == "accepted":
                    from app.skills import SkillScope
                    learning.skill_store.record_origin(candidate.proposed_name, SkillScope(candidate.scope),
                        "automatic" if candidate.origin.value == "pattern_mining" else "manual")
                elif candidate.approval_revision == candidate.revision and candidate.approval_scope:
                    from app.skills import SkillScope
                    from app.skill_learning.service import _render_candidate_body
                    current = await skills.load_managed(candidate.existing_skill_name or candidate.proposed_name, SkillScope(candidate.approval_scope))
                    if current and current.metadata.description == candidate.description and current.content.strip() == _render_candidate_body(candidate).strip():
                        await learning.accept(candidate.id, scope=candidate.approval_scope, expected_revision=candidate.revision)
            self._attach_notifications(memory, project.id)
            if getattr(self.app, "change_broadcaster", None):
                artifacts.set_broadcaster(self.app.change_broadcaster)
            service = ProjectServices(project, memory, skills, learning, tasks, artifacts)
            self._services[project.id] = service
            return service

    def _attach_notifications(self, memory, project_id):
        from functools import wraps
        async def failure(reason):
            notify = getattr(self.app, "change_broadcaster", None)
            if notify:
                try:
                    await notify("memory.not_saved", {"project_id": project_id, "reason": reason})
                except Exception:
                    pass
        memory.failure_notifier = failure
        for name in ("create", "create_if_capacity", "update", "update_if_revision", "archive", "archive_if_unchanged", "manage", "upsert_core", "remove_core"):
            method = getattr(memory, name)
            def wrap(method, name):
                @wraps(method)
                async def changed(*args, **kwargs):
                    result = await method(*args, **kwargs)
                    notify = getattr(self.app, "change_broadcaster", None)
                    record = result[0] if isinstance(result, tuple) else result
                    if notify and record is not None:
                        try:
                            await notify("memory.changed", {"project_id": project_id,
                                    "scope": "user" if "core" in name else "project",
                                    "id": getattr(record, "id", getattr(record, "key", None)), "action": name})
                        except Exception:
                            # Notification transport never rolls back a committed mutation.
                            pass
                    return result
                return changed
            setattr(memory, name, wrap(method, name))

    async def runtime(self, identifier: str | None):
        from app.agent.runtime import AgentRuntime
        from app.application import (build_builtin_tool_registry, SandboxSupervisor,
                                     register_memory_tools, register_skill_tools,
                                     register_task_tools, register_artifact_tools,
                                     register_skill_learning_tools, TaskContextProvider)
        services = await self.get(identifier)
        from app.skills.snapshot import SkillSnapshot
        snapshot = await SkillSnapshot.capture(services.skills)
        registry = build_builtin_tool_registry(Path(services.project.path),
                       sandbox_supervisor=SandboxSupervisor(Path(services.project.path)))
        register_memory_tools(registry, services.memory)
        register_skill_tools(registry, snapshot)
        register_task_tools(registry, services.tasks)
        register_artifact_tools(registry, services.artifacts)
        register_skill_learning_tools(registry, services.learning.candidate_store, snapshot)
        for name in self.app.tool_registry.names():
            from app.mcp import MCPToolAdapter, MCPStatusTool
            tool = self.app.tool_registry.get(name)
            if (services.project.id != self.app.projects.default_id
                    and isinstance(tool, (MCPToolAdapter, MCPStatusTool))):
                continue
            if name not in registry.names() and name != "delegate_worker":
                registry.register(self.app.tool_registry.get(name), deferred=self.app.tool_registry.is_deferred(name))
        if services.project.id != self.app.projects.default_id:
            from app.mcp import MCPClientManager, MCPStatusTool
            from app.tools.registry import ToolRegistry
            async with self._lock:
                if not hasattr(services, "mcp_registry"):
                    from app.mcp import MCPConfigurationError
                    config_error = None
                    try:
                        configs = (await self.app.mcp_config_store.load()).servers
                        configs = tuple(config.model_copy(update={"cwd": services.project.path})
                            if config.cwd is None or os.path.normcase(str(Path(config.cwd).resolve())) == os.path.normcase(str(self.app.workspace_root))
                            else config for config in configs)
                    except MCPConfigurationError as exc:
                        configs, config_error = (), str(exc)
                    manager = MCPClientManager(configs, sandbox_supervisor=SandboxSupervisor(Path(services.project.path)))
                    mcp_registry = ToolRegistry()
                    await manager.start(mcp_registry)
                    mcp_registry.register(MCPStatusTool(manager, configuration_error=config_error))
                    services.mcp_registry = mcp_registry
                    self._mcp.append((manager, mcp_registry))
            for name in services.mcp_registry.names():
                registry.register(services.mcp_registry.get(name))
        for name in self.app.tool_registry.deferred_names():
            if name in registry.names():
                registry._deferred_names.add(name)
        kwargs = dict(self.app.runtime.construction)
        kwargs.update(memory_manager=services.memory, skill_store=snapshot,
                      task_context_provider=TaskContextProvider(services.tasks), tool_executor=None)
        return AgentRuntime(self.app.registry, registry, **kwargs)

    async def close(self):
        for manager, registry in self._mcp:
            await manager.close(registry)
        for service in self._services.values():
            if service.memory is not self.app.memory_manager:
                await service.memory.close()
