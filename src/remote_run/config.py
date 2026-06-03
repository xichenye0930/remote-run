from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


CONFIG_FILE = ".rrun.toml"


class ConfigError(ValueError):
    """Raised when project configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    target: str
    remote_workdir: str
    port: int | None = None
    prelude: str = ""
    exclude: tuple[str, ...] = field(default_factory=tuple)


def load_config(project_root: Path) -> Config:
    config_path = project_root / CONFIG_FILE
    if not config_path.exists():
        raise ConfigError(
            f"missing {CONFIG_FILE}; run 'rrun init' in the project root first"
        )

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid {CONFIG_FILE}: {exc}") from exc

    return parse_config(data)


def parse_config(data: dict[str, object]) -> Config:
    target = _required_str(data, "target")
    remote_workdir = _required_str(data, "remote_workdir")
    port = _optional_int(data, "port")
    prelude = _optional_str(data, "prelude", "")
    exclude = _optional_str_list(data, "exclude")

    return Config(
        target=target,
        remote_workdir=remote_workdir,
        port=port,
        prelude=prelude,
        exclude=tuple(exclude),
    )


def sample_config() -> str:
    return """# SSH target used by ssh and rsync.
target = "user@gpu-server"

# Absolute directory on the remote machine.
remote_workdir = "/home/user/experiments/my-project"

# Optional SSH port.
# port = 22

# Optional shell snippet run before every command.
# prelude = "source ~/miniconda3/etc/profile.d/conda.sh && conda activate train"

# Extra rsync exclude patterns.
exclude = [
  "data/",
  "outputs/",
]
"""


def _required_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key!r} must be a non-empty string")
    return value


def _optional_str(data: dict[str, object], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{key!r} must be a string")
    return value


def _optional_int(data: dict[str, object], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{key!r} must be a positive integer")
    return value


def _optional_str_list(data: dict[str, object], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{key!r} must be a list of strings")
    return value

