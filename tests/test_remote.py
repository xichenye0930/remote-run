import json
import subprocess
from unittest.mock import Mock

from remote_run.config import Config
from remote_run.remote import (
    RemoteOutputError,
    build_cancel_script,
    build_ssh_command,
    build_submit_script,
    cancel_job,
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
    assert "nohup setsid bash -lc" in script


def test_build_cancel_script_targets_process_group_by_default() -> None:
    config = Config(target="user@gpu", remote_workdir="/remote/project")

    script = build_cancel_script(config, "job-1", force=False)

    assert "signal=TERM" in script
    assert "pgrep -P" in script
    assert "rrun_descendants" in script
    assert 'rrun_kill_tree "$pid" "$signal" "$job_dir/children"' in script
    assert 'known="$(cat "$children_file")"' in script
    assert "sleep 1" in script
    assert "sort -u" in script
    assert "tac" in script
    assert 'kill -s "$signal" -- "-$pid"' in script
    assert 'kill -s "$signal" "$pid"' in script
    assert 'cancel_signal"' in script


def test_build_cancel_script_uses_kill_when_forced() -> None:
    config = Config(target="user@gpu", remote_workdir="/remote/project")

    script = build_cancel_script(config, "job-1", force=True)

    assert "signal=KILL" in script


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


def test_cancel_job_invokes_remote_cancel(monkeypatch) -> None:
    config = Config(target="user@gpu", remote_workdir="/remote/project")
    result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='{"state":"cancelling","pid":"123","cancelled_at":"2026-01-01T00:00:00Z"}',
    )
    run = Mock(return_value=result)
    monkeypatch.setattr(subprocess, "run", run)

    status = cancel_job(config, "job-1", force=True)

    assert status.state == "cancelling"
    assert status.pid == "123"
    assert status.cancelled_at == "2026-01-01T00:00:00Z"
    assert "signal=KILL" in run.call_args.args[0][-1]


def test_fetch_status_parses_cancelled_state(monkeypatch) -> None:
    config = Config(target="user@gpu", remote_workdir="/remote/project")
    result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='{"state":"cancelled","pid":"123","cancelled_at":"2026-01-01T00:00:00Z"}',
    )
    monkeypatch.setattr(subprocess, "run", Mock(return_value=result))

    status = fetch_status(config, "job-1")

    assert status.state == "cancelled"
    assert status.cancelled_at == "2026-01-01T00:00:00Z"


def test_status_script_checks_recorded_children_after_cancel() -> None:
    config = Config(target="user@gpu", remote_workdir="/remote/project")

    script = build_cancel_script(config, "job-1", force=False)

    assert "rrun_live_known_children" in script
    assert 'live_children="$(rrun_live_known_children "$job_dir/children")"' in script
    assert '[ -n "$cancelled_at" ] && [ -n "$live_children" ]' in script


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
