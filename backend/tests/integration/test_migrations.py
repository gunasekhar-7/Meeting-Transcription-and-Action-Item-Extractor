from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "users",
    "refresh_tokens",
    "meetings",
    "audio_assets",
    "transcripts",
    "speakers",
    "transcript_segments",
    "meeting_intelligence",
    "key_points",
    "decisions",
    "action_items",
    "evidence_links",
    "processing_jobs",
}


def test_migrations_create_the_complete_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    env = {**os.environ, "DATABASE_URL": database_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert tables >= EXPECTED_TABLES, EXPECTED_TABLES - tables
    assert "alembic_version" in tables
