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
