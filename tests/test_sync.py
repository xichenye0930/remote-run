from pathlib import Path

from remote_run.config import Config
from remote_run.sync import build_rsync_command


def test_build_rsync_command_includes_port_gitignore_and_excludes(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    config = Config(
        target="user@gpu",
        remote_workdir="/remote/project/",
        port=2222,
        exclude=("data/",),
    )

    cmd = build_rsync_command(tmp_path, config)

    assert cmd[:5] == ["rsync", "-az", "--delete", "-e", "ssh -p 2222"]
    assert "--exclude=.git/" in cmd
    assert "--exclude-from" in cmd
    assert str(tmp_path / ".gitignore") in cmd
    assert "--exclude=data/" in cmd
    assert cmd[-2] == f"{tmp_path.resolve()}/"
    assert cmd[-1] == "user@gpu:/remote/project/"
