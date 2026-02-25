"""Tests for the pre-built context storage."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from devscontext.models import PrebuiltContext
from devscontext.storage import PrebuiltContextStorage


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    """Create a temporary database path."""
    return str(tmp_path / "test_cache.db")


@pytest.fixture
async def storage(temp_db_path: str) -> PrebuiltContextStorage:
    """Create and initialize a test storage instance."""
    storage = PrebuiltContextStorage(temp_db_path)
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.fixture
def sample_context() -> PrebuiltContext:
    """Create a sample pre-built context."""
    now = datetime.now(UTC)
    return PrebuiltContext(
        task_id="TEST-123",
        synthesized="## Task: TEST-123\n\nSample synthesized content.",
        sources_used=["jira:TEST-123", "docs:readme.md"],
        context_quality_score=0.8,
        gaps=["No acceptance criteria defined"],
        built_at=now,
        expires_at=now + timedelta(hours=24),
        source_data_hash="abc123",
    )


class TestPrebuiltContextStorage:
    """Tests for PrebuiltContextStorage."""

    async def test_initialize_creates_db_and_table(self, temp_db_path: str) -> None:
        """Test that initialization creates the database file and table."""
        storage = PrebuiltContextStorage(temp_db_path)
        await storage.initialize()

        # Database file should exist
        assert Path(temp_db_path).exists()

        # Should be able to close without error
        await storage.close()

    async def test_store_and_get(
        self, storage: PrebuiltContextStorage, sample_context: PrebuiltContext
    ) -> None:
        """Test storing and retrieving context."""
        await storage.store(sample_context)

        retrieved = await storage.get("TEST-123")
        assert retrieved is not None
        assert retrieved.task_id == "TEST-123"
        assert retrieved.synthesized == sample_context.synthesized
        assert retrieved.sources_used == sample_context.sources_used
        assert retrieved.context_quality_score == 0.8
        assert retrieved.gaps == ["No acceptance criteria defined"]
        assert retrieved.source_data_hash == "abc123"

    async def test_get_nonexistent_returns_none(self, storage: PrebuiltContextStorage) -> None:
        """Test that getting a non-existent task returns None."""
        result = await storage.get("NONEXISTENT-999")
        assert result is None

    async def test_store_replaces_existing(
        self, storage: PrebuiltContextStorage, sample_context: PrebuiltContext
    ) -> None:
        """Test that storing replaces existing context with same task_id."""
        await storage.store(sample_context)

        # Create updated context
        now = datetime.now(UTC)
        updated_context = PrebuiltContext(
            task_id="TEST-123",
            synthesized="Updated content",
            sources_used=["jira:TEST-123"],
            context_quality_score=0.9,
            gaps=[],
            built_at=now,
            expires_at=now + timedelta(hours=24),
            source_data_hash="def456",
        )
        await storage.store(updated_context)

        retrieved = await storage.get("TEST-123")
        assert retrieved is not None
        assert retrieved.synthesized == "Updated content"
        assert retrieved.context_quality_score == 0.9
        assert retrieved.source_data_hash == "def456"

    async def test_is_stale_with_matching_hash(
        self, storage: PrebuiltContextStorage, sample_context: PrebuiltContext
    ) -> None:
        """Test staleness check with matching hash returns False."""
        await storage.store(sample_context)
        is_stale = await storage.is_stale("TEST-123", "abc123")
        assert is_stale is False

    async def test_is_stale_with_different_hash(
        self, storage: PrebuiltContextStorage, sample_context: PrebuiltContext
    ) -> None:
        """Test staleness check with different hash returns True."""
        await storage.store(sample_context)
        is_stale = await storage.is_stale("TEST-123", "new_hash")
        assert is_stale is True

    async def test_is_stale_nonexistent_returns_true(self, storage: PrebuiltContextStorage) -> None:
        """Test staleness check for non-existent task returns True."""
        is_stale = await storage.is_stale("NONEXISTENT-999", "any_hash")
        assert is_stale is True

    async def test_delete(
        self, storage: PrebuiltContextStorage, sample_context: PrebuiltContext
    ) -> None:
        """Test deleting context."""
        await storage.store(sample_context)

        deleted = await storage.delete("TEST-123")
        assert deleted is True

        # Should be gone
        result = await storage.get("TEST-123")
        assert result is None

    async def test_delete_nonexistent_returns_false(self, storage: PrebuiltContextStorage) -> None:
        """Test deleting non-existent task returns False."""
        deleted = await storage.delete("NONEXISTENT-999")
        assert deleted is False

    async def test_delete_expired(self, storage: PrebuiltContextStorage) -> None:
        """Test deleting expired entries."""
        now = datetime.now(UTC)

        # Add expired context
        expired_context = PrebuiltContext(
            task_id="EXPIRED-1",
            synthesized="Expired content",
            sources_used=[],
            context_quality_score=0.5,
            gaps=[],
            built_at=now - timedelta(hours=48),
            expires_at=now - timedelta(hours=24),  # Expired 24 hours ago
            source_data_hash="old_hash",
        )
        await storage.store(expired_context)

        # Add active context
        active_context = PrebuiltContext(
            task_id="ACTIVE-1",
            synthesized="Active content",
            sources_used=[],
            context_quality_score=0.5,
            gaps=[],
            built_at=now,
            expires_at=now + timedelta(hours=24),  # Expires in 24 hours
            source_data_hash="new_hash",
        )
        await storage.store(active_context)

        deleted_count = await storage.delete_expired()
        assert deleted_count == 1

        # Expired should be gone
        assert await storage.get("EXPIRED-1") is None

        # Active should still exist
        assert await storage.get("ACTIVE-1") is not None

    async def test_list_all(
        self, storage: PrebuiltContextStorage, sample_context: PrebuiltContext
    ) -> None:
        """Test listing all contexts."""
        await storage.store(sample_context)

        now = datetime.now(UTC)
        another_context = PrebuiltContext(
            task_id="TEST-456",
            synthesized="Another content",
            sources_used=["jira:TEST-456"],
            context_quality_score=0.6,
            gaps=["Gap 1", "Gap 2"],
            built_at=now,
            expires_at=now + timedelta(hours=24),
            source_data_hash="xyz789",
        )
        await storage.store(another_context)

        all_contexts = await storage.list_all()
        assert len(all_contexts) == 2

        task_ids = [c["task_id"] for c in all_contexts]
        assert "TEST-123" in task_ids
        assert "TEST-456" in task_ids

    async def test_get_stats(
        self, storage: PrebuiltContextStorage, sample_context: PrebuiltContext
    ) -> None:
        """Test getting storage statistics."""
        await storage.store(sample_context)

        stats = await storage.get_stats()
        assert stats["total"] == 1
        assert stats["active"] == 1
        assert stats["expired"] == 0
        assert stats["avg_quality"] == 0.8
        assert stats["last_build"] is not None


class TestPrebuiltContextModel:
    """Tests for PrebuiltContext model."""

    def test_is_expired_returns_false_for_future(self) -> None:
        """Test is_expired returns False for future expiration."""
        now = datetime.now(UTC)
        context = PrebuiltContext(
            task_id="TEST-1",
            synthesized="Content",
            sources_used=[],
            context_quality_score=0.5,
            gaps=[],
            built_at=now,
            expires_at=now + timedelta(hours=24),
            source_data_hash="hash",
        )
        assert context.is_expired() is False

    def test_is_expired_returns_true_for_past(self) -> None:
        """Test is_expired returns True for past expiration."""
        now = datetime.now(UTC)
        context = PrebuiltContext(
            task_id="TEST-1",
            synthesized="Content",
            sources_used=[],
            context_quality_score=0.5,
            gaps=[],
            built_at=now - timedelta(hours=48),
            expires_at=now - timedelta(hours=24),
            source_data_hash="hash",
        )
        assert context.is_expired() is True
