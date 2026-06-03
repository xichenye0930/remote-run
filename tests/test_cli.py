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


def test_init_adds_config_to_existing_gitignore(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(".venv/", encoding="utf-8")

    exit_code = cli.main(["init"])

    assert exit_code == 0
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == (
        ".venv/\n.rrun.toml\n"
    )
    output = capsys.readouterr().out
    assert "created .rrun.toml" in output
    assert "added .rrun.toml to .gitignore" in output


def test_init_does_not_duplicate_existing_gitignore_entry(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(".rrun.toml\n", encoding="utf-8")

    exit_code = cli.main(["init"])

    assert exit_code == 0
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".rrun.toml\n"
    assert "added .rrun.toml" not in capsys.readouterr().out


def test_init_leaves_missing_gitignore_absent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["init"])

    assert exit_code == 0
    assert not (tmp_path / ".gitignore").exists()


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
