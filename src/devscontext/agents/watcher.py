"""Jira watcher for detecting tickets ready for pre-processing.

This module provides polling-based detection of Jira tickets that have
moved to a target status (e.g., "Ready for Development"). When new tickets
are detected, they are passed to the preprocessing pipeline.

Example:
    watcher = JiraWatcher(config, pipeline)
    await watcher.run()  # Runs until stopped
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx

from devscontext.logging import get_logger

if TYPE_CHECKING:
    from devscontext.agents.preprocessor import PreprocessingPipeline
    from devscontext.models import DevsContextConfig

logger = get_logger(__name__)

# Jira API paths
JIRA_API_BASE_PATH = "/rest/api/3"


class JiraWatcher:
    """Watches Jira for tickets in target status.

    Polls Jira periodically using JQL to find tickets in the configured
    status (e.g., "Ready for Development"). New tickets are passed to
    the preprocessing pipeline.

    Tracks already-processed tickets to avoid reprocessing.
    """

    def __init__(
        self,
        config: DevsContextConfig,
        pipeline: PreprocessingPipeline,
    ) -> None:
        """Initialize the watcher.

        Args:
            config: DevsContext configuration.
            pipeline: Preprocessing pipeline to handle new tickets.
        """
        self._config = config
        self._pipeline = pipeline
        self._preprocessor_config = config.agents.preprocessor
        self._jira_config = config.sources.jira

        self._processed_tickets: set[str] = set()
        self._running = False
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for Jira API."""
        if self._client is None:
            auth = (self._jira_config.email, self._jira_config.api_token)
            self._client = httpx.AsyncClient(
                base_url=self._jira_config.base_url,
                auth=auth,
                headers={"Accept": "application/json"},
                timeout=30.0,
            )
        return self._client

    def _build_jql(self) -> str:
        """Build JQL query for finding ready tickets.

        Returns:
            JQL query string.
        """
        # Handle single project or list of projects
        projects = self._preprocessor_config.jira_project
        if isinstance(projects, list):
            project_clause = f"project IN ({', '.join(projects)})"
        else:
            project_clause = f'project = "{projects}"'

        # Escape status for JQL
        status = self._preprocessor_config.jira_status.replace('"', '\\"')

        # Look for tickets updated in the last hour (configurable polling)
        # This ensures we don't miss tickets between polls
        jql = f'{project_clause} AND status = "{status}" AND updated >= -1h ORDER BY updated DESC'

        return jql

    async def poll_once(self) -> list[str]:
        """Single poll - returns list of new task IDs ready for processing.

        Queries Jira for tickets in the target status and filters out
        already-processed tickets.

        Returns:
            List of new task IDs that need processing.
        """
        if not self._jira_config.enabled:
            logger.warning("Jira adapter not enabled")
            return []

        client = self._get_client()
        jql = self._build_jql()

        try:
            response = await client.get(
                f"{JIRA_API_BASE_PATH}/search",
                params={
                    "jql": jql,
                    "maxResults": 50,
                    "fields": "key",  # Only need the key
                },
            )
            response.raise_for_status()
            data = response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                "Jira API error during poll",
                extra={"status_code": e.response.status_code, "jql": jql},
            )
            return []
        except Exception as e:
            logger.error("Error polling Jira", extra={"error": str(e)})
            return []

        # Extract ticket IDs
        issues = data.get("issues", [])
        all_tickets = [issue["key"] for issue in issues]

        # Filter out already-processed tickets
        new_tickets = [t for t in all_tickets if t not in self._processed_tickets]

        if new_tickets:
            logger.info(
                "Found new tickets",
                extra={"count": len(new_tickets), "tickets": new_tickets},
            )

        return new_tickets

    async def process_ticket(self, task_id: str) -> bool:
        """Process a single ticket through the pipeline.

        Args:
            task_id: Jira ticket ID to process.

        Returns:
            True if processed successfully, False otherwise.
        """
        try:
            logger.info("Processing ticket", extra={"task_id": task_id})
            await self._pipeline.process(task_id)
            self._processed_tickets.add(task_id)
            logger.info("Ticket processed successfully", extra={"task_id": task_id})
            return True

        except Exception as e:
            logger.error(
                "Failed to process ticket",
                extra={"task_id": task_id, "error": str(e)},
            )
            return False

    async def run(self) -> None:
        """Run polling loop until stopped.

        Polls Jira every N minutes (configurable) and processes new tickets.
        Use stop() to signal the loop to exit.
        """
        self._running = True
        poll_interval = self._preprocessor_config.trigger.poll_interval_minutes * 60

        logger.info(
            "Starting Jira watcher",
            extra={
                "poll_interval_minutes": self._preprocessor_config.trigger.poll_interval_minutes,
                "jira_status": self._preprocessor_config.jira_status,
                "jira_project": self._preprocessor_config.jira_project,
            },
        )

        while self._running:
            try:
                # Poll for new tickets
                new_tickets = await self.poll_once()

                # Process each new ticket
                for task_id in new_tickets:
                    if not self._running:
                        break
                    await self.process_ticket(task_id)

            except Exception as e:
                logger.error("Error in polling loop", extra={"error": str(e)})

            # Wait for next poll interval
            if self._running:
                logger.debug(
                    "Waiting for next poll",
                    extra={"interval_seconds": poll_interval},
                )
                await asyncio.sleep(poll_interval)

        logger.info("Jira watcher stopped")

    async def run_once(self) -> int:
        """Single run: check for ready tickets, process them, exit.

        Useful for cron jobs or CI pipelines.

        Returns:
            Number of tickets processed.
        """
        logger.info("Running single poll cycle")

        new_tickets = await self.poll_once()
        processed_count = 0

        for task_id in new_tickets:
            if await self.process_ticket(task_id):
                processed_count += 1

        logger.info(
            "Single poll cycle complete",
            extra={"processed": processed_count, "total": len(new_tickets)},
        )

        return processed_count

    def stop(self) -> None:
        """Signal watcher to stop.

        The polling loop will exit after the current iteration completes.
        """
        logger.info("Stopping Jira watcher")
        self._running = False

    async def close(self) -> None:
        """Close HTTP client and clean up resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def get_processed_count(self) -> int:
        """Get number of tickets processed in this session.

        Returns:
            Number of unique tickets processed.
        """
        return len(self._processed_tickets)

    def clear_processed(self) -> None:
        """Clear the set of processed tickets.

        Use this to allow reprocessing of tickets in the next poll.
        """
        self._processed_tickets.clear()
        logger.debug("Cleared processed tickets set")
