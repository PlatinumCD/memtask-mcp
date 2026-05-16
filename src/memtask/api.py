from __future__ import annotations

import json
from typing import Any

from . import manager


SERVER_INSTRUCTIONS = (
    "Prefer `task_ref` over numeric task ids for follow-up calls. "
    "Numeric ids can change after task mutations because pending tasks are displayed with ephemeral ids."
)
HELP_OVERVIEW = """# Local MCP Help

This server exposes a local SQLite-backed task and memory manager.

## Core Rule

Prefer `task_ref` for all follow-up task calls. It is the stable UUID alias returned by task-listing and task-fetching calls.
Use `pending_id` only as a temporary display id for humans.

## Common Workflow

1. Call `list_tasks`
2. Select a task's `task_ref`
3. Call `set_current_task(task_ref)` to start work
4. Call `complete_task(task_ref)` when finished
5. Call `remember(...)` to persist useful context
6. Recall with `recall(...)` and attach results with `memory_refs` when adding follow-up tasks

## Notes

- `current_tasks` only shows started pending tasks
- `complete_task` moves a task out of the pending list, so numeric ids can shift afterward
- `add_task` and `add_batch_tasks` return the new task records; capture their `task_ref` immediately if you plan to mutate them later
- `remove_all_tasks` deletes every currently listed pending task and is destructive.
- `remember` stores context with `memory_scope`, `kind`, and `confidence` (0-100)
- `recall` supports filtering by `memory_scope`, `kind`, minimum confidence, and text search via `query`

## Dependency Model

Tasks can optionally include `parent_task_refs` when created. Those are dependency edges used by the
manager for completion checks.

## Memory Graph

Memories can be organized with a single `parent_memory_id`.
Tasks can couple to memory via `memory_refs` for persistent context.
""".strip()


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _best_practice_for_tool(name: str) -> str | None:
    if name in {"get_task", "set_current_task", "complete_task", "remove_task"}:
        return "Prefer `task_ref`/UUID over numeric ids because pending ids can change after task mutations."
    if name in {"list_tasks", "current_tasks"}:
        return "Use this call to discover stable `task_ref` values before follow-up mutations."
    if name in {"add_task", "add_batch_tasks"}:
        return "Capture the returned `task_ref` values immediately if you will mutate these tasks later."
    if name in {"remember", "recall", "update_memory"}:
        return "Use `memory_scope` for context boundaries and `confidence` to represent belief strength."
    if name == "remove_all_tasks":
        return "This tool is destructive and removes all pending tasks returned by `list_tasks`."
    return None


def _example_for_tool(name: str) -> dict[str, Any] | list[dict[str, Any]] | None:
    if name == "list_tasks":
        return {}
    if name == "current_tasks":
        return {}
    if name == "get_task":
        return {"task_id": "task_ref-from-list_tasks"}
    if name == "add_task":
        return {"description": "Write release notes", "project": "ops", "tags": ["docs"]}
    if name == "add_batch_tasks":
        return {
            "descriptions": ["Draft agenda", "Send recap"],
            "project": "meetings",
            "tags": ["team"],
            "parent_task_refs": ["parent-task-ref"],
        }
    if name == "remember":
        return {
            "content": "Release notes should include API migration commands first.",
            "memory_scope": "projects",
            "kind": "fact",
            "confidence": 90,
        }
    if name == "recall":
        return {
            "query": "release notes",
            "memory_scope": "projects",
            "min_confidence": 70,
            "limit": 5,
        }
    if name == "get_memory":
        return {"memory_id": "memory-ref"}
    if name == "update_memory":
        return {
            "memory_id": "memory-ref",
            "confidence": 95,
            "tags": ["evidence", "release"],
        }
    if name == "delete_memory":
        return {"memory_id": "memory-ref"}
    if name == "set_current_task":
        return {"task_id": "task_ref-from-list_tasks"}
    if name == "complete_task":
        return {"task_id": "task_ref-from-current_tasks"}
    if name == "remove_task":
        return {"task_id": "task_ref-to-delete"}
    if name == "remove_all_tasks":
        return {}
    return None


async def _tool_help_payload(mcp: Any, name: str) -> dict[str, Any]:
    tools = await mcp.list_tools()
    for tool in tools:
        if tool.name != name:
            continue

        payload: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema,
        }
        best_practice = _best_practice_for_tool(tool.name)
        if best_practice is not None:
            payload["best_practice"] = best_practice
        example = _example_for_tool(tool.name)
        if example is not None:
            payload["example_arguments"] = example
        return payload

    raise ValueError(f"Unknown tool: {name}")


