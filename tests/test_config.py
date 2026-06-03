from pathlib import Path

import pytest

from remote_run.config import Config, ConfigError, load_config, parse_config


def test_parse_config_accepts_required_fields() -> None:
    config = parse_config(
        {
            "target": "user@gpu",
            "remote_workdir": "/remote/project",
            "port": 2222,
            "prelude": "source env",
            "exclude": ["data/"],
        }
    )

    assert config == Config(
        target="user@gpu",
        remote_workdir="/remote/project",
        port=2222,
        prelude="source env",
        exclude=("data/",),
    )


def test_parse_config_requires_target() -> None:
    with pytest.raises(ConfigError, match="target"):
        parse_config({"remote_workdir": "/remote/project"})


def test_load_config_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing"):
        load_config(tmp_path)
