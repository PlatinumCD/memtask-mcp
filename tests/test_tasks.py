from __future__ import annotations

import pytest

from memory_task_mcp import manager


def test_add_list_and_get_task() -> None:
    task = manager.add_task("Write release notes", project="ops", tags=["docs", "docs"])

    tasks = manager.list_tasks()

    assert len(tasks) == 1
    assert tasks[0]["task_ref"] == task["task_ref"]
    assert tasks[0]["pending_id"] == 1
    assert tasks[0]["tags"] == ["docs"]
    assert manager.get_task(task["task_ref"])["description"] == "Write release notes"


def test_batch_add_and_remove_all_tasks() -> None:
    created = manager.add_batch_tasks(["Draft agenda", "Send recap"], project="meetings")

    result = manager.remove_all_tasks()

    assert len(created) == 2
    assert result["attempted_count"] == 2
    assert result["removed_count"] == 2
    assert result["failed"] == []
    assert manager.list_tasks() == []


def test_dependencies_block_parent_completion_until_child_is_complete() -> None:
    parent = manager.add_task("Parent")
    child = manager.add_task("Child", parent_task_refs=[parent["task_ref"]])

    with pytest.raises(ValueError, match="incomplete child tasks"):
        manager.complete_task(parent["task_ref"])

    completed_child = manager.complete_task(child["task_ref"])
    completed_parent = manager.complete_task(parent["task_ref"])

    assert completed_child["status"] == "completed"
    assert completed_parent["status"] == "completed"
    assert manager.list_tasks() == []


def test_current_task_replaces_previous_current_task() -> None:
    first = manager.add_task("First")
    second = manager.add_task("Second")

    manager.set_current_task(first["task_ref"])
    manager.set_current_task(second["task_ref"])

    current = manager.current_tasks()

    assert len(current) == 1
    assert current[0]["task_ref"] == second["task_ref"]


def test_memory_refs_are_validated_when_adding_tasks() -> None:
    with pytest.raises(ValueError, match="Memory 'missing' not found"):
        manager.add_task("Bad ref", memory_refs=["missing"])
