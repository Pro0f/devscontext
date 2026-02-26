"""Slack adapter for fetching team discussion context.

This adapter connects to Slack Web API to search for messages mentioning
ticket IDs or keywords, fetches full threads, and extracts decisions/actions.

Implements the Adapter interface for the plugin system.

Example:
    config = SlackConfig(bot_token="xoxb-...", channels=["engineering"])
    adapter = SlackAdapter(config)
    context = await adapter.fetch_task_context("PROJ-123", ticket)
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

import httpx

from devscontext.constants import (
    ADAPTER_SLACK,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    SLACK_API_BASE_URL,
    SLACK_CHANNEL_HISTORY_CACHE_TTL,
    SLACK_MAX_MESSAGES_PER_CHANNEL,
    SLACK_RATE_LIMIT_REQUESTS_PER_MINUTE,
    SLACK_THREAD_REPLY_LIMIT,
    SOURCE_TYPE_COMMUNICATION,
)
from devscontext.logging import get_logger
from devscontext.models import (
    SlackConfig,
    SlackContext,
    SlackMessage,
    SlackThread,
)
from devscontext.plugins.base import Adapter, SearchResult, SourceContext
from devscontext.utils import extract_keywords

if TYPE_CHECKING:
    from devscontext.models import JiraTicket

logger = get_logger(__name__)


# Decision patterns for extraction
DECISION_PATTERNS = [
    re.compile(r"(?:we(?:'ve|'ll| will| have)?\s+)?decided\s+(?:to\s+)?(.+)", re.IGNORECASE),
    re.compile(r"let's\s+(?:go\s+with|use|do)\s+(.+)", re.IGNORECASE),
    re.compile(r"agreed[:\s]+(.+)", re.IGNORECASE),
    re.compile(r"decision[:\s]+(.+)", re.IGNORECASE),
    re.compile(r"we(?:'re| are)\s+going\s+(?:to|with)\s+(.+)", re.IGNORECASE),
]

# Action item patterns for extraction
ACTION_PATTERNS = [
    re.compile(r"(?:i(?:'ll| will|'m going to)\s+)(.+)", re.IGNORECASE),
    re.compile(r"@\w+\s+(?:can you|please|will you|could you)\s+(.+)", re.IGNORECASE),
    re.compile(r"action item[:\s]+(.+)", re.IGNORECASE),
    re.compile(r"todo[:\s]+(.+)", re.IGNORECASE),
    re.compile(r"need(?:s)? to\s+(.+)", re.IGNORECASE),
]


class RateLimiter:
    """Simple rate limiter for Slack API calls."""

    def __init__(self, requests_per_minute: int = SLACK_RATE_LIMIT_REQUESTS_PER_MINUTE) -> None:
        """Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per minute.
        """
        self._requests_per_minute = requests_per_minute
        self._request_times: list[float] = []

    async def acquire(self) -> None:
        """Wait if necessary to respect rate limits."""
        now = time.monotonic()
        minute_ago = now - 60

        # Remove old requests
        self._request_times = [t for t in self._request_times if t > minute_ago]

        if len(self._request_times) >= self._requests_per_minute:
            # Wait until oldest request is more than a minute old
            sleep_time = 60 - (now - self._request_times[0]) + 0.1
            if sleep_time > 0:
                logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)

        self._request_times.append(time.monotonic())


class ChannelHistoryCache:
    """Simple cache for channel history to avoid repeated fetches."""

    def __init__(self, ttl_seconds: int = SLACK_CHANNEL_HISTORY_CACHE_TTL) -> None:
        """Initialize cache.

        Args:
            ttl_seconds: Time-to-live for cached entries in seconds.
        """
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def get(self, channel_id: str) -> list[dict[str, Any]] | None:
        """Get cached history if not expired.

        Args:
            channel_id: The channel ID to look up.

        Returns:
            Cached messages or None if not found/expired.
        """
        if channel_id in self._cache:
            timestamp, messages = self._cache[channel_id]
            if time.monotonic() - timestamp < self._ttl:
                return messages
            del self._cache[channel_id]
        return None

    def set(self, channel_id: str, messages: list[dict[str, Any]]) -> None:
        """Cache channel history.

        Args:
            channel_id: The channel ID to cache.
            messages: The messages to cache.
        """
        self._cache[channel_id] = (time.monotonic(), messages)

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()


class SlackAdapter(Adapter):
    """Adapter for fetching context from Slack conversations.

    Implements the Adapter interface for the plugin system.
    Searches for messages mentioning ticket IDs or keywords,
    fetches full threads, and extracts decisions/actions.

    Class Attributes:
        name: Adapter identifier ("slack").
        source_type: Source category ("communication").
        config_schema: Configuration model (SlackConfig).
    """

    name: ClassVar[str] = ADAPTER_SLACK
    source_type: ClassVar[str] = SOURCE_TYPE_COMMUNICATION
    config_schema: ClassVar[type[SlackConfig]] = SlackConfig

    def __init__(self, config: SlackConfig) -> None:
        """Initialize the Slack adapter.

        Args:
            config: Slack configuration with bot token and channels.
        """
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._rate_limiter = RateLimiter()
        self._channel_cache = ChannelHistoryCache()
        self._channel_id_map: dict[str, str] = {}  # name -> id
        self._user_name_cache: dict[str, str] = {}  # user_id -> display_name

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=SLACK_API_BASE_URL,
                headers={
                    "Authorization": f"Bearer {self._config.bot_token}",
                    "Content-Type": "application/json",
                },
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client and clear caches."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._channel_cache.clear()
        self._channel_id_map.clear()
        self._user_name_cache.clear()

    async def _api_call(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a rate-limited Slack API call with error handling.

        Args:
            method: HTTP method (GET or POST).
            endpoint: API endpoint path.
            params: Query parameters or POST body.

        Returns:
            API response as dict.
        """
        await self._rate_limiter.acquire()
        client = self._get_client()

        try:
            if method.upper() == "GET":
                response = await client.get(endpoint, params=params)
            else:
                response = await client.post(endpoint, json=params)

            response.raise_for_status()
            data: dict[str, Any] = response.json()

            if not data.get("ok"):
                error = data.get("error", "unknown_error")
                logger.warning(
                    "Slack API error",
                    extra={"endpoint": endpoint, "error": error},
                )

                # Handle rate limiting response
                if error == "ratelimited":
                    retry_after = int(data.get("retry_after", 30))
                    logger.info(f"Rate limited, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    return await self._api_call(method, endpoint, params)

                return {"ok": False, "error": error}

            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                retry_after = int(e.response.headers.get("Retry-After", "30"))
                logger.info(f"Rate limited (429), waiting {retry_after}s")
                await asyncio.sleep(retry_after)
                return await self._api_call(method, endpoint, params)
            logger.warning(
                "Slack HTTP error",
                extra={"status_code": e.response.status_code, "endpoint": endpoint},
            )
            return {"ok": False, "error": f"http_{e.response.status_code}"}

        except httpx.RequestError as e:
            logger.warning("Slack request error", extra={"error": str(e)})
            return {"ok": False, "error": "network_error"}

    async def _resolve_channel_ids(self) -> dict[str, str]:
        """Resolve channel names to IDs.

        Returns:
            Dict mapping channel names to IDs.
        """
        if self._channel_id_map:
            return self._channel_id_map

        # Get list of channels the bot is in
        data = await self._api_call(
            "GET",
            "/conversations.list",
            {"types": "public_channel,private_channel", "limit": 200},
        )

        if not data.get("ok"):
            return {}

        for channel in data.get("channels", []):
            name = channel.get("name", "")
            channel_id = channel.get("id", "")
            if name and channel_id:
                self._channel_id_map[name] = channel_id

        return self._channel_id_map

    async def _resolve_user_name(self, user_id: str) -> str:
        """Resolve user ID to display name.

        Args:
            user_id: Slack user ID.

        Returns:
            User display name or the user ID if lookup fails.
        """
        if user_id in self._user_name_cache:
            return self._user_name_cache[user_id]

        data = await self._api_call("GET", "/users.info", {"user": user_id})

        if not data.get("ok"):
            return user_id

        user = data.get("user", {})
        profile = user.get("profile", {})
        name = profile.get("display_name") or profile.get("real_name") or user_id
        self._user_name_cache[user_id] = name
        return name

    async def _search_messages(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for messages using Slack search API.

        Falls back to channel history if search is not available (free plan).

        Args:
            query: Search query string.
            max_results: Maximum number of results.

        Returns:
            List of matching message dicts.
        """
        # Try search API first (requires paid plan)
        data = await self._api_call(
            "GET",
            "/search.messages",
            {
                "query": query,
                "count": max_results,
                "sort": "timestamp",
                "sort_dir": "desc",
            },
        )

        if data.get("ok"):
            matches: list[dict[str, Any]] = data.get("messages", {}).get("matches", [])
            if matches:
                logger.debug(f"Found {len(matches)} messages via search API")
                return matches

        # Fall back to channel history search
        logger.debug("Search API unavailable, falling back to channel history")
        return await self._search_channel_history(query, max_results)

    async def _search_channel_history(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Search channel history manually (for free Slack plans).

        Args:
            query: Search query string.
            max_results: Maximum number of results.

        Returns:
            List of matching message dicts.
        """
        channel_ids = await self._resolve_channel_ids()

        # Filter to configured channels
        target_channels = [
            (name, channel_ids[name]) for name in self._config.channels if name in channel_ids
        ]

        if not target_channels:
            logger.warning("No configured channels found")
            return []

        oldest = (datetime.now(UTC) - timedelta(days=self._config.lookback_days)).timestamp()
        query_lower = query.lower()
        matching_messages: list[dict[str, Any]] = []

        for channel_name, channel_id in target_channels:
            # Check cache first
            cached = self._channel_cache.get(channel_id)

            if cached is None:
                data = await self._api_call(
                    "GET",
                    "/conversations.history",
                    {
                        "channel": channel_id,
                        "oldest": str(oldest),
                        "limit": SLACK_MAX_MESSAGES_PER_CHANNEL,
                    },
                )

                if not data.get("ok"):
                    continue

                cached = data.get("messages", [])
                self._channel_cache.set(channel_id, cached)

            # Search through messages
            for msg in cached:
                text = msg.get("text", "").lower()
                if query_lower in text:
                    # Add channel info to message
                    msg_copy = dict(msg)
                    msg_copy["channel"] = channel_id
                    msg_copy["_channel_name"] = channel_name
                    matching_messages.append(msg_copy)

                    if len(matching_messages) >= max_results:
                        return matching_messages

        return matching_messages

    async def _fetch_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> list[dict[str, Any]]:
        """Fetch all replies in a thread.

        Args:
            channel_id: The channel containing the thread.
            thread_ts: The thread timestamp.

        Returns:
            List of message dicts in the thread.
        """
        data = await self._api_call(
            "GET",
            "/conversations.replies",
            {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": SLACK_THREAD_REPLY_LIMIT,
            },
        )

        if not data.get("ok"):
            return []

        messages: list[dict[str, Any]] = data.get("messages", [])
        return messages

    def _parse_message(
        self,
        msg: dict[str, Any],
        channel_id: str,
        channel_name: str,
        user_names: dict[str, str],
    ) -> SlackMessage:
        """Parse a Slack message into our model.

        Args:
            msg: Raw message dict from Slack API.
            channel_id: The channel ID.
            channel_name: The channel name.
            user_names: Dict mapping user IDs to display names.

        Returns:
            SlackMessage instance.
        """
        user_id = msg.get("user", "unknown")
        ts = msg.get("ts", "0")

        # Convert timestamp
        try:
            timestamp = datetime.fromtimestamp(float(ts), tz=UTC)
        except (ValueError, TypeError):
            timestamp = datetime.now(UTC)

        # Get reactions as emoji names
        reactions = []
        for reaction in msg.get("reactions", []):
            reactions.append(reaction.get("name", ""))

        return SlackMessage(
            message_id=ts,
            channel_id=channel_id,
            channel_name=channel_name,
            user_id=user_id,
            user_name=user_names.get(user_id, user_id),
            text=msg.get("text", ""),
            timestamp=timestamp,
            thread_ts=msg.get("thread_ts") if msg.get("thread_ts") != ts else None,
            permalink=msg.get("permalink"),
            reactions=reactions,
        )

    def _extract_decisions(self, text: str) -> list[str]:
        """Extract decisions from message text.

        Args:
            text: Message text to analyze.

        Returns:
            List of extracted decision strings.
        """
        decisions = []

        for pattern in DECISION_PATTERNS:
            for match in pattern.finditer(text):
                decision = match.group(1).strip()
                # Filter out too short or too long
                if 10 < len(decision) < 200:
                    decisions.append(decision[:200])

        return decisions[:10]  # Limit to 10 decisions

    def _extract_action_items(self, text: str) -> list[str]:
        """Extract action items from message text.

        Args:
            text: Message text to analyze.

        Returns:
            List of extracted action item strings.
        """
        actions = []

        for pattern in ACTION_PATTERNS:
            for match in pattern.finditer(text):
                action = match.group(1).strip()
                # Filter out too short or too long
                if 5 < len(action) < 200:
                    actions.append(action[:200])

        return actions[:10]  # Limit to 10 actions

    async def fetch_task_context(
        self,
        task_id: str,
        ticket: JiraTicket | None = None,
    ) -> SourceContext:
        """Fetch context from Slack conversations.

        Search strategy:
        1. Search for exact ticket ID (e.g., "PROJ-123")
        2. Search for keywords from ticket title
        3. Fetch full threads for matching messages
        4. Extract decisions and action items

        Args:
            task_id: The task identifier to search for.
            ticket: Optional Jira ticket for keyword extraction.

        Returns:
            SourceContext with SlackContext data.
        """
        if not self._config.enabled:
            logger.debug("Slack adapter is disabled")
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
            )

        if not self._config.bot_token:
            logger.warning("Slack adapter missing bot token")
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
            )

        # Build search queries
        search_queries = [task_id]
        if ticket:
            keywords = extract_keywords(ticket.title)[:5]
            search_queries.extend(keywords)

        # Collect matching messages
        all_matches: list[dict[str, Any]] = []
        seen_ts: set[str] = set()

        for query in search_queries:
            matches = await self._search_messages(
                query,
                max_results=self._config.max_messages // max(len(search_queries), 1),
            )
            for msg in matches:
                ts = msg.get("ts", "")
                if ts and ts not in seen_ts:
                    seen_ts.add(ts)
                    all_matches.append(msg)

        if not all_matches:
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=SlackContext(),
                raw_text="",
                metadata={"task_id": task_id, "thread_count": 0},
            )

        # Resolve channel names and user names
        channel_ids = await self._resolve_channel_ids()
        id_to_name = {v: k for k, v in channel_ids.items()}

        # Collect unique user IDs
        user_ids: set[str] = set()
        for msg in all_matches:
            if msg.get("user"):
                user_ids.add(msg["user"])

        # Resolve user names
        user_names: dict[str, str] = {}
        for user_id in user_ids:
            user_names[user_id] = await self._resolve_user_name(user_id)

        # Group by thread and fetch full threads
        threads: list[SlackThread] = []
        standalone: list[SlackMessage] = []
        processed_threads: set[str] = set()

        for msg in all_matches:
            channel_id = msg.get("channel", "")
            channel_name = msg.get("_channel_name") or id_to_name.get(channel_id, channel_id)
            thread_ts = msg.get("thread_ts") or msg.get("ts", "")

            # Skip if we've already processed this thread
            thread_key = f"{channel_id}:{thread_ts}"
            if thread_key in processed_threads:
                continue
            processed_threads.add(thread_key)

            reply_count = msg.get("reply_count", 0)
            if self._config.include_threads and reply_count > 0:
                # Fetch full thread
                thread_msgs = await self._fetch_thread(channel_id, thread_ts)

                if thread_msgs:
                    # Resolve user names for thread participants
                    for thread_msg in thread_msgs:
                        thread_user_id: str | None = thread_msg.get("user")
                        if thread_user_id and thread_user_id not in user_names:
                            user_names[thread_user_id] = await self._resolve_user_name(
                                thread_user_id
                            )

                    parent = self._parse_message(
                        thread_msgs[0], channel_id, channel_name, user_names
                    )
                    replies = [
                        self._parse_message(m, channel_id, channel_name, user_names)
                        for m in thread_msgs[1:]
                    ]

                    # Extract decisions and actions from all messages
                    all_decisions: list[str] = []
                    all_actions: list[str] = []
                    participants: set[str] = {parent.user_name}

                    for m in [parent, *replies]:
                        all_decisions.extend(self._extract_decisions(m.text))
                        all_actions.extend(self._extract_action_items(m.text))
                        participants.add(m.user_name)

                    threads.append(
                        SlackThread(
                            parent_message=parent,
                            replies=replies,
                            participant_names=list(participants),
                            decisions=all_decisions[:10],
                            action_items=all_actions[:10],
                        )
                    )
            else:
                # Standalone message
                parsed = self._parse_message(msg, channel_id, channel_name, user_names)
                standalone.append(parsed)

        slack_context = SlackContext(
            threads=threads,
            standalone_messages=standalone,
        )

        raw_text = self._format_slack_context(slack_context)

        logger.info(
            "Slack context assembled",
            extra={
                "task_id": task_id,
                "thread_count": len(threads),
                "standalone_count": len(standalone),
            },
        )

        return SourceContext(
            source_name=self.name,
            source_type=self.source_type,
            data=slack_context,
            raw_text=raw_text,
            metadata={
                "task_id": task_id,
                "thread_count": len(threads),
                "standalone_count": len(standalone),
            },
        )

    def _format_slack_context(self, context: SlackContext) -> str:
        """Format Slack context as raw text for synthesis.

        Args:
            context: SlackContext with threads and messages.

        Returns:
            Formatted markdown string.
        """
        parts: list[str] = []

        for thread in context.threads:
            thread_parts = [
                f"## #{thread.parent_message.channel_name} Thread",
                f"**Started:** {thread.parent_message.timestamp.strftime('%Y-%m-%d %H:%M')}",
                f"**Participants:** {', '.join(thread.participant_names)}",
                "",
                f"**{thread.parent_message.user_name}:** {thread.parent_message.text}",
            ]

            for reply in thread.replies[:10]:
                thread_parts.append(f"**{reply.user_name}:** {reply.text}")

            if thread.decisions:
                thread_parts.append("\n**Decisions:**")
                for d in thread.decisions:
                    thread_parts.append(f"- {d}")

            if thread.action_items:
                thread_parts.append("\n**Action Items:**")
                for a in thread.action_items:
                    thread_parts.append(f"- {a}")

            parts.append("\n".join(thread_parts))

        for msg in context.standalone_messages[:10]:
            parts.append(
                f"**#{msg.channel_name}** ({msg.timestamp.strftime('%Y-%m-%d')}) "
                f"**{msg.user_name}:** {msg.text}"
            )

        return "\n\n---\n\n".join(parts)

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search Slack messages matching the query.

        Args:
            query: Search terms.
            max_results: Maximum number of results.

        Returns:
            List of SearchResult items.
        """
        if not self._config.enabled or not self._config.bot_token:
            return []

        matches = await self._search_messages(query, max_results)

        results: list[SearchResult] = []
        for msg in matches[:max_results]:
            text = msg.get("text", "")[:300]

            # Get channel name
            channel = msg.get("channel", "")
            channel_name = msg.get("_channel_name", "")
            if not channel_name and isinstance(channel, dict):
                channel_name = channel.get("name", "")

            results.append(
                SearchResult(
                    source_name=self.name,
                    source_type=self.source_type,
                    title=f"Slack: #{channel_name}" if channel_name else "Slack message",
                    excerpt=text,
                    url=msg.get("permalink"),
                    metadata={
                        "channel": channel_name,
                        "ts": msg.get("ts"),
                    },
                )
            )

        return results

    async def health_check(self) -> bool:
        """Check if Slack is configured and accessible.

        Returns:
            True if healthy or disabled, False if there's an issue.
        """
        if not self._config.enabled:
            return True

        if not self._config.bot_token:
            logger.warning("Slack adapter missing bot token")
            return False

        data = await self._api_call("GET", "/auth.test")

        if data.get("ok"):
            logger.info("Slack health check passed")
            return True

        logger.warning(f"Slack health check failed: {data.get('error')}")
        return False
