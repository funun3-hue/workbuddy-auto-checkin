"""Read task metadata only; unknown states fail closed. No credential access."""
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

def idle(app):
    db = Path.home() / '.workbuddy/workbuddy.db'
    with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=3)) as conn:
        states = [str(row[0]).lower() for row in conn.execute(
            'SELECT status FROM sessions WHERE deleted_at IS NULL')]
    return all(state in {'completed', 'archived', 'cancelled', 'canceled', 'failed', 'error'}
               for state in states)

if __name__ == '__main__':
    try:
        sys.exit(0 if idle(sys.argv[1]) else 10)
    except Exception:
        sys.exit(11)
