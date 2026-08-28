"""SQLite-backed request/usage tracking for the /stat/ dashboard (package).

Split along the seam the module already had: writer.py owns the schema, the
per-request holder and the single-row flush; queries.py owns the dashboard
reads; they share only the connection (_conn.py). Every public name the rest
of the tree imports is re-exported here, so the package is a drop-in for the
old single module.

WHY re-exports do not preserve patch targets: schedule_flush resolves
_flush_row through writer's own module globals, so a test patching
``src.core.usage_db._flush_row`` would replace only the inert alias here.
Patch the submodule the CALLER resolves the name from
(``src.core.usage_db.writer._flush_row``).
"""
# SYSTEM: usage-stats — SQLite per-request usage rows and cost freezing

from ._conn import get_connection
from .queries import (
    ERROR_CODE_NULL,
    get_distinct_models,
    get_distinct_users,
    get_requests,
    get_summary,
    get_usage_data,
)
from .writer import (
    RequestStats,
    close_db,
    init_db,
    request_stats,
    schedule_flush,
)

__all__ = [
    "ERROR_CODE_NULL",
    "RequestStats",
    "close_db",
    "get_connection",
    "get_distinct_models",
    "get_distinct_users",
    "get_requests",
    "get_summary",
    "get_usage_data",
    "init_db",
    "request_stats",
    "schedule_flush",
]
