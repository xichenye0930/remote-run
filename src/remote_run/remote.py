from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import secrets
import shlex
import subprocess

from .config import Config


class RemoteOutputError(ValueError):
    """Raised when a remote control command returns malformed output."""


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    state: str
    pid: str | None = None
    exit_code: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    cancelled_at: str | None = None


def make_job_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(4)}"


def build_ssh_command(config: Config, remote_script: str) -> list[str]:
    cmd = ["ssh", "-o", "LogLevel=ERROR"]
    if config.port is not None:
        cmd.extend(["-p", str(config.port)])
    cmd.extend([config.target, "bash", "-c", remote_script])
    return cmd


def submit_job(config: Config, command: list[str]) -> str:
    if not command:
        raise ValueError("command must not be empty")

    job_id = make_job_id()
    remote_script = build_submit_script(config, job_id, command)
    subprocess.run(
        build_ssh_command(config, remote_script),
        check=True,
        stdout=subprocess.PIPE,
    )
    return job_id


def cancel_job(config: Config, job_id: str, force: bool = False) -> JobStatus:
    remote_script = build_cancel_script(config, job_id, force)
    result = subprocess.run(
        build_ssh_command(config, remote_script),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return _status_from_data(job_id, _parse_status_json(result.stdout))


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
                f"nohup setsid bash -lc {shlex.quote(_background_runner(job_dir))} "
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
    data = _parse_status_json(result.stdout)
    return _status_from_data(job_id, data)


def _status_from_data(job_id: str, data: dict[str, object]) -> JobStatus:
    return JobStatus(
        job_id=job_id,
        state=data["state"],
        pid=data.get("pid") or None,
        exit_code=data.get("exit_code"),
        started_at=data.get("started_at") or None,
        ended_at=data.get("ended_at") or None,
        cancelled_at=data.get("cancelled_at") or None,
    )


def build_status_script(config: Config, job_id: str) -> str:
    job_dir = shlex.quote(_job_dir(config, job_id))
    return _status_script(job_dir)


def build_cancel_script(config: Config, job_id: str, force: bool) -> str:
    job_dir = shlex.quote(_job_dir(config, job_id))
    signal = "KILL" if force else "TERM"
    signal_q = shlex.quote(signal)
    return f"""
set -e
job_dir={job_dir}
signal={signal_q}
if [ ! -d "$job_dir" ]; then
  printf '{{"state":"unknown"}}\\n'
  exit 0
fi
if [ -f "$job_dir/exit_code" ]; then
  {_status_script_body()}
  exit 0
fi
if [ ! -f "$job_dir/pid" ]; then
  printf '{{"state":"unknown"}}\\n'
  exit 0
fi
pid="$(cat "$job_dir/pid")"
if [ -z "$pid" ]; then
  printf '{{"state":"unknown"}}\\n'
  exit 0
fi
date -u +%Y-%m-%dT%H:%M:%SZ > "$job_dir/cancelled_at"
printf '%s\\n' "$signal" > "$job_dir/cancel_signal"
{_process_tree_functions()}
rrun_kill_tree "$pid" "$signal" "$job_dir/children"
sleep 1
rrun_kill_tree "$pid" "$signal" "$job_dir/children"
{_status_script_body()}
"""


def _status_script(job_dir: str) -> str:
    return f"""
set -e
job_dir={job_dir}
{_status_script_body()}
"""


def _status_script_body() -> str:
    return _known_children_status_functions() + """
if [ ! -d "$job_dir" ]; then
  printf '{"state":"unknown"}\\n'
  exit 0
fi
pid=""
if [ -f "$job_dir/pid" ]; then pid="$(cat "$job_dir/pid")"; fi
started_at=""
if [ -f "$job_dir/started_at" ]; then started_at="$(cat "$job_dir/started_at")"; fi
ended_at=""
if [ -f "$job_dir/ended_at" ]; then ended_at="$(cat "$job_dir/ended_at")"; fi
cancelled_at=""
if [ -f "$job_dir/cancelled_at" ]; then cancelled_at="$(cat "$job_dir/cancelled_at")"; fi
live_children=""
if [ -f "$job_dir/children" ]; then live_children="$(rrun_live_known_children "$job_dir/children")"; fi
if [ -f "$job_dir/exit_code" ]; then
  exit_code="$(cat "$job_dir/exit_code")"
  if [ "$exit_code" = "0" ]; then state="succeeded"; else state="failed"; fi
  printf '{"state":"%s","pid":"%s","exit_code":%s,"started_at":"%s","ended_at":"%s"}\\n' "$state" "$pid" "$exit_code" "$started_at" "$ended_at"
  exit 0
fi
if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
  if [ -n "$cancelled_at" ]; then state="cancelling"; else state="running"; fi
  printf '{"state":"%s","pid":"%s","started_at":"%s","cancelled_at":"%s"}\\n' "$state" "$pid" "$started_at" "$cancelled_at"
else
  if [ -n "$cancelled_at" ] && [ -n "$live_children" ]; then state="cancelling";
  elif [ -n "$cancelled_at" ]; then state="cancelled";
  else state="unknown"; fi
  printf '{"state":"%s","pid":"%s","started_at":"%s","cancelled_at":"%s"}\\n' "$state" "$pid" "$started_at" "$cancelled_at"
fi
"""


def _process_tree_functions() -> str:
    return r"""
rrun_descendants() {
  root="$1"
  queue="$root"
  while [ -n "$queue" ]; do
    next=""
    for parent in $queue; do
      children="$(pgrep -P "$parent" 2>/dev/null || true)"
      for child in $children; do
        printf '%s\n' "$child"
        next="$next $child"
      done
    done
    queue="$next"
  done
}

rrun_kill_tree() {
  root="$1"
  signal="$2"
  children_file="$3"
  known=""
  if [ -f "$children_file" ]; then known="$(cat "$children_file")"; fi
  children="$(printf '%s\n%s\n' "$(rrun_descendants "$root" | awk 'NF' || true)" "$known" | awk 'NF' | sort -u || true)"
  printf '%s\n' "$children" | awk 'NF' > "$children_file"
  printf '%s\n' "$children" | awk 'NF' | tac 2>/dev/null | while read -r child; do
    kill -s "$signal" "$child" >/dev/null 2>&1 || true
  done
  kill -s "$signal" -- "-$root" >/dev/null 2>&1 || true
  kill -s "$signal" "$root" >/dev/null 2>&1 || true
}
"""


def _known_children_status_functions() -> str:
    return r"""
rrun_live_known_children() {
  children_file="$1"
  while read -r child; do
    if [ -n "$child" ] && kill -0 "$child" >/dev/null 2>&1; then
      printf '%s\n' "$child"
    fi
  done < "$children_file"
}
"""


def stream_logs(config: Config, job_id: str, follow: bool) -> int:
    remote_script = build_logs_script(config, job_id, follow)
    process = subprocess.Popen(build_ssh_command(config, remote_script))
    return process.wait()


def build_logs_script(config: Config, job_id: str, follow: bool) -> str:
    job_dir = shlex.quote(_job_dir(config, job_id))
    log_path = shlex.quote(_job_dir(config, job_id) + "/run.log")
    unknown_job = shlex.quote(f"rrun: unknown job {job_id}")
    missing_log = shlex.quote("rrun: log is not available yet")
    command = f"tail -n +1 -F {log_path}" if follow else f"cat {log_path}"
    return f"""
set -e
job_dir={job_dir}
log_path={log_path}
if [ ! -d "$job_dir" ]; then
  printf '%s\\n' {unknown_job} >&2
  exit 2
fi
if [ ! -f "$log_path" ]; then
  printf '%s\\n' {missing_log} >&2
  exit 2
fi
{command}
"""


def _parse_status_json(stdout: str) -> dict[str, object]:
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            return json.loads(candidate)
    raise RemoteOutputError("remote status output did not contain JSON")


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
