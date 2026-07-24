"""Gate: CLI image-dir resolution precedence + actionable missing-dir error."""

from __future__ import annotations

import pytest

from skywatcher.fr24 import cli_support


def test_explicit_flag_wins(tmp_path):
    d = tmp_path / "explicit"
    d.mkdir()
    env = {"SKYWATCHER_IMAGE_DIR": str(tmp_path / "env")}
    resolved = cli_support.resolve_image_dir(str(d), env=env)
    assert resolved == d


def test_env_var_used_when_no_flag(tmp_path):
    d = tmp_path / "env"
    d.mkdir()
    env = {"SKYWATCHER_IMAGE_DIR": str(d)}
    resolved = cli_support.resolve_image_dir(None, env=env)
    assert resolved == d


def test_default_when_nothing_set():
    resolved = cli_support.resolve_image_dir(None, env={}, require_exists=False)
    assert resolved == cli_support.DEFAULT_IMAGE_DIR_RELATIVE


def test_missing_dir_raises_actionable_error(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(cli_support.ImageDirUnavailableError) as exc:
        cli_support.resolve_image_dir(str(missing), env={})
    msg = str(exc.value)
    assert str(missing) in msg
    assert "--image-dir" in msg and "SKYWATCHER_IMAGE_DIR" in msg


def test_no_hosted_default_leak():
    # The hosted-only /mnt/user-data/uploads default must be gone.
    assert "/mnt/user-data/uploads" not in str(cli_support.DEFAULT_IMAGE_DIR_RELATIVE)
