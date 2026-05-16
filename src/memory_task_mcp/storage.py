from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEMTASK_HOME_ENV = "MEMTASK_HOME"
MEMTASK_DB_PATH_ENV = "MEMTASK_DB_PATH"


def default_home() -> Path:
    return Path(os.environ.get(MEMTASK_HOME_ENV, Path.home() / ".memtask")).expanduser()


def resolve_default_db_path() -> Path:
    if os.environ.get(MEMTASK_DB_PATH_ENV):
        return Path(os.environ[MEMTASK_DB_PATH_ENV]).expanduser()

    repo_db_path = PROJECT_ROOT / "data" / "tasks.sqlite"
    if repo_db_path.exists():
        return repo_db_path

    return default_home() / "tasks.sqlite"


DEFAULT_DB_PATH = resolve_default_db_path()
DB_PATH = DEFAULT_DB_PATH


def set_db_path(path: str | Path) -> None:
    """Set the SQLite path used by subsequent manager calls."""
    global DB_PATH
    DB_PATH = Path(path)


def get_db_path() -> Path:
    return DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_ref TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                project TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                memory_refs_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                is_current INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
            CREATE INDEX IF NOT EXISTS idx_tasks_is_current ON tasks (is_current);

            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                memory_scope TEXT NOT NULL DEFAULT 'global',
                kind TEXT NOT NULL DEFAULT 'fact',
                confidence INTEGER NOT NULL DEFAULT 100,
                parent_memory_id TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_accessed_at REAL,
                FOREIGN KEY (parent_memory_id) REFERENCES memories (memory_id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories (memory_scope);
            CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories (kind);
            CREATE INDEX IF NOT EXISTS idx_memories_confidence ON memories (confidence);
            CREATE INDEX IF NOT EXISTS idx_memories_parent ON memories (parent_memory_id);

            CREATE TABLE IF NOT EXISTS task_dependencies (
                task_ref TEXT NOT NULL,
                depends_on_task_ref TEXT NOT NULL,
                PRIMARY KEY (task_ref, depends_on_task_ref),
                FOREIGN KEY (task_ref) REFERENCES tasks (task_ref) ON DELETE CASCADE,
                FOREIGN KEY (depends_on_task_ref) REFERENCES tasks (task_ref) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_task_dependencies_task_ref ON task_dependencies (task_ref);
            CREATE INDEX IF NOT EXISTS idx_task_dependencies_depends_on ON task_dependencies (depends_on_task_ref);
            """
        )


def normalize_non_empty_string(value: str, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def normalize_confidence(confidence: int) -> int:
    if isinstance(confidence, bool) or not isinstance(confidence, int):
        raise ValueError("confidence must be an integer between 0 and 100")
    if not 0 <= confidence <= 100:
        raise ValueError("confidence must be between 0 and 100")
    return confidence


def encode_string_list(values: list[str] | None) -> str:
    if values is None:
        return "[]"
    normalized = []
    seen = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return json.dumps(normalized)


def decode_string_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def encode_tags(tags: list[str] | None) -> str:
    return encode_string_list(tags)


def decode_tags(value: str | None) -> list[str]:
    return decode_string_list(value)
