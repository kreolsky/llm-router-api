"""The single aiosqlite connection shared by the writer and the dashboard queries.

This module is the seam the usage_db package splits along: writer.py owns the
INSERT path, queries.py owns the dashboard reads, and both resolve the
connection from here — never from each other.
"""

import aiosqlite

_connection: aiosqlite.Connection | None = None


def get_connection() -> aiosqlite.Connection | None:
    return _connection
