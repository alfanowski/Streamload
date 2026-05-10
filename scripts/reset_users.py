"""DEV-ONLY: wipe users + sessions cascade so the new GitHub-auth flow can
register everyone fresh. Refuses to run if STREAMLOAD_ENV=production."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

import streamload.db.session as _db_session  # noqa: E402

from streamload.db import init as db_init, shutdown as db_shutdown  # noqa: E402


async def main(db_url: str) -> None:
    db_init(db_url)
    try:
        async with _db_session._session_factory() as db:  # type: ignore[misc]
            # CASCADE drops sessions, webauthn_credentials, watch_progress,
            # favorites, watchlist, etc.
            await db.execute(text("TRUNCATE users CASCADE"))
            await db.commit()
        print("users truncated (CASCADE)")
    finally:
        await db_shutdown()


if __name__ == "__main__":
    if os.environ.get("STREAMLOAD_ENV") == "production":
        print("refusing to truncate users in production")
        sys.exit(1)
    _db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload",
    )
    asyncio.run(main(_db_url))
