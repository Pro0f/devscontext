"""Gmail adapter for fetching email context.

This adapter connects to Gmail API to search for emails mentioning
ticket IDs or keywords, groups by thread, and extracts content.

Implements the Adapter interface for the plugin system.

OAuth Notes:
- First run requires browser authentication
- Subsequent runs use stored refresh token
- Token is stored at config.token_path

Example:
    config = GmailConfig(credentials_path="credentials.json", enabled=True)
    adapter = GmailAdapter(config)
    context = await adapter.fetch_task_context("PROJ-123", ticket)
"""

from __future__ import annotations

import asyncio
import base64
import re
from datetime import UTC, datetime
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from devscontext.constants import (
    ADAPTER_GMAIL,
    GMAIL_API_SCOPES,
    GMAIL_BODY_MAX_CHARS,
    GMAIL_MAX_RESULTS_PER_QUERY,
    SOURCE_TYPE_EMAIL,
)
from devscontext.logging import get_logger
from devscontext.models import (
    GmailConfig,
    GmailContext,
    GmailMessage,
    GmailThread,
)
from devscontext.plugins.base import Adapter, SearchResult, SourceContext
from devscontext.utils import extract_keywords, truncate_text

if TYPE_CHECKING:
    from devscontext.models import JiraTicket

logger = get_logger(__name__)


