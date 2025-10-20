from datetime import datetime
from pathlib import Path

from bot.database import Database
from bot.services.models import ReputationEntry


def test_fetch_summary_is_case_insensitive(tmp_path: Path) -> None:
    db_path = tmp_path / "reputation.sqlite"
    db = Database(db_path)
    async def scenario() -> None:
        await db.connect()
        try:
            await db.store_reputation_entries(
                [
                    ReputationEntry(
                        target="uglymove",
                        chat_id=-100,
                        message_id=1,
                        sentiment="positive",
                        has_photo=False,
                        has_media=False,
                        content="+rep @UglyMove",
                        author_id=42,
                        author_username="tester",
                        message_date=datetime.utcnow(),
                    )
                ]
            )

            summary = await db.fetch_summary("UglyMove")
            assert summary.positive == 1
            assert summary.target == "UglyMove"
        finally:
            await db.close()

    import asyncio

    asyncio.run(scenario())


def test_fetch_summary_handles_legacy_targets(tmp_path: Path) -> None:
    db_path = tmp_path / "reputation.sqlite"
    db = Database(db_path)

    async def scenario() -> None:
        await db.connect()
        try:
            await db.conn.execute(
                """
                INSERT INTO reputation_entries (
                    target, chat_id, message_id, sentiment, has_photo, has_media,
                    content, author_id, author_username, message_date
                ) VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?, ?)
                """,
                (
                    "@UglyMove",
                    -100,
                    42,
                    "positive",
                    "+rep @UglyMove",
                    7,
                    "tester",
                    int(datetime.utcnow().timestamp()),
                ),
            )
            await db.conn.commit()

            summary = await db.fetch_summary("uglymove")
            assert summary.positive == 1
            assert summary.negative == 0
        finally:
            await db.close()

    import asyncio

    asyncio.run(scenario())
