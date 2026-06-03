from __future__ import annotations

from pathlib import Path
import subprocess

from .config import Config


DEFAULT_EXCLUDES = (
    ".git/",
    ".rrun/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".tox/",
    ".venv/",
    "__pycache__/",
    "build/",
    "dist/",
    "node_modules/",
    "venv/",
)


def build_rsync_command(project_root: Path, config: Config) -> list[str]:
    cmd = ["rsync", "-az", "--delete"]
    ssh_command = ["ssh", "-o", "LogLevel=ERROR"]

    if config.port is not None:
        ssh_command.extend(["-p", str(config.port)])

    cmd.extend(["-e", " ".join(ssh_command)])

    for pattern in DEFAULT_EXCLUDES:
        cmd.append(f"--exclude={pattern}")

    gitignore = project_root / ".gitignore"
    if gitignore.exists():
        cmd.extend(["--exclude-from", str(gitignore)])

    for pattern in config.exclude:
        cmd.append(f"--exclude={pattern}")

    source = f"{project_root.resolve()}/"
    destination = f"{config.target}:{config.remote_workdir.rstrip('/')}/"
    cmd.extend([source, destination])
    return cmd


def sync_project(project_root: Path, config: Config) -> None:
    subprocess.run(build_rsync_command(project_root, config), check=True)
