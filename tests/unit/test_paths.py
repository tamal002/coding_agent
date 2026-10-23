from pathlib import Path

import pytest

from agent.config import Settings
from agent.infra.paths import (
    artifacts_dir,
    runs_dir,
    undo_dir,
    workspace_dir,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path)


def test_workspace_dir(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    path = workspace_dir("t1", settings)
    assert path == tmp_path / "workspaces" / "t1"
    assert path.exists()


def test_workspace_dir_rejects_path_escape(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(ValueError):
        workspace_dir("../etc", settings)


def test_artifacts_dir(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    path = artifacts_dir("t1", settings)
    assert path == tmp_path / "artifacts" / "t1"
    assert path.exists()


def test_runs_dir(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    path = runs_dir(settings)
    assert path == tmp_path / "runs"
    assert path.exists()


def test_undo_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    path = undo_dir(workspace, "p1")
    assert path == workspace / ".agent" / "undo" / "p1"
    assert path.exists()


def test_undo_dir_rejects_bad_patch_id(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(ValueError):
        undo_dir(workspace, "../evil")