def register(mcp: Any, manager_module: Any = manager) -> Any:
    @mcp.resource(
        "help://overview",
        name="help_overview",
        title="Local MCP Overview",
        description="Overview, invariants, and common workflows for the local task manager MCP server.",
        mime_type="text/markdown",
    )
    def help_overview() -> str:
        return HELP_OVERVIEW

    @mcp.resource(
        "help://tools",
        name="help_tools",
        title="Local MCP Tool Catalog",
        description="Live catalog of task-manager tools with best-practice notes.",
        mime_type="application/json",
    )
    async def help_tools() -> str:
        tools = await mcp.list_tools()
        payload = []
        for tool in tools:
            payload.append(await _tool_help_payload(mcp, tool.name))
        return _json_text(payload)

    @mcp.resource(
        "help://tool/{name}",
        name="help_tool",
        title="Local MCP Tool Help",
        description="Detailed help for a specific task-manager tool.",
        mime_type="application/json",
    )
    async def help_tool(name: str) -> str:
        return _json_text(await _tool_help_payload(mcp, name))

    @mcp.tool()
    def list_tasks() -> str:
        """List pending tasks from Agent Task Manager with stable `task_ref` values."""
        return _json_text(manager_module.list_tasks())

    @mcp.tool()
    def get_task(task_id: str) -> str:
        """Get a single task by task_ref/UUID or pending numeric id. UUID is preferred."""
        return _json_text(manager_module.get_task(task_id))

    @mcp.tool()
    def add_task(
        description: str,
        project: str | None = None,
        tags: list[str] | None = None,
        parent_task_refs: list[str] | None = None,
        memory_refs: list[str] | None = None,
    ) -> str:
        """Add a new task to Agent Task Manager."""
        return _json_text(
            manager_module.add_task(
                description=description,
                project=project,
                tags=tags,
                parent_task_refs=parent_task_refs,
                memory_refs=memory_refs,
            )
        )

    @mcp.tool()
    def add_batch_tasks(
        descriptions: list[str],
        project: str | None = None,
        tags: list[str] | None = None,
        parent_task_refs: list[str] | None = None,
        memory_refs: list[str] | None = None,
    ) -> str:
        """Add multiple tasks to Agent Task Manager."""
        return _json_text(
            manager_module.add_batch_tasks(
                descriptions=descriptions,
                project=project,
                tags=tags,
                parent_task_refs=parent_task_refs,
                memory_refs=memory_refs,
            )
        )

    @mcp.tool()
    def complete_task(task_id: str) -> str:
        """Complete a task by task_ref/UUID or pending numeric id. UUID is preferred."""
        return _json_text(manager_module.complete_task(task_id))

    @mcp.tool()
    def remove_task(task_id: str) -> str:
        """Delete a task by task_ref/UUID or pending numeric id. UUID is preferred."""
        return _json_text(manager_module.remove_task(task_id))

    @mcp.tool()
    def remove_all_tasks() -> str:
        """Delete all pending tasks currently returned by `list_tasks`."""
        return _json_text(manager_module.remove_all_tasks())

    @mcp.tool()
    def current_tasks() -> str:
        """List currently active tasks with stable `task_ref` values."""
        return _json_text(manager_module.current_tasks())

    @mcp.tool()
    def set_current_task(task_id: str) -> str:
        """Stop active tasks and mark the specified task as current. UUID is preferred."""
        return _json_text(manager_module.set_current_task(task_id))

    @mcp.tool()
    def remember(
        content: str,
        memory_scope: str | None = None,
        kind: str | None = None,
        confidence: int = 100,
        parent_memory_id: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Store a memory artifact with optional scope, kind, and confidence."""
        return _json_text(
            manager_module.remember(
                content=content,
                memory_scope=memory_scope,
                kind=kind,
                confidence=confidence,
                parent_memory_id=parent_memory_id,
                tags=tags,
            )
        )

    @mcp.tool()
    def recall(
        query: str | None = None,
        memory_scope: str | None = None,
        kind: str | None = None,
        min_confidence: int | None = None,
        parent_memory_id: str | None = None,
        limit: int | None = None,
    ) -> str:
        """Recall memory records by scope, kind, and confidence."""
        return _json_text(
            manager_module.recall(
                query=query,
                memory_scope=memory_scope,
                kind=kind,
                min_confidence=min_confidence,
                parent_memory_id=parent_memory_id,
                limit=limit,
            )
        )

    @mcp.tool()
    def get_memory(memory_id: str) -> str:
        """Get a memory by memory_id."""
        return _json_text(manager_module.get_memory(memory_id))

    @mcp.tool()
    def update_memory(
        memory_id: str,
        content: str | None = None,
        memory_scope: str | None = None,
        kind: str | None = None,
        confidence: int | None = None,
        parent_memory_id: str | None = None,
        clear_parent: bool = False,
        tags: list[str] | None = None,
    ) -> str:
        """Update a memory with optional field replacements."""
        return _json_text(
            manager_module.update_memory(
                memory_id=memory_id,
                content=content,
                memory_scope=memory_scope,
                kind=kind,
                confidence=confidence,
                parent_memory_id=parent_memory_id,
                clear_parent=clear_parent,
                tags=tags,
            )
        )

    @mcp.tool()
    def delete_memory(memory_id: str) -> str:
        """Delete a memory by memory_id."""
        return _json_text(manager_module.delete_memory(memory_id))

    return mcp
