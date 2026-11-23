"""Test configuration: isolate all runtime data in a temporary directory."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="studypack_test_"))
os.environ.setdefault("DATA_DIR", str(_TMP / "data"))
os.environ.setdefault("DB_PATH", str(_TMP / "data" / "test.db"))
os.environ.setdefault("GENERATED_DIR", str(_TMP / "generated"))
os.environ.setdefault("LOGS_DIR", str(_TMP / "logs"))

FIXTURES = Path(__file__).parent / "fixtures"


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_token_calibration():
    """The chars/token estimate self-calibrates process-wide; isolate tests from each other."""
    import prompt_engine.context_manager as cm
    cm.CHARS_PER_TOKEN = cm.DEFAULT_CHARS_PER_TOKEN
    yield
    cm.CHARS_PER_TOKEN = cm.DEFAULT_CHARS_PER_TOKEN
