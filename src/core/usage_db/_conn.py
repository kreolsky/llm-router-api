"""The single aiosqlite connection shared by the writer and the dashboard queries.

This module is the seam the usage_db package splits along: writer.py owns the
INSERT path, queries.py owns the dashboard reads, and both resolve the
connection from here — never from each other.
"""

import aiosqlite

_connection: aiosqlite.Connection | None = None


def get_connection() -> aiosqlite.Connection | None:
    return _connection


async def set_connection(conn: aiosqlite.Connection | None) -> None:
    """Install conn as the shared connection, closing any prior one.

    The single write point for this module: writer and queries resolve the
    connection via get_connection(), and init_db/close_db swap it only
    through here — so an overwrite can never orphan an open handle.
    """
    global _connection
    if _connection is not None:
        await _connection.close()
    _connection = conn
