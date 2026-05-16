from __future__ import annotations

import sqlite3
import uuid
from time import time
from typing import Any

from .storage import (
    decode_string_list,
    decode_tags,
    encode_string_list,
    encode_tags,
    get_connection,
    init_db,
    normalize_confidence,
    normalize_non_empty_string,
)


def _row_to_task(
    row: sqlite3.Row,
    pending_id: int | None,
    parent_task_refs: list[str] | None,
    child_task_refs: list[str] | None,
) -> dict[str, Any]:
    return {
        "task_ref": row["task_ref"],
        "description": row["description"],
        "project": row["project"],
        "tags": decode_tags(row["tags_json"]),
        "memory_refs": decode_string_list(row["memory_refs_json"]),
        "status": row["status"],
        "is_current": bool(row["is_current"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
        "pending_id": pending_id,
        "parent_task_refs": parent_task_refs or [],
        "child_task_refs": child_task_refs or [],
    }


def _row_to_memory(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "memory_id": row["memory_id"],
        "content": row["content"],
        "memory_scope": row["memory_scope"],
        "kind": row["kind"],
        "confidence": row["confidence"],
        "parent_memory_id": row["parent_memory_id"],
        "tags": decode_tags(row["tags_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_accessed_at": row["last_accessed_at"],
    }


def _fetch_pending_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cursor = conn.execute(
        """
        SELECT task_ref, description, project, tags_json, memory_refs_json, status,
               is_current, created_at, updated_at, completed_at
        FROM tasks
        WHERE status = 'pending'
        ORDER BY created_at ASC, task_ref ASC
        """
    )
    return cursor.fetchall()


def _task_row_by_ref(conn: sqlite3.Connection, task_ref: str) -> sqlite3.Row | None:
    cursor = conn.execute(
        """
        SELECT task_ref, description, project, tags_json, memory_refs_json, status,
               is_current, created_at, updated_at, completed_at
        FROM tasks
        WHERE task_ref = ?
        """,
        (task_ref,),
    )
    return cursor.fetchone()


def _task_row_by_pending_id(conn: sqlite3.Connection, pending_id: int) -> sqlite3.Row | None:
    if pending_id < 1:
        return None
    rows = _fetch_pending_rows(conn)
    if pending_id > len(rows):
        return None
    return rows[pending_id - 1]


def _memory_row_by_id(conn: sqlite3.Connection, memory_id: str) -> sqlite3.Row | None:
    cursor = conn.execute(
        """
        SELECT memory_id, content, memory_scope, kind, confidence, parent_memory_id, tags_json,
               created_at, updated_at, last_accessed_at
        FROM memories
        WHERE memory_id = ?
        """,
        (memory_id,),
    )
    return cursor.fetchone()


def _resolve_task_identifier(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    # Prefer stable task_ref/uuid, then fallback to pending_id for compatibility.
    by_ref = _task_row_by_ref(conn, task_id)
    if by_ref is not None:
        return by_ref

    try:
        numeric_id = int(task_id)
    except (TypeError, ValueError):
        raise ValueError(f"Task '{task_id}' not found")

    by_pending = _task_row_by_pending_id(conn, numeric_id)
    if by_pending is not None:
        return by_pending

    raise ValueError(f"Task '{task_id}' not found")


def _resolve_pending_task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    row = _resolve_task_identifier(conn, task_id)
    if row["status"] != "pending":
        raise ValueError(f"Task '{task_id}' is not pending")
    return row


def _resolve_memory_identifier(conn: sqlite3.Connection, memory_id: str) -> sqlite3.Row:
    memory_id = normalize_non_empty_string(memory_id, "memory_id")
    row = _memory_row_by_id(conn, memory_id)
    if row is None:
        raise ValueError(f"Memory '{memory_id}' not found")
    return row


def _find_row_index(rows: list[sqlite3.Row], task_ref: str) -> int:
    for index, row in enumerate(rows):
        if row["task_ref"] == task_ref:
            return index
    return -1


def _resolve_task_refs(conn: sqlite3.Connection, refs: list[str] | None) -> list[str]:
    if not refs:
        return []

    task_refs = []
    seen = set()
    for ref in refs:
        if not str(ref).strip():
            continue
        row = _resolve_task_identifier(conn, str(ref).strip())
        task_ref = row["task_ref"]
        if task_ref in seen:
            continue
        seen.add(task_ref)
        task_refs.append(task_ref)
    return task_refs


def _resolve_memory_refs(conn: sqlite3.Connection, refs: list[str] | None) -> list[str]:
    if not refs:
        return []

    memory_refs = []
    seen = set()
    for memory_ref in refs:
        if not str(memory_ref).strip():
            continue
        row = _resolve_memory_identifier(conn, str(memory_ref).strip())
        memory_ref_value = row["memory_id"]
        if memory_ref_value in seen:
            continue
        seen.add(memory_ref_value)
        memory_refs.append(memory_ref_value)
    return memory_refs


def _dependency_map(
    conn: sqlite3.Connection,
    task_refs: list[str],
    source_column: str,
    target_column: str,
) -> dict[str, list[str]]:
    if not task_refs:
        return {}

    qmarks = ",".join("?" * len(task_refs))
    query = f"""
        SELECT {source_column}, {target_column}
        FROM task_dependencies
        WHERE {source_column} IN ({qmarks})
        ORDER BY {target_column} ASC
    """
    rows = conn.execute(query, task_refs).fetchall()

    mapping: dict[str, list[str]] = {task_ref: [] for task_ref in task_refs}
    for row in rows:
        mapping[row[source_column]].append(row[target_column])
    return mapping


def _attach_dependencies(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    include_pending_ids: bool = False,
) -> list[dict[str, Any]]:
    task_refs = [row["task_ref"] for row in rows]
    if not task_refs:
        return []

    parent_map = _dependency_map(
        conn=conn,
        task_refs=task_refs,
        source_column="task_ref",
        target_column="depends_on_task_ref",
    )
    child_map = _dependency_map(
        conn=conn,
        task_refs=task_refs,
        source_column="depends_on_task_ref",
        target_column="task_ref",
    )

    payload = []
    for index, row in enumerate(rows):
        task_ref = row["task_ref"]
        pending_id = index + 1 if include_pending_ids else None
        payload.append(
            _row_to_task(
                row=row,
                pending_id=pending_id,
                parent_task_refs=parent_map.get(task_ref, []),
                child_task_refs=child_map.get(task_ref, []),
            )
        )
    return payload


def _attach_task_dependencies(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    pending_id: int | None = None,
) -> dict[str, Any]:
    pending_refs = [row["task_ref"]]
    parent_map = _dependency_map(
        conn=conn,
        task_refs=pending_refs,
        source_column="task_ref",
        target_column="depends_on_task_ref",
    )
    child_map = _dependency_map(
        conn=conn,
        task_refs=pending_refs,
        source_column="depends_on_task_ref",
        target_column="task_ref",
    )
    task_ref = row["task_ref"]
    return _row_to_task(
        row=row,
        pending_id=pending_id,
        parent_task_refs=parent_map.get(task_ref, []),
        child_task_refs=child_map.get(task_ref, []),
    )


def _check_dependency_blockers(conn: sqlite3.Connection, task_ref: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT td.task_ref
        FROM task_dependencies td
        JOIN tasks t ON t.task_ref = td.task_ref
        WHERE td.depends_on_task_ref = ? AND t.status != 'completed'
        ORDER BY td.task_ref
        """,
        (task_ref,),
    ).fetchall()
    return [row["task_ref"] for row in rows]


def _add_dependency_links(
    conn: sqlite3.Connection,
    task_ref: str,
    parent_task_refs: list[str],
) -> None:
    if not parent_task_refs:
        return
    cursor = conn.cursor()
    for parent_ref in parent_task_refs:
        cursor.execute(
            """
            INSERT OR IGNORE INTO task_dependencies (task_ref, depends_on_task_ref)
            VALUES (?, ?)
            """,
            (task_ref, parent_ref),
        )


def _remove_dependency_links(conn: sqlite3.Connection, task_ref: str) -> None:
    conn.execute(
        "DELETE FROM task_dependencies WHERE task_ref = ? OR depends_on_task_ref = ?",
        (task_ref, task_ref),
    )


def _remove_memory_refs_from_tasks(conn: sqlite3.Connection, memory_id: str) -> list[str]:
    affected_refs = []
    rows = conn.execute("SELECT task_ref, memory_refs_json FROM tasks").fetchall()
    for row in rows:
        memory_refs = decode_string_list(row["memory_refs_json"])
        if memory_id not in memory_refs:
            continue
        updated_refs = [ref for ref in memory_refs if ref != memory_id]
        conn.execute(
            """
            UPDATE tasks
            SET memory_refs_json = ?
            WHERE task_ref = ?
            """,
            (encode_string_list(updated_refs), row["task_ref"]),
        )
        affected_refs.append(row["task_ref"])
    return affected_refs


def _touch_memory_access(conn: sqlite3.Connection, memory_id: str) -> None:
    now = time()
    conn.execute(
        """
        UPDATE memories
        SET last_accessed_at = ?
        WHERE memory_id = ?
        """,
        (now, memory_id),
    )


def list_tasks() -> list[dict[str, Any]]:
    """Return all pending tasks with stable task_ref and ephemeral pending_id values."""
    with get_connection() as conn:
        rows = _fetch_pending_rows(conn)
        return _attach_dependencies(conn, rows, include_pending_ids=True)


def current_tasks() -> list[dict[str, Any]]:
    """Return currently active pending tasks."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT task_ref, description, project, tags_json, memory_refs_json, status,
                   is_current, created_at, updated_at, completed_at
            FROM tasks
            WHERE status = 'pending' AND is_current = 1
            ORDER BY created_at ASC, task_ref ASC
            """
        ).fetchall()
        return _attach_dependencies(conn, rows, include_pending_ids=True)


def get_task(task_id: str) -> dict[str, Any]:
    """Return a task by task_ref/UUID or pending numeric id."""
    with get_connection() as conn:
        row = _resolve_task_identifier(conn, task_id)
        pending_id = None
        if row["status"] == "pending":
            pending_rows = _fetch_pending_rows(conn)
            pending_id = _find_row_index(pending_rows, row["task_ref"]) + 1
            if pending_id == 0:
                pending_id = None
        return _attach_task_dependencies(conn, row, pending_id=pending_id)


def add_task(
    description: str,
    project: str | None = None,
    tags: list[str] | None = None,
    parent_task_refs: list[str] | None = None,
    memory_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Add one pending task and return the created task record."""
    description = normalize_non_empty_string(description, "description")
    task_ref = str(uuid.uuid4())
    now = time()
    with get_connection() as conn:
        resolved_parents = _resolve_task_refs(conn, parent_task_refs)
        resolved_memories = _resolve_memory_refs(conn, memory_refs)
        conn.execute(
            """
            INSERT INTO tasks (task_ref, description, project, tags_json, memory_refs_json,
                               status, is_current, created_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, NULL)
            """,
            (
                task_ref,
                description,
                project,
                encode_tags(tags),
                encode_string_list(resolved_memories),
                now,
                now,
            ),
        )
        _add_dependency_links(conn, task_ref, resolved_parents)
    return get_task(task_ref)


def add_batch_tasks(
    descriptions: list[str],
    project: str | None = None,
    tags: list[str] | None = None,
    parent_task_refs: list[str] | None = None,
    memory_refs: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Add multiple pending tasks and return created records."""
    if not descriptions:
        return []
    created_refs: list[str] = []
    now = time()
    with get_connection() as conn:
        resolved_parents = _resolve_task_refs(conn, parent_task_refs)
        resolved_memories = _resolve_memory_refs(conn, memory_refs)
        cursor = conn.cursor()
        for index, description in enumerate(descriptions):
            if not str(description).strip():
                raise ValueError(f"Description at index {index} is required")
            task_ref = str(uuid.uuid4())
            created_refs.append(task_ref)
            cursor.execute(
                """
                INSERT INTO tasks (task_ref, description, project, tags_json, memory_refs_json,
                                   status, is_current, created_at, updated_at, completed_at)
                VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, NULL)
                """,
                (
                    task_ref,
                    str(description).strip(),
                    project,
                    encode_tags(tags),
                    encode_string_list(resolved_memories),
                    now,
                    now,
                ),
            )
            _add_dependency_links(cursor.connection, task_ref, resolved_parents)
        conn.commit()

    tasks = []
    for task_ref in created_refs:
        tasks.append(get_task(task_ref))
    return tasks


def complete_task(task_id: str) -> dict[str, Any]:
    """Mark a pending task completed."""
    now = time()
    with get_connection() as conn:
        row = _resolve_pending_task(conn, task_id)

        blockers = _check_dependency_blockers(conn, row["task_ref"])
        if blockers:
            raise ValueError(
                f"Cannot complete task '{task_id}'. It has incomplete child tasks: {blockers}"
            )

        conn.execute(
            """
            UPDATE tasks
            SET status = 'completed', is_current = 0, updated_at = ?, completed_at = ?
            WHERE task_ref = ?
            """,
            (now, now, row["task_ref"]),
        )
        conn.commit()
        completed = _task_row_by_ref(conn, row["task_ref"])
        if completed is None:
            raise RuntimeError("Failed to fetch completed task")
        return _attach_task_dependencies(conn, completed, pending_id=None)


def remove_task(task_id: str) -> dict[str, Any]:
    """Delete a task by task_ref/UUID or pending numeric id."""
    with get_connection() as conn:
        row = _resolve_task_identifier(conn, task_id)
        dep_map = _attach_task_dependencies(conn, row, pending_id=None)
        _remove_dependency_links(conn, row["task_ref"])
        conn.execute("DELETE FROM tasks WHERE task_ref = ?", (row["task_ref"],))
        conn.commit()
    return dep_map


def remove_all_tasks() -> dict[str, Any]:
    """Delete all pending tasks currently returned by list_tasks."""
    tasks = list_tasks()
    removed = []
    failed = []
    for task in tasks:
        task_id = task.get("task_ref") or task.get("pending_id")
        if not task_id:
            failed.append({"task": task, "error": "Could not resolve a task identifier."})
            continue
        try:
            removed.append(remove_task(str(task_id)))
        except Exception as exc:
            failed.append({"task_id": task_id, "error": str(exc)})

    return {
        "attempted_count": len(tasks),
        "removed_count": len(removed),
        "removed": removed,
        "failed": failed,
    }


def set_current_task(task_id: str) -> dict[str, Any]:
    """Mark a pending task as current and unset any other current pending task."""
    now = time()
    with get_connection() as conn:
        row = _resolve_pending_task(conn, task_id)
        conn.execute("UPDATE tasks SET is_current = 0 WHERE status = 'pending'")
        conn.execute(
            "UPDATE tasks SET is_current = 1, updated_at = ? WHERE task_ref = ?",
            (now, row["task_ref"]),
        )
        conn.commit()
        updated = _task_row_by_ref(conn, row["task_ref"])
    if updated is None:
        raise RuntimeError("Failed to fetch updated task")
    return get_task(updated["task_ref"])


def remember(
    content: str,
    memory_scope: str | None = None,
    kind: str | None = None,
    confidence: int = 100,
    parent_memory_id: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Add a memory artifact for recall and couple to higher-level memory structures."""
    content = normalize_non_empty_string(content, "content")
    scope = normalize_non_empty_string(memory_scope or "global", "memory_scope")
    normalized_kind = normalize_non_empty_string(kind or "fact", "kind")
    confidence = normalize_confidence(confidence)
    now = time()

    with get_connection() as conn:
        if parent_memory_id is not None:
            parent_memory_id = _resolve_memory_identifier(
                conn=conn,
                memory_id=parent_memory_id.strip(),
            )["memory_id"]

        memory_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO memories (
                memory_id, content, memory_scope, kind, confidence, parent_memory_id,
                tags_json, created_at, updated_at, last_accessed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                memory_id,
                content,
                scope,
                normalized_kind,
                confidence,
                parent_memory_id,
                encode_tags(tags),
                now,
                now,
            ),
        )
        row = _memory_row_by_id(conn, memory_id)
    if row is None:
        raise RuntimeError("Failed to fetch created memory")
    return _row_to_memory(row)


def recall(
    query: str | None = None,
    memory_scope: str | None = None,
    kind: str | None = None,
    min_confidence: int | None = None,
    parent_memory_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Recall memories with optional filtering."""
    clauses = []
    params: list[Any] = []

    if query is not None and str(query).strip():
        clauses.append("LOWER(content) LIKE ?")
        params.append(f"%{str(query).strip().lower()}%")

    if memory_scope is not None:
        clauses.append("memory_scope = ?")
        params.append(normalize_non_empty_string(memory_scope, "memory_scope"))

    if kind is not None:
        clauses.append("kind = ?")
        params.append(normalize_non_empty_string(kind, "kind"))

    if min_confidence is not None:
        clauses.append("confidence >= ?")
        params.append(normalize_confidence(min_confidence))

    if parent_memory_id is not None:
        parent_memory_id = normalize_non_empty_string(parent_memory_id, "parent_memory_id")
        with get_connection() as conn:
            _resolve_memory_identifier(conn, parent_memory_id)
        clauses.append("parent_memory_id = ?")
        params.append(parent_memory_id)

    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        "SELECT memory_id, content, memory_scope, kind, confidence, parent_memory_id, "
        "tags_json, created_at, updated_at, last_accessed_at FROM memories "
        f"{where} ORDER BY confidence DESC, updated_at DESC"
    )
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        payload = [_row_to_memory(row) for row in rows]
        memory_ids = [row["memory_id"] for row in rows]
        if memory_ids:
            now = time()
            placeholders = ",".join("?" * len(memory_ids))
            conn.execute(
                f"UPDATE memories SET last_accessed_at = ? WHERE memory_id IN ({placeholders})",
                [now] + memory_ids,
            )
            conn.commit()
            for memory in payload:
                memory["last_accessed_at"] = now
        return payload


def get_memory(memory_id: str) -> dict[str, Any]:
    """Return a memory by stable id and refresh last_accessed."""
    with get_connection() as conn:
        row = _resolve_memory_identifier(conn, memory_id)
        _touch_memory_access(conn, row["memory_id"])
        conn.commit()
        updated = _memory_row_by_id(conn, row["memory_id"])
    if updated is None:
        raise RuntimeError("Failed to fetch memory")
    return _row_to_memory(updated)


def update_memory(
    memory_id: str,
    content: str | None = None,
    memory_scope: str | None = None,
    kind: str | None = None,
    confidence: int | None = None,
    parent_memory_id: str | None = None,
    tags: list[str] | None = None,
    clear_parent: bool = False,
) -> dict[str, Any]:
    """Update selected fields of a memory."""
    if clear_parent and parent_memory_id is not None:
        raise ValueError("Cannot set parent_memory_id and clear_parent at the same time")

    updates: list[str] = []
    params: list[Any] = []

    if content is not None:
        updates.append("content = ?")
        params.append(normalize_non_empty_string(content, "content"))

    if memory_scope is not None:
        updates.append("memory_scope = ?")
        params.append(normalize_non_empty_string(memory_scope, "memory_scope"))

    if kind is not None:
        updates.append("kind = ?")
        params.append(normalize_non_empty_string(kind, "kind"))

    if confidence is not None:
        updates.append("confidence = ?")
        params.append(normalize_confidence(confidence))

    if clear_parent:
        updates.append("parent_memory_id = NULL")
    elif parent_memory_id is not None:
        updates.append("parent_memory_id = ?")
        params.append(normalize_non_empty_string(parent_memory_id, "parent_memory_id"))

    if tags is not None:
        updates.append("tags_json = ?")
        params.append(encode_tags(tags))

    if not updates:
        raise ValueError("No fields supplied for update")

    updates.append("updated_at = ?")
    params.append(time())

    with get_connection() as conn:
        if clear_parent is False and parent_memory_id is not None:
            parent_row = _resolve_memory_identifier(conn, parent_memory_id)
            if parent_row["memory_id"] == memory_id:
                raise ValueError("A memory cannot be its own parent")

        updates_sql = ", ".join(updates)
        row = _resolve_memory_identifier(conn, memory_id)
        memory_id_value = row["memory_id"]
        conn.execute(
            f"UPDATE memories SET {updates_sql} WHERE memory_id = ?",
            (*params, memory_id_value),
        )
        conn.commit()
        updated = _memory_row_by_id(conn, memory_id_value)
    if updated is None:
        raise RuntimeError("Failed to fetch updated memory")
    return _row_to_memory(updated)


def delete_memory(memory_id: str) -> dict[str, Any]:
    """Delete a memory by stable id."""
    with get_connection() as conn:
        row = _resolve_memory_identifier(conn, memory_id)
        _remove_memory_refs_from_tasks(conn, row["memory_id"])
        conn.execute(
            "UPDATE memories SET parent_memory_id = NULL WHERE parent_memory_id = ?",
            (row["memory_id"],),
        )
        conn.execute("DELETE FROM memories WHERE memory_id = ?", (row["memory_id"],))
        conn.commit()
    return _row_to_memory(row)


init_db()
