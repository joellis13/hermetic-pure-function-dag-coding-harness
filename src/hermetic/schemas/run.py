"""Run status schema."""
from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    PLANNING = "planning"
    APPROVED = "approved"
    EXECUTING = "executing"
    DONE = "done"
    FAILED = "failed"
