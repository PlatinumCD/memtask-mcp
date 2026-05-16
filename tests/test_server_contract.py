from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from memory_task_mcp import api


class FakeMCP:
    def __init__(self) -> None:
        self.tools = {}
        self.resources = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator

    def resource(self, uri, **metadata):
        def decorator(func):
            self.resources[metadata["name"]] = {
                "uri": uri,
                "metadata": metadata,
                "func": func,
            }
            return func

        return decorator

    async def list_tools(self):
        return [
            SimpleNamespace(name=name, description=func.__doc__, inputSchema={})
            for name, func in self.tools.items()
        ]


def test_register_exposes_expected_tools() -> None:
    mcp = FakeMCP()

    api.register(mcp)

    assert {
        "list_tasks",
        "get_task",
        "add_task",
        "add_batch_tasks",
        "complete_task",
        "remove_task",
        "remove_all_tasks",
        "current_tasks",
        "set_current_task",
        "remember",
        "recall",
        "get_memory",
        "update_memory",
        "delete_memory",
    }.issubset(mcp.tools)


def test_tool_functions_return_json_strings() -> None:
    mcp = FakeMCP()
    api.register(mcp)

    memory = json.loads(mcp.tools["remember"]("Use precise summaries", confidence=90))
    task = json.loads(mcp.tools["add_task"]("Summarize", memory_refs=[memory["memory_id"]]))
    recalled = json.loads(mcp.tools["recall"](query="precise"))

    assert task["memory_refs"] == [memory["memory_id"]]
    assert recalled[0]["memory_id"] == memory["memory_id"]


def test_help_resources_cover_tasks_and_memory() -> None:
    mcp = FakeMCP()
    api.register(mcp)

    overview = mcp.resources["help_overview"]["func"]()
    tools = asyncio.run(mcp.resources["help_tools"]["func"]())
    remember_help = asyncio.run(mcp.resources["help_tool"]["func"]("remember"))

    assert "Dependency Model" in overview
    assert "Memory Graph" in overview
    assert "remember" in tools
    assert json.loads(remember_help)["name"] == "remember"
