import subprocess
from pathlib import Path
from unittest.mock import Mock

from remote_run import cli
from remote_run.config import sample_config


def test_init_creates_config(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["init"])

    assert exit_code == 0
    assert (tmp_path / ".rrun.toml").read_text(encoding="utf-8") == sample_config()
    assert "created" in capsys.readouterr().out


def test_passthrough_syncs_then_submits(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".rrun.toml").write_text(
        'target = "user@gpu"\nremote_workdir = "/remote/project"\n',
        encoding="utf-8",
    )
    sync_project = Mock()
    submit_job = Mock(return_value="job-1")
    monkeypatch.setattr(cli, "sync_project", sync_project)
    monkeypatch.setattr(cli, "submit_job", submit_job)

    exit_code = cli.main(["--", "python", "train.py"])

    assert exit_code == 0
    sync_project.assert_called_once()
    submit_job.assert_called_once()
    assert submit_job.call_args.args[1] == ["python", "train.py"]
    assert capsys.readouterr().out.strip() == "job-1"


def test_passthrough_returns_subprocess_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".rrun.toml").write_text(
        'target = "user@gpu"\nremote_workdir = "/remote/project"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "sync_project",
        Mock(side_effect=subprocess.CalledProcessError(12, ["rsync"])),
    )

    assert cli.main(["--", "python", "train.py"]) == 12
    assert "exit code 12" in capsys.readouterr().err


def test_passthrough_rejects_prefix_args(capsys) -> None:
    assert cli.main(["run", "--", "python", "train.py"]) == 2
    assert "rrun -- <command>" in capsys.readouterr().err
