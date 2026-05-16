<p align="center">
  <img src="https://raw.githubusercontent.com/PlatinumCD/memtask-mcp/master/docs/assets/memtask-logo.png" alt="MemTask logo" width="220">
</p>

<h1 align="center">MemTask</h1>

MemTask gives MCP agents a local task list and lightweight memory, backed by SQLite.

## Install

```bash
pip install MemTask
```

## Start

```bash
memtask start
```

MemTask starts a local MCP server at:

```text
http://127.0.0.1:8000/mcp
```

## Add It To Codex

```bash
memtask install
```

That prints the exact `codex mcp add ...` commands for stdio and HTTP:

```text
Codex

stdio server
  codex mcp add memtask -- memtask start --transport stdio

HTTP server
  memtask start
  codex mcp add memtask --url http://127.0.0.1:8000/mcp
```

## Use It

Once connected, your agent gets tools for:

- tasks: add, list, focus, complete, remove, and track dependencies
- memory: remember, recall, update, and delete scoped context

## Common Commands

```bash
memtask status
memtask stop
memtask start --transport stdio
```

## What It Is

MemTask is a local MCP server for developer-built agents that need durable task state and persistent context. It gives an agent a small workspace for tracking active work, dependency order, completed tasks, and scoped memories across sessions.

State is stored locally. In this repo, MemTask uses `data/tasks.sqlite`. When installed outside this repo, it uses `~/.memtask/tasks.sqlite` by default. Set `MEMTASK_DB_PATH` to choose a specific SQLite path.

## Development

Run tests:

```bash
python -m pytest
```

Compile-check the package:

```bash
python -m py_compile src/memtask/*.py tests/*.py
```
