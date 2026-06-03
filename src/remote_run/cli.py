from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from .config import CONFIG_FILE, ConfigError, load_config, sample_config
from .remote import RemoteOutputError, cancel_job, fetch_status, stream_logs, submit_job
from .sync import sync_project


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    project_root = Path.cwd()

    if not args or args[0] == "--help":
        _print_help()
        return 0

    try:
        command = _extract_passthrough_command(args)
    except ValueError as exc:
        print(f"rrun: {exc}", file=sys.stderr)
        return 2
    if command is not None:
        return _run_remote_command(project_root, command)

    parser = _build_parser()
    parsed = parser.parse_args(args)

    try:
        if parsed.subcommand == "init":
            return _init(project_root)
        if parsed.subcommand == "sync":
            config = load_config(project_root)
            sync_project(project_root, config)
            return 0
        if parsed.subcommand == "status":
            config = load_config(project_root)
            status = fetch_status(config, parsed.job_id)
            _print_status(status)
            return 0
        if parsed.subcommand == "logs":
            config = load_config(project_root)
            return stream_logs(config, parsed.job_id, parsed.follow)
        if parsed.subcommand == "cancel":
            config = load_config(project_root)
            status = cancel_job(config, parsed.job_id, parsed.force)
            _print_status(status)
            return 0
    except ConfigError as exc:
        print(f"rrun: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"rrun: command failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode
    except RemoteOutputError as exc:
        print(f"rrun: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rrun")
    subparsers = parser.add_subparsers(dest="subcommand")

    subparsers.add_parser("init", help=f"create {CONFIG_FILE}")
    subparsers.add_parser("sync", help="sync the project to the remote workdir")

    status = subparsers.add_parser("status", help="show a remote job status")
    status.add_argument("job_id")

    logs = subparsers.add_parser("logs", help="show remote job logs")
    logs.add_argument("job_id")
    logs.add_argument("-f", "--follow", action="store_true")

    cancel = subparsers.add_parser("cancel", help="cancel a remote job")
    cancel.add_argument("job_id")
    cancel.add_argument("--force", action="store_true", help="send KILL instead of TERM")

    return parser


def _extract_passthrough_command(args: list[str]) -> list[str] | None:
    if "--" not in args:
        return None
    separator = args.index("--")
    command = args[separator + 1 :]
    if args[:separator]:
        raise ValueError("commands must use 'rrun -- <command>'")
    if not command:
        raise ValueError("missing command after '--'")
    return command


def _run_remote_command(project_root: Path, command: list[str]) -> int:
    try:
        config = load_config(project_root)
        sync_project(project_root, config)
        job_id = submit_job(config, command)
    except ConfigError as exc:
        print(f"rrun: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"rrun: command failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode

    print(job_id)
    return 0


def _init(project_root: Path) -> int:
    path = project_root / CONFIG_FILE
    if path.exists():
        print(f"rrun: {CONFIG_FILE} already exists", file=sys.stderr)
        return 1
    path.write_text(sample_config(), encoding="utf-8")
    print(f"created {CONFIG_FILE}")
    if _add_config_to_gitignore(project_root):
        print(f"added {CONFIG_FILE} to .gitignore")
    return 0


def _add_config_to_gitignore(project_root: Path) -> bool:
    gitignore = project_root / ".gitignore"
    if not gitignore.exists():
        return False

    content = gitignore.read_text(encoding="utf-8")
    entries = {
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if CONFIG_FILE in entries:
        return False

    prefix = "" if not content or content.endswith("\n") else "\n"
    gitignore.write_text(f"{content}{prefix}{CONFIG_FILE}\n", encoding="utf-8")
    return True


def _print_help() -> None:
    print(
        """usage: rrun <command> [args]

commands:
  init              create .rrun.toml
  sync              sync the project to the remote workdir
  status <job_id>   show remote job status
  logs <job_id>     show remote job logs
  cancel <job_id>   cancel a remote job
  -- <command...>   sync and submit a background remote command
"""
    )


def _print_status(status: object) -> None:
    for name in (
        "job_id",
        "state",
        "pid",
        "exit_code",
        "started_at",
        "ended_at",
        "cancelled_at",
    ):
        value = getattr(status, name)
        if value is not None:
            print(f"{name}: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
