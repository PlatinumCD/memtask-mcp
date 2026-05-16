from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .storage import default_home, get_db_path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_SERVER_NAME = "MemTask"
PID_FILE = "memtask.pid"
LOG_FILE = "memtask.log"
COMMANDS = {"start", "stop", "status", "install", "install-help"}


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


def _color(value: str, code: str, stream=None) -> str:
    stream = sys.stdout if stream is None else stream
    if os.environ.get("NO_COLOR") or not stream.isatty():
        return value
    return f"\033[{code}m{value}\033[0m"


def _green(value: str) -> str:
    return _color(value, "32")


def _yellow(value: str) -> str:
    return _color(value, "33")


def _bold_white(value: str) -> str:
    return _color(value, "1;97")


def _bold(value: str) -> str:
    return _color(value, "1")


def _print_main_help() -> None:
    print(_bold("MemTask"))
    print("Local MCP task and memory server")
    print()
    print(_bold("Usage"))
    print("  memtask start [--host 127.0.0.1] [--port 8000]")
    print("  memtask stop")
    print("  memtask status")
    print("  memtask install")
    print()
    print(_bold("Common"))
    print("  memtask start        Start the background HTTP server")
    print("  memtask install      Show Codex MCP install commands")
    print("  memtask status       Show PID, URL, log path, and DB path")
    print()
    print(_bold("Stdio"))
    print("  memtask start --transport stdio")
    print("  Use stdio only when your MCP client launches MemTask directly.")


def _print_stdio_guidance() -> None:
    print("MemTask starting over stdio; this process stays attached to the MCP client.", file=sys.stderr)


def _print_http_guidance(host: str, port: int, pid: int | None = None) -> None:
    print(f"{_green('OK')} MemTask started")
    if pid is not None:
        print(f"  PID:  {pid}")
    print(f"  URL:  {_mcp_url(host, port)}")
    print(f"  Data: {get_db_path()}")
    print(f"  Logs: {_log_path()}")
    print()
    print("Add it to your MCP client with:")
    print("  memtask install")


def _running_http_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> tuple[str, bool]:
    record = _read_pid_record()
    if record is None:
        return _mcp_url(host, port), False

    pid = int(record.get("pid", 0))
    if not _pid_is_running(pid):
        _clear_pid_record()
        return _mcp_url(host, port), False

    return str(record.get("url", _mcp_url(host, port))), True


def _print_install(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    url, running = _running_http_url(host=host, port=port)

    print(_bold_white("Codex"))
    print()
    print("stdio server")
    print("  codex mcp add memtask -- memtask start --transport stdio")
    print()
    print("HTTP server")
    if not running:
        print("  memtask start")
    print(f"  codex mcp add memtask --url {url}")


def _run_server(**kwargs) -> None:
    from .app import run_server

    run_server(**kwargs)


def _start_stdio(args: argparse.Namespace) -> None:
    _print_stdio_guidance()
    _run_server(
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
            print(f"{_yellow('RUNNING')} MemTask is already running")
            print(f"  PID: {pid}")
            print(f"  URL: {record.get('url', _mcp_url(args.host, args.port))}")
            print()
            print("Stop it with:")
            print("  memtask stop")
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
        print(f"{_yellow('STOPPED')} MemTask is not running")
        print("stdio servers are stopped by the MCP client that launched them.")
        return

    pid = int(record.get("pid", 0))
    if not _pid_is_running(pid):
        _clear_pid_record()
        print(f"{_yellow('STALE')} Removed old MemTask PID file.")
        return

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5
    while time.time() < deadline:
        if not _pid_is_running(pid):
            break
        time.sleep(0.1)

    _clear_pid_record()
    print(f"{_green('OK')} MemTask stopped")
    print("stdio servers are stopped by the MCP client that launched them.")


def _status(_: argparse.Namespace) -> None:
    record = _read_pid_record()
    if record is None:
        print(f"{_yellow('STOPPED')} MemTask is not running")
        print(f"  Data: {get_db_path()}")
        print()
        print("Start it with:")
        print("  memtask start")
        return

    pid = int(record.get("pid", 0))
    if not _pid_is_running(pid):
        _clear_pid_record()
        print(f"{_yellow('STALE')} MemTask was not running; removed old PID file.")
        print(f"  Data: {get_db_path()}")
        return

    print(f"{_green('RUNNING')} MemTask")
    print(f"  PID:  {pid}")
    print(f"  URL:  {record.get('url')}")
    print(f"  Data: {record.get('db_path', get_db_path())}")
    print(f"  Logs: {record.get('log_file', _log_path())}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memtask", add_help=False)
    subcommands = parser.add_subparsers(dest="command")

    start = subcommands.add_parser("start", help="Start the MemTask MCP server")
    start.add_argument(
        "--transport",
        choices=("stdio", "http", "streamable-http"),
        default="http",
        help="Use HTTP as a background server, or stdio when launched by an MCP client.",
    )
    start.add_argument("--host", default=DEFAULT_HOST)
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--server-name", default=DEFAULT_SERVER_NAME)
    start.set_defaults(handler=_start)

    stop = subcommands.add_parser("stop", help="Stop the background HTTP server")
    stop.set_defaults(handler=_stop)

    status = subcommands.add_parser("status", help="Show background server status")
    status.set_defaults(handler=_status)

    install = subcommands.add_parser("install", help="Show Codex MCP install commands")
    install.add_argument("--host", default=DEFAULT_HOST)
    install.add_argument("--port", type=int, default=DEFAULT_PORT)
    install.set_defaults(handler=lambda args: _print_install(host=args.host, port=args.port))

    install_help = subcommands.add_parser("install-help", help=argparse.SUPPRESS)
    install_help.add_argument("--host", default=DEFAULT_HOST)
    install_help.add_argument("--port", type=int, default=DEFAULT_PORT)
    install_help.set_defaults(handler=lambda args: _print_install(host=args.host, port=args.port))

    return parser


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv in (["-h"], ["--help"]):
        _print_main_help()
        return

    if argv[0] not in COMMANDS:
        print(f"Unknown command: {argv[0]}", file=sys.stderr)
        print("Run `memtask --help` for usage.", file=sys.stderr)
        raise SystemExit(2)

    parser = build_parser()
    args = parser.parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
