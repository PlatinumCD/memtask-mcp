from __future__ import annotations

import json

from memory_task_mcp import cli


def test_install_help_prints_stdio_and_http_config(capsys) -> None:
    cli.main(["install-help", "--host", "127.0.0.1", "--port", "9000"])

    output = capsys.readouterr().out

    assert "MemTask MCP configuration examples" in output
    assert '"command": "memtask"' in output
    assert '"args": [' in output
    assert "http://127.0.0.1:9000/mcp" in output


def test_start_stdio_prints_guidance_to_stderr(monkeypatch, capsys) -> None:
    called = {}

    def fake_run_server(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(cli, "run_server", fake_run_server)

    cli.main(["start", "--transport", "stdio", "--server-name", "TestTask"])

    captured = capsys.readouterr()

    assert captured.out == ""
    assert "MemTask starting over stdio." in captured.err
    assert '"command": "memtask"' in captured.err
    assert called["transport"] == "stdio"
    assert called["server_name"] == "TestTask"


def test_start_http_spawns_background_process(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("MEMTASK_HOME", str(tmp_path))

    captured_command = {}

    class FakeProcess:
        pid = 12345

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        captured_command["command"] = command
        captured_command["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)

    cli.main(["start", "--transport", "http", "--host", "127.0.0.1", "--port", "9001"])

    output = capsys.readouterr().out
    pid_record = json.loads((tmp_path / "memtask.pid").read_text())

    assert "MemTask HTTP server started." in output
    assert "http://127.0.0.1:9001/mcp" in output
    assert pid_record["pid"] == 12345
    assert pid_record["transport"] == "streamable-http"
    assert captured_command["command"][:3] == [
        cli.sys.executable,
        "-m",
        "memory_task_mcp.app",
    ]


def test_stop_without_pid_explains_stdio(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("MEMTASK_HOME", str(tmp_path))

    cli.main(["stop"])

    output = capsys.readouterr().out

    assert "No MemTask background server is registered." in output
    assert "stdio mode" in output


def test_status_without_pid_points_to_install_help(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("MEMTASK_HOME", str(tmp_path))

    cli.main(["status"])

    output = capsys.readouterr().out

    assert "not running" in output
    assert "memtask install-help" in output
