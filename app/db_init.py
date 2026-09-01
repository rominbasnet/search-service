"""Run once to create Postgres tables: `python -m app.db_init`"""
import asyncio

from app.database import Base, engine
from app import models  # noqa: F401


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created.")


if __name__ == "__main__":
    asyncio.run(main())
