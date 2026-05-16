from __future__ import annotations

import json

from memtask import cli


def test_no_args_prints_clean_help(capsys) -> None:
    cli.main([])

    output = capsys.readouterr().out

    assert "Usage" in output
    assert "memtask start" in output
    assert "argparse" not in output


def test_install_prints_codex_commands_when_not_running(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("MEMTASK_HOME", str(tmp_path))

    cli.main(["install", "--host", "127.0.0.1", "--port", "9000"])

    output = capsys.readouterr().out

    assert output == (
        "Codex\n"
        "\n"
        "stdio server\n"
        "  codex mcp add memtask -- memtask start --transport stdio\n"
        "\n"
        "HTTP server\n"
        "  memtask start\n"
        "  codex mcp add memtask --url http://127.0.0.1:9000/mcp\n"
    )


def test_install_uses_running_http_url(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("MEMTASK_HOME", str(tmp_path))
    (tmp_path / "memtask.pid").write_text(
        json.dumps(
            {
                "pid": 12345,
                "url": "http://127.0.0.1:9100/mcp",
            }
        )
    )
    monkeypatch.setattr(cli, "_pid_is_running", lambda pid: True)

    cli.main(["install"])

    output = capsys.readouterr().out

    assert "memtask start\n" not in output
    assert "codex mcp add memtask --url http://127.0.0.1:9100/mcp" in output


def test_start_stdio_prints_guidance_to_stderr(monkeypatch, capsys) -> None:
    called = {}

    def fake_run_server(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(cli, "_run_server", fake_run_server)

    cli.main(["start", "--transport", "stdio", "--server-name", "TestTask"])

    captured = capsys.readouterr()

    assert captured.out == ""
    assert "MemTask starting over stdio" in captured.err
    assert "mcpServers" not in captured.err
    assert called["transport"] == "stdio"
    assert called["server_name"] == "TestTask"


def test_start_defaults_to_background_http(monkeypatch, tmp_path, capsys) -> None:
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

    cli.main(["start", "--host", "127.0.0.1", "--port", "9001"])

    output = capsys.readouterr().out
    pid_record = json.loads((tmp_path / "memtask.pid").read_text())

    assert "OK MemTask started" in output
    assert "http://127.0.0.1:9001/mcp" in output
    assert pid_record["pid"] == 12345
    assert pid_record["transport"] == "streamable-http"
    assert captured_command["command"][:3] == [
        cli.sys.executable,
        "-m",
        "memtask.app",
    ]


def test_stop_without_pid_explains_stdio(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("MEMTASK_HOME", str(tmp_path))

    cli.main(["stop"])

    output = capsys.readouterr().out

    assert "MemTask background server is not registered." not in output
    assert "not running" in output
    assert "stdio" in output


def test_status_without_pid_points_to_install_help(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("MEMTASK_HOME", str(tmp_path))

    cli.main(["status"])

    output = capsys.readouterr().out

    assert "MemTask is not running" in output
    assert "memtask start" in output
