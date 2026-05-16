from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .app import run_server
from .storage import default_home, get_db_path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_SERVER_NAME = "MemTask"
PID_FILE = "memtask.pid"
LOG_FILE = "memtask.log"


def _runtime_dir() -> Path:
    path = default_home()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pid_path() -> Path:
    return _runtime_dir() / PID_FILE


def _log_path() -> Path:
    return _runtime_dir() / LOG_FILE


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid_record() -> dict[str, object] | None:
    path = _pid_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_pid_record(record: dict[str, object]) -> None:
    _pid_path().write_text(json.dumps(record, indent=2, sort_keys=True))


def _clear_pid_record() -> None:
    try:
        _pid_path().unlink()
    except FileNotFoundError:
        pass


def _mcp_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/mcp"


def _stdio_config_text() -> str:
    return json.dumps(
        {
            "mcpServers": {
                "memtask": {
                    "command": "memtask",
                    "args": ["start", "--transport", "stdio"],
                }
            }
        },
        indent=2,
    )


def _http_config_text(host: str, port: int) -> str:
    return json.dumps(
        {
            "mcpServers": {
                "memtask": {
                    "url": _mcp_url(host, port),
                }
            }
        },
        indent=2,
    )


def _print_stdio_guidance() -> None:
    print("MemTask starting over stdio.", file=sys.stderr)
    print("For MCP clients that launch stdio servers, configure:", file=sys.stderr)
    print(_stdio_config_text(), file=sys.stderr)
    print(f"SQLite state: {get_db_path()}", file=sys.stderr)


def _print_http_guidance(host: str, port: int, pid: int | None = None) -> None:
    print("MemTask HTTP server started.")
    if pid is not None:
        print(f"PID: {pid}")
    print(f"URL: {_mcp_url(host, port)}")
    print(f"SQLite state: {get_db_path()}")
    print(f"Log file: {_log_path()}")
    print()
    print("For MCP clients that connect to HTTP servers, configure:")
    print(_http_config_text(host, port))


def _print_install_help(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    print("MemTask MCP configuration examples")
    print()
    print("Stdio launch configuration:")
    print(_stdio_config_text())
    print()
    print("HTTP mode:")
    print(f"  memtask start --transport http --host {host} --port {port}")
    print()
    print("HTTP configuration:")
    print(_http_config_text(host, port))
    print()
    print(f"Default SQLite state: {get_db_path()}")


def _start_stdio(args: argparse.Namespace) -> None:
    _print_stdio_guidance()
    run_server(
        transport="stdio",
        host=args.host,
        port=args.port,
        server_name=args.server_name,
    )


def _start_http(args: argparse.Namespace) -> None:
    record = _read_pid_record()
    if record is not None:
        pid = int(record.get("pid", 0))
        if _pid_is_running(pid):
            print("MemTask HTTP server is already running.")
            print(f"PID: {pid}")
            print(f"URL: {record.get('url', _mcp_url(args.host, args.port))}")
            print(f"Stop it with: memtask stop")
            return
        _clear_pid_record()

    log_handle = _log_path().open("ab")
    command = [
        sys.executable,
        "-m",
        "memtask.app",
        "--transport",
        "streamable-http",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--server-name",
        args.server_name,
    ]
    popen_kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_handle,
        "stderr": log_handle,
        "close_fds": True,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(command, **popen_kwargs)
    finally:
        log_handle.close()
    time.sleep(0.2)
    if process.poll() is not None:
        raise RuntimeError(f"MemTask server exited during startup. See log: {_log_path()}")

    record = {
        "pid": process.pid,
        "transport": "streamable-http",
        "host": args.host,
        "port": args.port,
        "url": _mcp_url(args.host, args.port),
        "log_file": str(_log_path()),
        "db_path": str(get_db_path()),
        "started_at": time.time(),
    }
    _write_pid_record(record)
    _print_http_guidance(args.host, args.port, pid=process.pid)


def _start(args: argparse.Namespace) -> None:
    if args.transport == "stdio":
        _start_stdio(args)
        return
    _start_http(args)


def _stop(_: argparse.Namespace) -> None:
    record = _read_pid_record()
    if record is None:
        print("No MemTask background server is registered.")
        print("If you are using stdio mode, your MCP client starts and stops MemTask itself.")
        return

    pid = int(record.get("pid", 0))
    if not _pid_is_running(pid):
        _clear_pid_record()
        print("Removed stale MemTask PID file.")
        return

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5
    while time.time() < deadline:
        if not _pid_is_running(pid):
            break
        time.sleep(0.1)

    _clear_pid_record()
    print("MemTask HTTP server stopped.")
    print("For stdio MCP clients, no stop command is needed; the client owns the server process.")


def _status(_: argparse.Namespace) -> None:
    record = _read_pid_record()
    if record is None:
        print("MemTask background HTTP server is not running.")
        print(f"SQLite state: {get_db_path()}")
        print("For MCP client setup, run: memtask install-help")
        return

    pid = int(record.get("pid", 0))
    if not _pid_is_running(pid):
        _clear_pid_record()
        print("MemTask background HTTP server is not running. Removed stale PID file.")
        print(f"SQLite state: {get_db_path()}")
        return

    print("MemTask background HTTP server is running.")
    print(f"PID: {pid}")
    print(f"URL: {record.get('url')}")
    print(f"SQLite state: {record.get('db_path', get_db_path())}")
    print(f"Log file: {record.get('log_file', _log_path())}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memtask")
    subcommands = parser.add_subparsers(dest="command", required=True)

    start = subcommands.add_parser("start", help="Start the MemTask MCP server")
    start.add_argument(
        "--transport",
        choices=("stdio", "http", "streamable-http"),
        default="stdio",
        help="Use stdio in the foreground or HTTP as a background server.",
    )
    start.add_argument("--host", default=DEFAULT_HOST)
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--server-name", default=DEFAULT_SERVER_NAME)
    start.set_defaults(handler=_start)

    stop = subcommands.add_parser("stop", help="Stop the background HTTP server")
    stop.set_defaults(handler=_stop)

    status = subcommands.add_parser("status", help="Show background server status")
    status.set_defaults(handler=_status)

    install_help = subcommands.add_parser(
        "install-help",
        help="Print MCP client configuration examples",
    )
    install_help.add_argument("--host", default=DEFAULT_HOST)
    install_help.add_argument("--port", type=int, default=DEFAULT_PORT)
    install_help.set_defaults(
        handler=lambda args: _print_install_help(host=args.host, port=args.port)
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
