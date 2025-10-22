from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional

from pyrogram import Client, errors

from ..database import Database

LOGGER = logging.getLogger(__name__)


class PyrogramAccountPool:
    """Manages a pool of logged-in Pyrogram clients with round-robin selection."""

    def __init__(self, db: Database, session_dir: Path) -> None:
        self._db = db
        self._session_dir = session_dir
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._clients: Dict[str, Client] = {}
        self._order: List[str] = []
        self._index: int = 0
        self._lock = asyncio.Lock()
        self._api_id: Optional[int] = None
        self._api_hash: Optional[str] = None

    async def configure(self, api_id: Optional[int], api_hash: Optional[str]) -> None:
        async with self._lock:
            if self._api_id == api_id and self._api_hash == api_hash:
                await self._refresh_locked()
                return
            await self._close_all_locked()
            self._api_id = api_id
            self._api_hash = api_hash
            await self._refresh_locked()

    async def refresh(self) -> None:
        async with self._lock:
            await self._refresh_locked()

    async def acquire(self) -> Client:
        async with self._lock:
            await self._refresh_locked()
            if not self._order:
                raise RuntimeError("No active Pyrogram accounts configured")
            session_name = self._order[self._index % len(self._order)]
            self._index += 1
            client = self._clients[session_name]
            await self._db.mark_pyrogram_account_used(session_name)
            return client

    async def close(self) -> None:
        async with self._lock:
            await self._close_all_locked()

    async def _refresh_locked(self) -> None:
        if not self._api_id or not self._api_hash:
            self._order = []
            await self._close_all_locked()
            return

        accounts = await self._db.list_pyrogram_accounts(only_active=True)
        desired_sessions = {item["session_name"] for item in accounts}

        # Remove clients that are no longer needed
        for session_name in list(self._clients.keys()):
            if session_name not in desired_sessions:
                client = self._clients.pop(session_name)
                try:
                    await client.stop()
                except Exception:
                    LOGGER.debug("Failed to stop Pyrogram client %s", session_name, exc_info=True)

        # Start new clients if necessary
        for account in accounts:
            session_name = account["session_name"]
            if session_name in self._clients:
                continue
            client = Client(
                name=session_name,
                api_id=self._api_id,
                api_hash=self._api_hash,
                workdir=str(self._session_dir.resolve()),
                no_updates=True,
            )
            try:
                await client.start()
            except errors.AuthKeyUnregistered:
                LOGGER.warning("Session %s is invalid; deactivating.", session_name)
                await self._db.deactivate_pyrogram_account(session_name)
                continue
            except errors.FloodWait as exc:
                LOGGER.warning(
                    "Flood wait while starting session %s; sleeping %ss", session_name, exc.value
                )
                await asyncio.sleep(exc.value + 1)
                await client.start()
            self._clients[session_name] = client

        self._order = [item["session_name"] for item in accounts if item["session_name"] in self._clients]
        if not self._order:
            self._index = 0

    async def _close_all_locked(self) -> None:
        for session_name, client in list(self._clients.items()):
            try:
                await client.stop()
            except Exception:
                LOGGER.debug("Failed to stop Pyrogram client %s", session_name, exc_info=True)
        self._clients.clear()
        self._order.clear()
        self._index = 0
