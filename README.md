<p align="center">
  <img src="docs/assets/memtask-logo.png" alt="MemTask logo" width="220">
</p>

<h1 align="center">MemTask</h1>

MemTask is a local MCP server for developer-built agents that need durable task state and lightweight memory. It combines task planning, dependency tracking, active work selection, completion history, and scoped memories in a small SQLite-backed service. The goal is to give agents a structured place to manage agency: what to do next, what depends on what, and what context should persist across sessions.

## What It Provides

MemTask exposes two local primitives over MCP:

- Tasks: pending work, stable task references, parent/child dependency edges, active task selection, and completed task state.
- Memories: scoped pieces of context with confidence scores, optional parent memory relationships, tags, and task-memory references.

The server is intentionally local-first. State lives in SQLite, the tool surface is small, and the manager layer can be tested directly without running an MCP transport.

## Quickstart

Install MemTask:

```bash
pip install MemTask
```

Then ask MemTask for the MCP config to add to your agent:

```bash
memtask install-help
```

Most MCP clients should launch MemTask over stdio:

```bash
memtask start --transport stdio
```

If your client connects to a running HTTP server instead, start it in the background:

```bash
memtask start --transport http --host 127.0.0.1 --port 8000
```

For local development from this repo:

```bash
PYTHONPATH=src python -m memtask start --transport stdio
```

Useful HTTP commands: `memtask status` and `memtask stop`.

## Storage

Runtime state in this repo is stored in `data/tasks.sqlite`.

When installed outside this repo, MemTask uses `~/.memtask/tasks.sqlite` by default. Set `MEMTASK_DB_PATH` to choose a specific SQLite path.

The server creates the required SQLite tables on startup using `CREATE TABLE IF NOT EXISTS`. There is no migration framework.

## Tools

Task tools:

- `list_tasks`
- `get_task`
- `add_task`
- `add_batch_tasks`
- `complete_task`
- `remove_task`
- `remove_all_tasks`
- `current_tasks`
- `set_current_task`

Memory tools:

- `remember`
- `recall`
- `get_memory`
- `update_memory`
- `delete_memory`

## Development

Run tests:

```bash
python -m pytest
```

Compile-check the package:

```bash
python -m py_compile src/memtask/*.py tests/*.py
```
