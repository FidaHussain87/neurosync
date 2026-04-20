"""Test fixtures: isolated SQLite, ChromaDB, memory layers."""

from __future__ import annotations

import os
import shutil
import tempfile

# Redirect HOME before any neurosync imports to isolate test data
_original_home = os.environ.get("HOME", "")
_test_home = tempfile.mkdtemp(prefix="neurosync_test_")
os.environ["HOME"] = _test_home
os.environ["NEUROSYNC_DATA_DIR"] = os.path.join(_test_home, ".neurosync")

import pytest

from neurosync.config import NeuroSyncConfig
from neurosync.db import Database
from neurosync.episodic import EpisodicMemory
from neurosync.semantic import SemanticMemory
from neurosync.user_model import UserModel
from neurosync.vectorstore import VectorStore


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp(prefix="neurosync_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def config(tmp_dir):
    return NeuroSyncConfig(
        data_dir=tmp_dir,
        sqlite_path=os.path.join(tmp_dir, "test.sqlite3"),
        chroma_path=os.path.join(tmp_dir, "chroma"),
    )


@pytest.fixture
def db(config):
    database = Database(config)
    yield database
    database.close()


@pytest.fixture
def vectorstore(config):
    return VectorStore(config)


@pytest.fixture
def episodic(db, vectorstore):
    return EpisodicMemory(db, vectorstore)


@pytest.fixture
def semantic(db, vectorstore):
    return SemanticMemory(db, vectorstore)


@pytest.fixture
def user_model(db):
    return UserModel(db)


def pytest_sessionfinish(session, exitstatus):
    """Clean up test home directory."""
    os.environ["HOME"] = _original_home
    if "NEUROSYNC_DATA_DIR" in os.environ:
        del os.environ["NEUROSYNC_DATA_DIR"]
    shutil.rmtree(_test_home, ignore_errors=True)
