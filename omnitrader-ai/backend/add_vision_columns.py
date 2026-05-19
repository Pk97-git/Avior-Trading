#!/usr/bin/env python3
"""
add_vision_columns.py
=====================
One-time migration: adds vision_score and vision_thesis columns to the
ai_analysis table. Safe to run multiple times (uses IF NOT EXISTS).

Run:
    source venv/bin/activate
    python add_vision_columns.py
"""
import asyncio
import sys

sys.path.insert(0, ".")
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.core.config import settings

engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, echo=False)
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

MIGRATIONS = [
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS vision_score  INTEGER",
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS vision_thesis  JSONB",
]


async def main():
    print("\nAdding vision columns to ai_analysis table...")
    async with Session() as session:
        for sql in MIGRATIONS:
            try:
                await session.execute(text(sql))
                print(f"  ✓ {sql}")
            except Exception as e:
                print(f"  ✗ {sql}\n    Error: {e}")
        await session.commit()
    print("\nDone. Restart the backend server.\n")


if __name__ == "__main__":
    asyncio.run(main())
