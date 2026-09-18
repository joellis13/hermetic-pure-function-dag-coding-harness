"""SQLite-backed state machine for run lifecycle and plan checkpoint persistence."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
import uuid

import aiosqlite

from hermetic.schemas.context import IssueContext
from hermetic.schemas.plan import ImplementationPlan
from hermetic.schemas.run import RunStatus


@dataclass(frozen=True)
class RunState:
    """Snapshot of a run row in the database."""
    run_id: str
    issue_id: str
    repo_path: str
    base_branch: str
    status: str
    context_json: str
    created_at: str
    updated_at: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    issue_id     TEXT NOT NULL,
    repo_path    TEXT NOT NULL,
    base_branch  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'planning',
    context_json TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    version       INTEGER NOT NULL,
    plan_json     TEXT NOT NULL,
    feedback      TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    UNIQUE(run_id, version)
);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class StateMachine:
    """Persists run state, context snapshots, and plan checkpoints in SQLite via aiosqlite."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.executescript(_SCHEMA)
            await db.commit()
            yield db

    async def create_run(
        self,
        issue_id: str,
        repo_path: str | Path,
        base_branch: str,
        context: IssueContext,
    ) -> str:
        """Create a new run row with IssueContext snapshot. Returns run_id (UUID)."""
        run_id = str(uuid.uuid4())
        now = _utc_now_iso()
        context_json = context.model_dump_json()

        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO runs (run_id, issue_id, repo_path, base_branch, status, context_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    issue_id,
                    str(repo_path),
                    base_branch,
                    RunStatus.PLANNING.value,
                    context_json,
                    now,
                    now,
                ),
            )
            await db.commit()
        return run_id

    async def get_run(self, run_id: str) -> RunState | None:
        """Fetch a run state by run_id, or None if not found."""
        async with self._connect() as db:
            async with db.execute(
                """
                SELECT run_id, issue_id, repo_path, base_branch, status, context_json, created_at, updated_at
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return RunState(
                    run_id=row[0],
                    issue_id=row[1],
                    repo_path=row[2],
                    base_branch=row[3],
                    status=row[4],
                    context_json=row[5],
                    created_at=row[6],
                    updated_at=row[7],
                )

    async def update_run_status(self, run_id: str, status: str | RunStatus) -> None:
        """Update the status of a run and touch updated_at."""
        status_str = status.value if isinstance(status, RunStatus) else str(status)
        now = _utc_now_iso()
        async with self._connect() as db:
            await db.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status_str, now, run_id),
            )
            await db.commit()

    async def save_plan(
        self,
        run_id: str,
        plan: ImplementationPlan,
        feedback: str = "",
    ) -> int:
        """Persist a new plan version checkpoint. Returns version number (1-indexed)."""
        checkpoint_id = str(uuid.uuid4())
        now = _utc_now_iso()
        plan_json = plan.model_dump_json()

        async with self._connect() as db:
            async with db.execute(
                "SELECT MAX(version) FROM plan_checkpoints WHERE run_id = ?",
                (run_id,),
            ) as cursor:
                row = await cursor.fetchone()
                current_max = row[0] if row and row[0] is not None else 0
                next_version = current_max + 1

            await db.execute(
                """
                INSERT INTO plan_checkpoints (checkpoint_id, run_id, version, plan_json, feedback, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (checkpoint_id, run_id, next_version, plan_json, feedback, now),
            )
            await db.execute(
                "UPDATE runs SET updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )
            await db.commit()
        return next_version

    async def get_latest_plan(
        self, run_id: str
    ) -> tuple[ImplementationPlan, int] | None:
        """Return (plan, version) for the highest version checkpoint, or None."""
        async with self._connect() as db:
            async with db.execute(
                """
                SELECT plan_json, version
                FROM plan_checkpoints
                WHERE run_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (run_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                plan = ImplementationPlan.model_validate_json(row[0])
                return plan, int(row[1])

    async def get_plan_version(
        self, run_id: str, version: int
    ) -> ImplementationPlan | None:
        """Return the ImplementationPlan for a specific version, or None."""
        async with self._connect() as db:
            async with db.execute(
                "SELECT plan_json FROM plan_checkpoints WHERE run_id = ? AND version = ?",
                (run_id, version),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return ImplementationPlan.model_validate_json(row[0])

    async def list_plan_versions(self, run_id: str) -> list[int]:
        """List all plan version numbers for a run, in ascending order."""
        async with self._connect() as db:
            async with db.execute(
                "SELECT version FROM plan_checkpoints WHERE run_id = ? ORDER BY version ASC",
                (run_id,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def get_context(self, run_id: str) -> IssueContext | None:
        """Re-hydrate IssueContext from the stored point-in-time snapshot."""
        async with self._connect() as db:
            async with db.execute(
                "SELECT context_json FROM runs WHERE run_id = ?",
                (run_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None or not row[0]:
                    return None
                return IssueContext.model_validate_json(row[0])

    async def get_plan_feedback(self, run_id: str, version: int) -> str | None:
        """Get the feedback string stored with a plan version checkpoint."""
        async with self._connect() as db:
            async with db.execute(
                "SELECT feedback FROM plan_checkpoints WHERE run_id = ? AND version = ?",
                (run_id, version),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return row[0]
