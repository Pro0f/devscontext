"""Tests for the Gmail adapter."""

import base64
from datetime import UTC, datetime

import pytest

from devscontext.adapters.gmail import GmailAdapter
from devscontext.models import GmailConfig


@pytest.fixture
def gmail_config() -> GmailConfig:
    """Create a test Gmail configuration."""
    return GmailConfig(
        credentials_path="/path/to/credentials.json",
        token_path="/path/to/token.json",
        search_scope="newer_than:30d",
        max_results=10,
        labels=["INBOX"],
        enabled=True,
    )


@pytest.fixture
def gmail_adapter(gmail_config: GmailConfig) -> GmailAdapter:
    """Create a test Gmail adapter."""
    return GmailAdapter(gmail_config)


# Sample Gmail API responses
def make_message(
    msg_id: str,
    thread_id: str,
    subject: str,
    sender: str,
    body: str,
    date: str = "Mon, 1 Jan 2024 10:00:00 +0000",
) -> dict:
    """Create a sample Gmail message."""
    body_encoded = base64.urlsafe_b64encode(body.encode()).decode()
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": body[:100],
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": "dev-team@example.com"},
                {"name": "Date", "value": date},
            ],
            "body": {"data": body_encoded},
        },
    }


SAMPLE_MESSAGE = make_message(
    msg_id="msg123",
    thread_id="thread123",
    subject="Re: PROJ-123 Implementation",
    sender="Alice <alice@example.com>",
    body="Here are the requirements for PROJ-123. Please review.",
)

SAMPLE_THREAD = {
    "id": "thread123",
    "messages": [
        make_message(
            msg_id="msg123",
            thread_id="thread123",
            subject="PROJ-123 Implementation",
            sender="Alice <alice@example.com>",
            body="Here are the requirements for PROJ-123. Please review.",
        ),
        make_message(
            msg_id="msg124",
            thread_id="thread123",
            subject="Re: PROJ-123 Implementation",
            sender="Bob <bob@example.com>",
            body="Looks good! I'll start working on it.",
            date="Mon, 1 Jan 2024 11:00:00 +0000",
        ),
    ],
}

SAMPLE_MESSAGE_LIST = {"messages": [{"id": "msg123", "threadId": "thread123"}]}

EMPTY_MESSAGE_LIST = {"messages": []}

SAMPLE_PROFILE = {"emailAddress": "user@example.com"}


class TestGmailAdapter:
    """Tests for GmailAdapter."""

    def test_name(self, gmail_adapter: GmailAdapter) -> None:
        """Test adapter name."""
        assert gmail_adapter.name == "gmail"

    def test_source_type(self, gmail_adapter: GmailAdapter) -> None:
        """Test adapter source type."""
        assert gmail_adapter.source_type == "email"

    async def test_fetch_task_context_disabled_returns_empty(self) -> None:
        """Test that fetch_task_context returns empty when adapter is disabled."""
        config = GmailConfig(credentials_path="/path/to/creds.json", enabled=False)
        adapter = GmailAdapter(config)

        result = await adapter.fetch_task_context("PROJ-123")

        assert result.is_empty()

    async def test_fetch_task_context_no_credentials_returns_empty(self) -> None:
        """Test that fetch_task_context returns empty when no credentials configured."""
        config = GmailConfig(credentials_path="", enabled=True)
        adapter = GmailAdapter(config)

        result = await adapter.fetch_task_context("PROJ-123")

        assert result.is_empty()

    async def test_health_check_disabled(self) -> None:
        """Test health check when adapter is disabled."""
        config = GmailConfig(credentials_path="/path/to/creds.json", enabled=False)
        adapter = GmailAdapter(config)

        result = await adapter.health_check()

        assert result is True  # Disabled adapters are "healthy"

    async def test_health_check_no_credentials(self) -> None:
        """Test health check fails when no credentials configured."""
        config = GmailConfig(credentials_path="", enabled=True)
        adapter = GmailAdapter(config)

        result = await adapter.health_check()

        assert result is False

    async def test_search_disabled_returns_empty(self) -> None:
        """Test search returns empty when adapter is disabled."""
        config = GmailConfig(credentials_path="/path/to/creds.json", enabled=False)
        adapter = GmailAdapter(config)

        results = await adapter.search("PROJ-123")

        assert len(results) == 0


