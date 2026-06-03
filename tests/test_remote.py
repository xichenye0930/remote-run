import json
import subprocess
from unittest.mock import Mock

from remote_run.config import Config
from remote_run.remote import (
    RemoteOutputError,
    build_ssh_command,
    build_submit_script,
    fetch_status,
    _parse_status_json,
    submit_job,
)


def test_build_ssh_command_uses_port() -> None:
    config = Config(target="user@gpu", remote_workdir="/remote/project", port=2222)

    assert build_ssh_command(config, "echo ok") == [
        "ssh",
        "-o",
        "LogLevel=ERROR",
        "-p",
        "2222",
        "user@gpu",
        "bash",
        "-c",
        "echo ok",
    ]


def test_build_submit_script_writes_prelude_and_command() -> None:
    config = Config(
        target="user@gpu",
        remote_workdir="/remote/project",
        prelude="source env",
    )

    script = build_submit_script(config, "job-1", ["python", "train.py", "--epochs", "1"])

    assert "mkdir -p /remote/project/.rrun/jobs/job-1" in script
    assert "source env" in script
    assert "python train.py --epochs 1" in script
    assert "nohup bash -lc" in script


def test_submit_job_invokes_ssh(monkeypatch) -> None:
    config = Config(target="user@gpu", remote_workdir="/remote/project")
    run = Mock()
    monkeypatch.setattr("remote_run.remote.make_job_id", lambda: "job-1")
    monkeypatch.setattr(subprocess, "run", run)

    job_id = submit_job(config, ["python", "train.py"])

    assert job_id == "job-1"
    run.assert_called_once()
    assert run.call_args.args[0][0] == "ssh"
    assert run.call_args.kwargs["stdout"] == subprocess.PIPE
    assert "stderr" not in run.call_args.kwargs


def test_fetch_status_parses_remote_json(monkeypatch) -> None:
    config = Config(target="user@gpu", remote_workdir="/remote/project")
    result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps(
            {
                "state": "succeeded",
                "pid": "123",
                "exit_code": 0,
                "started_at": "2026-01-01T00:00:00Z",
                "ended_at": "2026-01-01T00:00:01Z",
            }
        ),
    )
    monkeypatch.setattr(subprocess, "run", Mock(return_value=result))

    status = fetch_status(config, "job-1")

    assert status.state == "succeeded"
    assert status.pid == "123"
    assert status.exit_code == 0


def test_fetch_status_parses_json_after_noisy_output(monkeypatch) -> None:
    config = Config(target="user@gpu", remote_workdir="/remote/project")
    result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='\n'.join(
            [
                "BASH=/bin/bash",
                "CUDA_VERSION=11.6.2",
                '{"state":"running","pid":"123","started_at":"2026-01-01T00:00:00Z"}',
            ]
        ),
    )
    monkeypatch.setattr(subprocess, "run", Mock(return_value=result))

    status = fetch_status(config, "job-1")

    assert status.state == "running"
    assert status.pid == "123"


def test_parse_status_json_reports_missing_json() -> None:
    try:
        _parse_status_json("BASH=/bin/bash\nCUDA_VERSION=11.6.2\n")
    except RemoteOutputError as exc:
        assert "did not contain JSON" in str(exc)
    else:
        raise AssertionError("expected ValueError")