class GmailAdapter(Adapter):
    """Adapter for fetching context from Gmail.

    Implements the Adapter interface for the plugin system.
    Searches for emails mentioning ticket IDs or keywords,
    groups by conversation thread, and extracts content.

    Class Attributes:
        name: Adapter identifier ("gmail").
        source_type: Source category ("email").
        config_schema: Configuration model (GmailConfig).

    OAuth Notes:
        - First run requires browser authentication via OAuth flow
        - Subsequent runs use stored refresh token from token_path
        - Only read-only access is requested (gmail.readonly scope)
    """

    name: ClassVar[str] = ADAPTER_GMAIL
    source_type: ClassVar[str] = SOURCE_TYPE_EMAIL
    config_schema: ClassVar[type[GmailConfig]] = GmailConfig

    def __init__(self, config: GmailConfig) -> None:
        """Initialize the Gmail adapter.

        Args:
            config: Gmail configuration with credentials path.
        """
        self._config = config
        self._service: Any = None
        self._credentials: Any = None

    def _get_service(self) -> Any:
        """Get or create the Gmail API service (lazy initialization).

        Returns:
            Gmail API service object.

        Raises:
            ImportError: If google-api-python-client is not installed.
            ValueError: If credentials cannot be loaded.
        """
        if self._service is not None:
            return self._service

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as e:
            raise ImportError(
                "google-api-python-client not installed. "
                "Install with: pip install devscontext[gmail]"
            ) from e

        creds = None
        token_path = Path(self._config.token_path)
        credentials_path = Path(self._config.credentials_path)

        # Load existing token if available
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_API_SCOPES)
            except Exception as e:
                logger.warning(f"Failed to load token: {e}")

        # Refresh or get new credentials
        if creds is None or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning(f"Failed to refresh token: {e}")
                    creds = None

            if creds is None:
                if not credentials_path.exists():
                    raise ValueError(f"Gmail credentials file not found: {credentials_path}")

                # This will open browser for auth on first run
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path),
                    GMAIL_API_SCOPES,
                )
                creds = flow.run_local_server(port=0)

            # Save token for future use
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())

        self._credentials = creds
        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    async def close(self) -> None:
        """Close resources."""
        self._service = None
        self._credentials = None

    async def _search_emails(
        self,
        query: str,
        max_results: int = GMAIL_MAX_RESULTS_PER_QUERY,
    ) -> list[dict[str, Any]]:
        """Search Gmail for messages matching query.

        Args:
            query: Gmail search query (supports Gmail search operators).
            max_results: Maximum number of messages to return.

        Returns:
            List of message metadata dicts with id and threadId.
        """
        try:
            service = self._get_service()

            # Add scope filter from config
            full_query = f"{query} {self._config.search_scope}"

            # Add label filter if configured
            if self._config.labels:
                label_query = " OR ".join(f"label:{label}" for label in self._config.labels)
                full_query = f"({full_query}) ({label_query})"

            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: (
                    service.users()
                    .messages()
                    .list(
                        userId="me",
                        q=full_query,
                        maxResults=max_results,
                    )
                    .execute()
                ),
            )

            return result.get("messages", [])

        except ImportError:
            logger.warning("Gmail dependencies not installed")
            return []
        except Exception as e:
            logger.warning(f"Gmail search failed: {e}")
            return []

    async def _get_message(self, message_id: str) -> dict[str, Any] | None:
        """Fetch full message content by ID.

        Args:
            message_id: Gmail message ID.

        Returns:
            Message dict or None if fetch fails.
        """
        try:
            service = self._get_service()

            loop = asyncio.get_event_loop()
            msg = await loop.run_in_executor(
                None,
                lambda: (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=message_id,
                        format="full",
                    )
                    .execute()
                ),
            )

            return msg

        except Exception as e:
            logger.warning(f"Failed to fetch message {message_id}: {e}")
            return None

    async def _get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Fetch full thread with all messages.

        Args:
            thread_id: Gmail thread ID.

        Returns:
            Thread dict or None if fetch fails.
        """
        try:
            service = self._get_service()

            loop = asyncio.get_event_loop()
            thread = await loop.run_in_executor(
                None,
                lambda: (
                    service.users()
                    .threads()
                    .get(
                        userId="me",
                        id=thread_id,
                        format="full",
                    )
                    .execute()
                ),
            )

            return thread

        except Exception as e:
            logger.warning(f"Failed to fetch thread {thread_id}: {e}")
            return None

    def _parse_message(self, msg: dict[str, Any]) -> GmailMessage:
        """Parse Gmail API message into our model.

        Args:
            msg: Raw message dict from Gmail API.

        Returns:
            GmailMessage instance.
        """
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}

        # Parse sender
        sender_raw = headers.get("from", "")
        sender_name, sender_email = parseaddr(sender_raw)

        # Parse recipients
        to_raw = headers.get("to", "")
        recipients = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

        cc_raw = headers.get("cc", "")
        cc = [addr.strip() for addr in cc_raw.split(",") if addr.strip()]

        # Parse date
        date_str = headers.get("date", "")
        try:
            date = parsedate_to_datetime(date_str)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            date = datetime.now(UTC)

        # Extract body
        body_text = self._extract_body(msg.get("payload", {}))

        return GmailMessage(
            message_id=msg.get("id", ""),
            thread_id=msg.get("threadId", ""),
            subject=headers.get("subject", "(no subject)"),
            sender=sender_email or sender_raw,
            sender_name=sender_name or None,
            recipients=recipients,
            cc=cc,
            date=date,
            snippet=msg.get("snippet", ""),
            body_text=truncate_text(body_text, GMAIL_BODY_MAX_CHARS),
            labels=msg.get("labelIds", []),
        )

    def _extract_body(self, payload: dict[str, Any]) -> str:
        """Extract plain text body from message payload.

        Recursively searches for text/plain parts, falling back to
        HTML with tags stripped if no plain text is found.

        Args:
            payload: Message payload dict.

        Returns:
            Extracted body text.
        """
        # Try to find plain text part
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Check parts recursively
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

            # Recurse into nested parts
            nested = self._extract_body(part)
            if nested:
                return nested

        # Fall back to HTML if no plain text
        if payload.get("mimeType") == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                # Strip HTML tags (simple approach)
                return re.sub(r"<[^>]+>", " ", html).strip()

        return ""

    async def fetch_task_context(
        self,
        task_id: str,
        ticket: JiraTicket | None = None,
    ) -> SourceContext:
        """Fetch context from Gmail.

        Search strategy:
        1. Search for exact ticket ID in subject/body
        2. Search for keywords from ticket title
        3. Group results by thread
        4. Fetch full thread content

        Args:
            task_id: The task identifier to search for.
            ticket: Optional Jira ticket for keyword extraction.

        Returns:
            SourceContext with GmailContext data.
        """
        if not self._config.enabled:
            logger.debug("Gmail adapter is disabled")
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
            )

        if not self._config.credentials_path:
            logger.warning("Gmail adapter missing credentials path")
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
            )

        # Build search queries
        search_terms = [task_id]
        if ticket:
            keywords = extract_keywords(ticket.title)[:3]
            search_terms.extend(keywords)

        # Search with all terms combined
        query = " OR ".join(f'"{term}"' for term in search_terms)
        message_refs = await self._search_emails(query, self._config.max_results)

        if not message_refs:
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=GmailContext(),
                raw_text="",
                metadata={"task_id": task_id, "thread_count": 0},
            )

        # Group by thread and fetch full threads
        thread_ids = list({m.get("threadId") for m in message_refs if m.get("threadId")})
        threads: list[GmailThread] = []

        for thread_id in thread_ids[:10]:  # Limit threads to avoid too many API calls
            thread_data = await self._get_thread(thread_id)
            if not thread_data:
                continue

            messages = [self._parse_message(m) for m in thread_data.get("messages", [])]

            if not messages:
                continue

            # Get participants from all messages
            participants: set[str] = set()
            for msg in messages:
                participants.add(msg.sender)
                participants.update(msg.recipients)

            threads.append(
                GmailThread(
                    thread_id=thread_id,
                    subject=messages[0].subject,
                    messages=messages,
                    participants=list(participants),
                    latest_date=max(m.date for m in messages),
                )
            )

        # Sort threads by latest date
        threads.sort(key=lambda t: t.latest_date, reverse=True)

        gmail_context = GmailContext(threads=threads)
        raw_text = self._format_gmail_context(gmail_context)

        logger.info(
            "Gmail context assembled",
            extra={
                "task_id": task_id,
                "thread_count": len(threads),
                "message_count": sum(len(t.messages) for t in threads),
            },
        )

        return SourceContext(
            source_name=self.name,
            source_type=self.source_type,
            data=gmail_context,
            raw_text=raw_text,
            metadata={
                "task_id": task_id,
                "thread_count": len(threads),
                "message_count": sum(len(t.messages) for t in threads),
            },
        )

    def _format_gmail_context(self, context: GmailContext) -> str:
        """Format Gmail context as raw text for synthesis.

        Args:
            context: GmailContext with threads.

        Returns:
            Formatted markdown string.
        """
        parts: list[str] = []

        for thread in context.threads:
            thread_parts = [
                f"## Email Thread: {thread.subject}",
                f"**Participants:** {', '.join(thread.participants[:5])}",
                f"**Latest:** {thread.latest_date.strftime('%Y-%m-%d')}",
                "",
            ]

            for msg in thread.messages[:5]:  # Limit messages per thread
                sender = msg.sender_name or msg.sender
                date_str = msg.date.strftime("%Y-%m-%d %H:%M")
                thread_parts.append(f"**{sender}** ({date_str}):")
                thread_parts.append(msg.body_text or msg.snippet)
                thread_parts.append("")

            parts.append("\n".join(thread_parts))

        return "\n\n---\n\n".join(parts)

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search Gmail for emails matching the query.

        Args:
            query: Search terms.
            max_results: Maximum number of results.

        Returns:
            List of SearchResult items.
        """
        if not self._config.enabled:
            return []

        message_refs = await self._search_emails(query, max_results)

        results: list[SearchResult] = []
        for ref in message_refs[:max_results]:
            msg = await self._get_message(ref.get("id", ""))
            if not msg:
                continue

            parsed = self._parse_message(msg)

            results.append(
                SearchResult(
                    source_name=self.name,
                    source_type=self.source_type,
                    title=parsed.subject,
                    excerpt=parsed.snippet,
                    metadata={
                        "from": parsed.sender,
                        "date": parsed.date.isoformat(),
                        "thread_id": parsed.thread_id,
                    },
                )
            )

        return results

    async def health_check(self) -> bool:
        """Check if Gmail is configured and accessible.

        Returns:
            True if healthy or disabled, False if there's an issue.
        """
        if not self._config.enabled:
            return True

        if not self._config.credentials_path:
            logger.warning("Gmail adapter missing credentials path")
            return False

        try:
            service = self._get_service()

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: service.users().getProfile(userId="me").execute(),
            )

            if result.get("emailAddress"):
                logger.info("Gmail health check passed")
                return True

            return False

        except ImportError:
            logger.warning("Gmail dependencies not installed")
            return False
        except Exception as e:
            logger.warning(f"Gmail health check failed: {e}")
            return False