class TestMessageParsing:
    """Tests for Gmail message parsing logic."""

    def test_parse_message_extracts_subject(self, gmail_adapter: GmailAdapter) -> None:
        """Test that subject is extracted from message."""
        result = gmail_adapter._parse_message(SAMPLE_MESSAGE)

        assert result.subject == "Re: PROJ-123 Implementation"

    def test_parse_message_extracts_sender(self, gmail_adapter: GmailAdapter) -> None:
        """Test that sender is extracted from message."""
        result = gmail_adapter._parse_message(SAMPLE_MESSAGE)

        assert result.sender == "alice@example.com"
        assert result.sender_name == "Alice"

    def test_parse_message_extracts_body(self, gmail_adapter: GmailAdapter) -> None:
        """Test that body is extracted from message."""
        result = gmail_adapter._parse_message(SAMPLE_MESSAGE)

        assert "PROJ-123" in result.body_text
        assert "requirements" in result.body_text

    def test_parse_message_extracts_date(self, gmail_adapter: GmailAdapter) -> None:
        """Test that date is extracted from message."""
        result = gmail_adapter._parse_message(SAMPLE_MESSAGE)

        assert result.date.year == 2024
        assert result.date.month == 1
        assert result.date.day == 1


class TestBodyExtraction:
    """Tests for body extraction from various MIME types."""

    def test_extract_body_plain_text(self, gmail_adapter: GmailAdapter) -> None:
        """Test extraction of plain text body."""
        body_text = "This is the message body."
        payload = {
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(body_text.encode()).decode()},
        }

        result = gmail_adapter._extract_body(payload)

        assert result == body_text

    def test_extract_body_html_fallback(self, gmail_adapter: GmailAdapter) -> None:
        """Test extraction of HTML body with tag stripping."""
        html_body = "<html><body><p>Hello <b>world</b>!</p></body></html>"
        payload = {
            "mimeType": "text/html",
            "body": {"data": base64.urlsafe_b64encode(html_body.encode()).decode()},
        }

        result = gmail_adapter._extract_body(payload)

        assert "Hello" in result
        assert "world" in result
        assert "<" not in result  # Tags should be stripped

    def test_extract_body_multipart_finds_plain(self, gmail_adapter: GmailAdapter) -> None:
        """Test extraction from multipart message with plain text part."""
        body_text = "Plain text version."
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode(body_text.encode()).decode()},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": base64.urlsafe_b64encode(b"<p>HTML</p>").decode()},
                },
            ],
        }

        result = gmail_adapter._extract_body(payload)

        assert result == body_text

    def test_extract_body_empty_returns_empty(self, gmail_adapter: GmailAdapter) -> None:
        """Test extraction from empty payload returns empty string."""
        payload = {"mimeType": "text/plain", "body": {}}

        result = gmail_adapter._extract_body(payload)

        assert result == ""


class TestGmailContextFormatting:
    """Tests for Gmail context formatting."""

    def test_format_gmail_context_empty(self, gmail_adapter: GmailAdapter) -> None:
        """Test formatting empty context returns empty string."""
        from devscontext.models import GmailContext

        ctx = GmailContext(threads=[])
        result = gmail_adapter._format_gmail_context(ctx)

        assert result == ""

    def test_format_gmail_context_with_thread(self, gmail_adapter: GmailAdapter) -> None:
        """Test formatting context with threads."""
        from devscontext.models import GmailContext, GmailMessage, GmailThread

        thread = GmailThread(
            thread_id="thread123",
            subject="PROJ-123 Discussion",
            messages=[
                GmailMessage(
                    message_id="msg123",
                    thread_id="thread123",
                    subject="PROJ-123 Discussion",
                    sender="alice@example.com",
                    sender_name="Alice",
                    recipients=["bob@example.com"],
                    date=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
                    body_text="Here are the requirements.",
                )
            ],
            participants=["alice@example.com", "bob@example.com"],
            latest_date=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
        )
        ctx = GmailContext(threads=[thread])

        result = gmail_adapter._format_gmail_context(ctx)

        assert "PROJ-123 Discussion" in result
        assert "Alice" in result
        assert "requirements" in result
