"""Tests for config.py."""

from __future__ import annotations

import json
import os

from neurosync.config import NeuroSyncConfig, detect_git_info


class TestNeuroSyncConfig:
    def test_defaults(self, tmp_dir):
        config = NeuroSyncConfig(data_dir=tmp_dir)
        assert config.data_dir == tmp_dir
        assert config.sqlite_path == os.path.join(tmp_dir, "neurosync.sqlite3")
        assert config.chroma_path == os.path.join(tmp_dir, "chroma")
        assert config.recall_max_tokens == 500
        assert config.consolidation_min_episodes == 5

    def test_new_config_defaults(self, tmp_dir):
        config = NeuroSyncConfig(data_dir=tmp_dir)
        assert config.episode_quality_threshold == 3
        assert config.continuation_weight == 8.0
        assert config.protocol_hints_enabled is True

    def test_auto_consolidation_config_defaults(self, tmp_dir):
        config = NeuroSyncConfig(data_dir=tmp_dir)
        assert config.auto_consolidation_enabled is True
        assert config.auto_consolidation_threshold == 20

    def test_ensure_dirs(self, tmp_dir):
        config = NeuroSyncConfig(data_dir=os.path.join(tmp_dir, "sub"))
        config.ensure_dirs()
        assert os.path.isdir(config.data_dir)
        assert os.path.isdir(config.chroma_path)

    def test_load_from_config_file(self, tmp_dir):
        config_path = os.path.join(tmp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump({"recall_max_tokens": 1000, "data_dir": tmp_dir}, f)
        config = NeuroSyncConfig.load(config_path=config_path)
        assert config.recall_max_tokens == 1000

    def test_load_ignores_unknown_keys(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("NEUROSYNC_DATA_DIR", raising=False)
        config_path = os.path.join(tmp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump({"unknown_key": "value", "data_dir": tmp_dir}, f)
        config = NeuroSyncConfig.load(config_path=config_path)
        assert config.data_dir == tmp_dir


    def test_malformed_config_json_uses_defaults(self, tmp_dir):
        """A malformed config.json should not crash — defaults should be used."""
        config_path = os.path.join(tmp_dir, "config.json")
        with open(config_path, "w") as f:
            f.write("{invalid json content")
        config = NeuroSyncConfig.load(config_path=config_path)
        # Should have default values, not crash
        assert config.recall_max_tokens == 500

    def test_ensure_dirs_permission_error(self, tmp_dir):
        """ensure_dirs should raise RuntimeError with helpful message on OSError."""
        import stat
        # Create a read-only directory
        readonly = os.path.join(tmp_dir, "readonly")
        os.makedirs(readonly)
        os.chmod(readonly, stat.S_IRUSR | stat.S_IXUSR)
        config = NeuroSyncConfig(data_dir=os.path.join(readonly, "sub", "data"))
        try:
            import pytest
            with pytest.raises(RuntimeError, match="Cannot create NeuroSync data directory"):
                config.ensure_dirs()
        finally:
            # Restore permissions for cleanup
            os.chmod(readonly, stat.S_IRWXU)


class TestGitDetection:
    def test_detect_git_info_returns_dict(self):
        info = detect_git_info()
        assert isinstance(info, dict)

    def test_detect_git_info_nonexistent_dir(self, tmp_dir):
        info = detect_git_info(cwd=os.path.join(tmp_dir, "nonexistent"))
        assert isinstance(info, dict)
