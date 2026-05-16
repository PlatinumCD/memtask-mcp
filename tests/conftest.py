from __future__ import annotations

import pytest

from memtask import storage


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    storage.set_db_path(tmp_path / "tasks.sqlite")
    storage.init_db()
    yield
    storage.set_db_path(storage.DEFAULT_DB_PATH)
