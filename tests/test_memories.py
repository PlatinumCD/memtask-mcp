from __future__ import annotations

import pytest

from memtask import manager


def test_remember_recall_get_and_update_memory() -> None:
    memory = manager.remember(
        "Release notes should include migration commands first.",
        memory_scope="projects",
        kind="fact",
        confidence=80,
        tags=["release"],
    )

    recalled = manager.recall(
        query="migration",
        memory_scope="projects",
        kind="fact",
        min_confidence=70,
        limit=1,
    )
    updated = manager.update_memory(memory["memory_id"], confidence=95, tags=["release", "api"])
    fetched = manager.get_memory(memory["memory_id"])

    assert recalled[0]["memory_id"] == memory["memory_id"]
    assert recalled[0]["last_accessed_at"] is not None
    assert updated["confidence"] == 95
    assert fetched["tags"] == ["release", "api"]


def test_confidence_must_be_zero_to_one_hundred() -> None:
    with pytest.raises(ValueError, match="confidence must be between 0 and 100"):
        manager.remember("Too certain", confidence=101)


def test_parent_memory_can_be_assigned_and_cleared() -> None:
    parent = manager.remember("Parent memory")
    child = manager.remember("Child memory", parent_memory_id=parent["memory_id"])

    assert child["parent_memory_id"] == parent["memory_id"]

    updated = manager.update_memory(child["memory_id"], clear_parent=True)

    assert updated["parent_memory_id"] is None


def test_delete_memory_clears_task_memory_refs() -> None:
    memory = manager.remember("Task context")
    task = manager.add_task("Use context", memory_refs=[memory["memory_id"]])

    deleted = manager.delete_memory(memory["memory_id"])
    updated_task = manager.get_task(task["task_ref"])

    assert deleted["memory_id"] == memory["memory_id"]
    assert updated_task["memory_refs"] == []


def test_delete_parent_memory_clears_child_parent() -> None:
    parent = manager.remember("Parent memory")
    child = manager.remember("Child memory", parent_memory_id=parent["memory_id"])

    manager.delete_memory(parent["memory_id"])
    updated_child = manager.get_memory(child["memory_id"])

    assert updated_child["parent_memory_id"] is None
