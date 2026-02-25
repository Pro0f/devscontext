"""SQLite storage for pre-built context.

This module provides persistent storage for pre-built context that has been
processed by the background agent. The MCP server can then retrieve this
context instantly instead of fetching on-demand.

Uses aiosqlite for async SQLite access.

Example:
    storage = PrebuiltContextStorage(".devscontext/cache.db")
    await storage.initialize()

    # Store pre-built context
    await storage.store(context)

    # Retrieve context
    context = await storage.get("PROJ-123")
    if context and not context.is_expired():
        # Use the pre-built context
        ...

    await storage.close()
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from devscontext.logging import get_logger
from devscontext.models import PrebuiltContext

logger = get_logger(__name__)


class PrebuiltContextStorage:
    """SQLite storage for pre-built context.

    Provides async storage and retrieval of pre-built context that was
    created by the background preprocessing agent.

    The storage uses a single SQLite table with the following schema:
        - task_id: TEXT PRIMARY KEY
        - synthesized: TEXT (markdown content)
        - sources_used: TEXT (JSON array)
        - context_quality_score: REAL (0-1)
        - gaps: TEXT (JSON array)
        - built_at: TEXT (ISO timestamp)
        - expires_at: TEXT (ISO timestamp)
        - source_data_hash: TEXT (for staleness detection)
    """

    def __init__(self, db_path: str = ".devscontext/cache.db") -> None:
        """Initialize storage with database path.

        Args:
            db_path: Path to SQLite database file.
        """
        self._db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create database and table if needed.

        Creates the parent directory if it doesn't exist.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS prebuilt_context (
                task_id TEXT PRIMARY KEY,
                synthesized TEXT NOT NULL,
                sources_used TEXT NOT NULL,
                context_quality_score REAL NOT NULL,
                gaps TEXT NOT NULL,
                built_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                source_data_hash TEXT NOT NULL
            )
        """)
        await self._conn.commit()

        logger.info(
            "Storage initialized",
            extra={"db_path": str(self._db_path)},
        )

    async def store(self, context: PrebuiltContext) -> None:
        """Store pre-built context, replacing if exists.

        Args:
            context: PrebuiltContext to store.
        """
        if self._conn is None:
            raise RuntimeError("Storage not initialized. Call initialize() first.")

        await self._conn.execute(
            """
            INSERT OR REPLACE INTO prebuilt_context
            (task_id, synthesized, sources_used, context_quality_score,
             gaps, built_at, expires_at, source_data_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                context.task_id,
                context.synthesized,
                json.dumps(context.sources_used),
                context.context_quality_score,
                json.dumps(context.gaps),
                context.built_at.isoformat(),
                context.expires_at.isoformat(),
                context.source_data_hash,
            ),
        )
        await self._conn.commit()

        logger.info(
            "Stored pre-built context",
            extra={
                "task_id": context.task_id,
                "quality_score": context.context_quality_score,
                "gaps_count": len(context.gaps),
            },
        )

    async def get(self, task_id: str) -> PrebuiltContext | None:
        """Get pre-built context if exists.

        Note: This returns the context even if expired. Use is_expired()
        to check if it should be refreshed.

        Args:
            task_id: Task identifier to retrieve.

        Returns:
            PrebuiltContext if found, None otherwise.
        """
        if self._conn is None:
            raise RuntimeError("Storage not initialized. Call initialize() first.")

        cursor = await self._conn.execute(
            """
            SELECT task_id, synthesized, sources_used, context_quality_score,
                   gaps, built_at, expires_at, source_data_hash
            FROM prebuilt_context
            WHERE task_id = ?
            """,
            (task_id,),
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        return PrebuiltContext(
            task_id=row[0],
            synthesized=row[1],
            sources_used=json.loads(row[2]),
            context_quality_score=row[3],
            gaps=json.loads(row[4]),
            built_at=datetime.fromisoformat(row[5]),
            expires_at=datetime.fromisoformat(row[6]),
            source_data_hash=row[7],
        )

    async def is_stale(self, task_id: str, current_hash: str) -> bool:
        """Check if stored context is stale.

        Context is stale if the source data has changed (Jira ticket updated).

        Args:
            task_id: Task identifier.
            current_hash: Current hash of source data (ticket.updated).

        Returns:
            True if stale or not found, False if fresh.
        """
        if self._conn is None:
            raise RuntimeError("Storage not initialized. Call initialize() first.")

        cursor = await self._conn.execute(
            "SELECT source_data_hash FROM prebuilt_context WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()

        if row is None:
            return True  # Not found = stale

        return bool(row[0] != current_hash)

    async def delete(self, task_id: str) -> bool:
        """Delete pre-built context for a task.

        Args:
            task_id: Task identifier to delete.

        Returns:
            True if deleted, False if not found.
        """
        if self._conn is None:
            raise RuntimeError("Storage not initialized. Call initialize() first.")

        cursor = await self._conn.execute(
            "DELETE FROM prebuilt_context WHERE task_id = ?",
            (task_id,),
        )
        await self._conn.commit()

        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Deleted pre-built context", extra={"task_id": task_id})

        return deleted

    async def delete_expired(self) -> int:
        """Delete all expired entries.

        Returns:
            Number of entries deleted.
        """
        if self._conn is None:
            raise RuntimeError("Storage not initialized. Call initialize() first.")

        now = datetime.now(UTC).isoformat()
        cursor = await self._conn.execute(
            "DELETE FROM prebuilt_context WHERE expires_at < ?",
            (now,),
        )
        await self._conn.commit()

        count = cursor.rowcount
        if count > 0:
            logger.info("Deleted expired contexts", extra={"count": count})

        return count

    async def list_all(self) -> list[dict[str, Any]]:
        """List all stored contexts (summary only).

        Returns:
            List of dicts with task_id, quality_score, built_at, expires_at.
        """
        if self._conn is None:
            raise RuntimeError("Storage not initialized. Call initialize() first.")

        cursor = await self._conn.execute(
            """
            SELECT task_id, context_quality_score, built_at, expires_at, gaps
            FROM prebuilt_context
            ORDER BY built_at DESC
            """
        )
        rows = await cursor.fetchall()

        return [
            {
                "task_id": row[0],
                "quality_score": row[1],
                "built_at": row[2],
                "expires_at": row[3],
                "gaps_count": len(json.loads(row[4])),
            }
            for row in rows
        ]

    async def get_stats(self) -> dict[str, Any]:
        """Get storage statistics for CLI status command.

        Returns:
            Dict with total, active, expired counts and average quality.
        """
        if self._conn is None:
            raise RuntimeError("Storage not initialized. Call initialize() first.")

        now = datetime.now(UTC).isoformat()

        # Total count
        cursor = await self._conn.execute("SELECT COUNT(*) FROM prebuilt_context")
        total_row = await cursor.fetchone()
        total: int = total_row[0] if total_row else 0

        # Active (not expired) count
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM prebuilt_context WHERE expires_at >= ?",
            (now,),
        )
        active_row = await cursor.fetchone()
        active: int = active_row[0] if active_row else 0

        # Average quality score
        cursor = await self._conn.execute("SELECT AVG(context_quality_score) FROM prebuilt_context")
        avg_quality_row = await cursor.fetchone()
        avg_quality: float = (
            avg_quality_row[0] if avg_quality_row and avg_quality_row[0] is not None else 0.0
        )

        # Last build time
        cursor = await self._conn.execute("SELECT MAX(built_at) FROM prebuilt_context")
        last_build_row = await cursor.fetchone()
        last_build: str | None = last_build_row[0] if last_build_row and last_build_row[0] else None

        return {
            "total": total,
            "active": active,
            "expired": total - active,
            "avg_quality": avg_quality,
            "last_build": last_build,
        }

    async def close(self) -> None:
        """Close database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.debug("Storage connection closed")
