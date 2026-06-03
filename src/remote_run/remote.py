from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import secrets
import shlex
import subprocess

from .config import Config


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    state: str
    pid: str | None = None
    exit_code: int | None = None
    started_at: str | None = None
    ended_at: str | None = None


def make_job_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(4)}"


def build_ssh_command(config: Config, remote_script: str) -> list[str]:
    cmd = ["ssh"]
    if config.port is not None:
        cmd.extend(["-p", str(config.port)])
    cmd.extend([config.target, "bash", "-lc", remote_script])
    return cmd


def submit_job(config: Config, command: list[str]) -> str:
    if not command:
        raise ValueError("command must not be empty")

    job_id = make_job_id()
    remote_script = build_submit_script(config, job_id, command)
    subprocess.run(build_ssh_command(config, remote_script), check=True)
    return job_id


def build_submit_script(config: Config, job_id: str, command: list[str]) -> str:
    job_dir = _job_dir(config, job_id)
    remote_workdir = shlex.quote(config.remote_workdir)
    job_dir_q = shlex.quote(job_dir)
    command_line = shlex.join(command)
    command_payload = _command_script(config.prelude, command_line)
    metadata = json.dumps(
        {
            "job_id": job_id,
            "command": command,
            "remote_workdir": config.remote_workdir,
        },
        sort_keys=True,
    )

    return "\n".join(
        [
            "set -e",
            f"mkdir -p {job_dir_q}",
            f"cd {remote_workdir}",
            f"cat > {shlex.quote(job_dir + '/command.sh')} <<'RRUN_COMMAND'",
            command_payload,
            "RRUN_COMMAND",
            f"chmod +x {shlex.quote(job_dir + '/command.sh')}",
            f"cat > {shlex.quote(job_dir + '/metadata.json')} <<'RRUN_METADATA'",
            metadata,
            "RRUN_METADATA",
            f"date -u +%Y-%m-%dT%H:%M:%SZ > {shlex.quote(job_dir + '/started_at')}",
            (
                f"nohup bash -lc {shlex.quote(_background_runner(job_dir))} "
                f"> {shlex.quote(job_dir + '/run.log')} 2>&1 < /dev/null &"
            ),
            f"echo $! > {shlex.quote(job_dir + '/pid')}",
        ]
    )


def fetch_status(config: Config, job_id: str) -> JobStatus:
    remote_script = build_status_script(config, job_id)
    result = subprocess.run(
        build_ssh_command(config, remote_script),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    data = json.loads(result.stdout)
    return JobStatus(
        job_id=job_id,
        state=data["state"],
        pid=data.get("pid") or None,
        exit_code=data.get("exit_code"),
        started_at=data.get("started_at") or None,
        ended_at=data.get("ended_at") or None,
    )


def build_status_script(config: Config, job_id: str) -> str:
    job_dir = shlex.quote(_job_dir(config, job_id))
    return f"""
set -e
job_dir={job_dir}
if [ ! -d "$job_dir" ]; then
  printf '{{"state":"unknown"}}\\n'
  exit 0
fi
pid=""
if [ -f "$job_dir/pid" ]; then pid="$(cat "$job_dir/pid")"; fi
started_at=""
if [ -f "$job_dir/started_at" ]; then started_at="$(cat "$job_dir/started_at")"; fi
ended_at=""
if [ -f "$job_dir/ended_at" ]; then ended_at="$(cat "$job_dir/ended_at")"; fi
if [ -f "$job_dir/exit_code" ]; then
  exit_code="$(cat "$job_dir/exit_code")"
  if [ "$exit_code" = "0" ]; then state="succeeded"; else state="failed"; fi
  printf '{{"state":"%s","pid":"%s","exit_code":%s,"started_at":"%s","ended_at":"%s"}}\\n' "$state" "$pid" "$exit_code" "$started_at" "$ended_at"
  exit 0
fi
if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
  printf '{{"state":"running","pid":"%s","started_at":"%s"}}\\n' "$pid" "$started_at"
else
  printf '{{"state":"unknown","pid":"%s","started_at":"%s"}}\\n' "$pid" "$started_at"
fi
"""


def stream_logs(config: Config, job_id: str, follow: bool) -> int:
    log_path = shlex.quote(_job_dir(config, job_id) + "/run.log")
    tail_args = "-n +1 -f" if follow else "-n +1"
    remote_script = f"tail {tail_args} {log_path}"
    process = subprocess.Popen(build_ssh_command(config, remote_script))
    return process.wait()


def _command_script(prelude: str, command_line: str) -> str:
    lines = ["#!/usr/bin/env bash", "set -e"]
    if prelude.strip():
        lines.append(prelude)
    lines.append(command_line)
    return "\n".join(lines)


def _background_runner(job_dir: str) -> str:
    command_path = shlex.quote(job_dir + "/command.sh")
    exit_path = shlex.quote(job_dir + "/exit_code")
    ended_path = shlex.quote(job_dir + "/ended_at")
    return (
        f"{command_path}; "
        "code=$?; "
        f"printf '%s\\n' \"$code\" > {exit_path}; "
        f"date -u +%Y-%m-%dT%H:%M:%SZ > {ended_path}; "
        "exit \"$code\""
    )


def _job_dir(config: Config, job_id: str) -> str:
    return f"{config.remote_workdir.rstrip('/')}/.rrun/jobs/{job_id}"

