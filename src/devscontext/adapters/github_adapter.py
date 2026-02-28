"""GitHub adapter for fetching PRs, issues, and recent changes.

This adapter provides context from GitHub repositories:
- PRs that mention the ticket ID
- PRs that touch the same files/service area
- Recent merged PRs for general awareness
- Related issues

Uses GitHub REST API v3 via httpx.

Example:
    config = GitHubConfig(
        token="ghp_xxx",
        repos=["org/repo-name"],
        recent_pr_days=14,
        max_prs=10,
        enabled=True,
    )
    adapter = GitHubAdapter(config)
    context = await adapter.fetch_task_context("PROJ-123", ticket)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar

import httpx

from devscontext.constants import DEFAULT_HTTP_TIMEOUT_SECONDS
from devscontext.logging import get_logger
from devscontext.models import (
    GitHubConfig,
    GitHubContext,
    GitHubIssue,
    GitHubPR,
    GitHubReviewComment,
)
from devscontext.plugins.base import Adapter, SearchResult, SourceContext

if TYPE_CHECKING:
    from devscontext.models import JiraTicket

logger = get_logger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubAdapter(Adapter):
    """GitHub adapter for fetching PRs, issues, and recent changes.

    Implements the Adapter interface for the plugin system.
    Uses GitHub REST API v3 to fetch:
    - PRs mentioning the ticket ID
    - PRs in the same service area (based on ticket labels/components)
    - Recent merged PRs
    - Related issues

    Class Attributes:
        name: Adapter identifier ("github").
        source_type: Category ("version_control").
        config_schema: Configuration model (GitHubConfig).
    """

    name: ClassVar[str] = "github"
    source_type: ClassVar[str] = "version_control"
    config_schema: ClassVar[type[GitHubConfig]] = GitHubConfig

    def __init__(self, config: GitHubConfig) -> None:
        """Initialize the GitHub adapter.

        Args:
            config: GitHub configuration with token, repos, etc.
        """
        self._config = config
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client with GitHub headers."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=GITHUB_API_BASE,
                headers={
                    "Authorization": f"Bearer {self._config.token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> bool:
        """Check if the GitHub token is valid.

        Returns:
            True if token is valid, False otherwise.
        """
        if not self._config.enabled:
            return True

        if not self._config.token:
            logger.warning("GitHub token not configured")
            return False

        try:
            client = self._get_client()
            response = await client.get("/user")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"GitHub health check failed: {e}")
            return False

    async def fetch_task_context(
        self,
        task_id: str,
        ticket: JiraTicket | None = None,
    ) -> SourceContext:
        """Fetch GitHub context for a task.

        Searches for:
        1. PRs mentioning the ticket ID
        2. PRs in the same service area (based on ticket components/labels)
        3. Recent merged PRs
        4. Issues mentioning the ticket ID

        Args:
            task_id: The task/ticket identifier (e.g., "PROJ-123").
            ticket: Optional Jira ticket for service area matching.

        Returns:
            SourceContext with GitHubContext data.
        """
        if not self._config.enabled:
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
            )

        if not self._config.repos:
            logger.warning("No GitHub repos configured")
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
                metadata={"error": "no_repos_configured"},
            )

        try:
            # Fetch PRs and issues in parallel for each repo
            related_prs: list[GitHubPR] = []
            recent_prs: list[GitHubPR] = []
            related_issues: list[GitHubIssue] = []

            for repo in self._config.repos:
                # Search PRs mentioning the ticket
                ticket_prs = await self._search_prs_by_ticket(repo, task_id)
                related_prs.extend(ticket_prs)

                # Search issues mentioning the ticket
                ticket_issues = await self._search_issues_by_ticket(repo, task_id)
                related_issues.extend(ticket_issues)

                # Get recent merged PRs
                recent = await self._get_recent_merged_prs(repo)
                recent_prs.extend(recent)

            # If we have ticket info, filter recent PRs to same service area
            if ticket and (ticket.components or ticket.labels):
                service_areas = self._extract_service_areas(ticket)
                recent_prs = self._filter_prs_by_service_area(recent_prs, service_areas)

            # Deduplicate and limit
            related_prs = self._deduplicate_prs(related_prs)[: self._config.max_prs]
            recent_prs = self._deduplicate_prs(recent_prs)[: self._config.max_prs]

            # Remove from recent_prs any that are already in related_prs
            related_numbers = {pr.number for pr in related_prs}
            recent_prs = [pr for pr in recent_prs if pr.number not in related_numbers]

            github_context = GitHubContext(
                related_prs=related_prs,
                recent_prs=recent_prs[:5],  # Limit recent to 5
                related_issues=related_issues,
            )

            # Format raw text for synthesis
            raw_text = self._format_context(github_context)

            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=github_context,
                raw_text=raw_text,
                metadata={
                    "task_id": task_id,
                    "related_pr_count": len(related_prs),
                    "recent_pr_count": len(recent_prs),
                    "issue_count": len(related_issues),
                },
            )

        except Exception as e:
            logger.exception(f"GitHub fetch failed for {task_id}: {e}")
            return SourceContext(
                source_name=self.name,
                source_type=self.source_type,
                data=None,
                raw_text="",
                metadata={"task_id": task_id, "error": str(e)},
            )

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search GitHub for PRs and issues matching a query.

        Args:
            query: Search query string.
            max_results: Maximum results to return.

        Returns:
            List of SearchResult objects.
        """
        if not self._config.enabled or not self._config.repos:
            return []

        results: list[SearchResult] = []

        try:
            for repo in self._config.repos:
                # Search PRs
                prs = await self._search_prs(repo, query, max_results=max_results // 2)
                for pr in prs:
                    results.append(
                        SearchResult(
                            source_name=self.name,
                            source_type=self.source_type,
                            title=f"PR #{pr.number}: {pr.title}",
                            excerpt=pr.body[:200] if pr.body else "",
                            url=pr.url,
                            metadata={"type": "pr", "number": pr.number, "state": pr.state},
                        )
                    )

                # Search issues
                issues = await self._search_issues(repo, query, max_results=max_results // 2)
                for issue in issues:
                    results.append(
                        SearchResult(
                            source_name=self.name,
                            source_type=self.source_type,
                            title=f"Issue #{issue.number}: {issue.title}",
                            excerpt=issue.body[:200] if issue.body else "",
                            url=issue.url,
                            metadata={
                                "type": "issue",
                                "number": issue.number,
                                "state": issue.state,
                            },
                        )
                    )

                if len(results) >= max_results:
                    break

        except Exception as e:
            logger.warning(f"GitHub search failed: {e}")

        return results[:max_results]

    async def _search_prs_by_ticket(self, repo: str, task_id: str) -> list[GitHubPR]:
        """Search for PRs mentioning the ticket ID.

        Args:
            repo: Repository in "owner/repo" format.
            task_id: Ticket ID to search for.

        Returns:
            List of matching PRs with details.
        """
        query = f"{task_id} repo:{repo} type:pr"
        return await self._search_prs(repo, query)

    async def _search_prs(
        self,
        repo: str,
        query: str,
        max_results: int = 10,
    ) -> list[GitHubPR]:
        """Search for PRs using GitHub search API.

        Args:
            repo: Repository in "owner/repo" format.
            query: Search query (will add repo filter if not present).
            max_results: Maximum results to return.

        Returns:
            List of matching PRs with details.
        """
        client = self._get_client()

        # Ensure repo is in query if not already
        if f"repo:{repo}" not in query:
            query = f"{query} repo:{repo}"

        # Add type:pr if not already there
        if "type:pr" not in query:
            query = f"{query} type:pr"

        try:
            response = await client.get(
                "/search/issues",
                params={"q": query, "per_page": max_results, "sort": "updated"},
            )
            response.raise_for_status()
            data = response.json()

            prs: list[GitHubPR] = []
            for item in data.get("items", []):
                pr = await self._fetch_pr_details(repo, item["number"])
                if pr:
                    prs.append(pr)

            return prs

        except Exception as e:
            logger.warning(f"GitHub PR search failed: {e}")
            return []

    async def _fetch_pr_details(self, repo: str, pr_number: int) -> GitHubPR | None:
        """Fetch full PR details including files and comments.

        Args:
            repo: Repository in "owner/repo" format.
            pr_number: PR number.

        Returns:
            GitHubPR with full details, or None on error.
        """
        client = self._get_client()

        try:
            # Fetch PR details
            pr_response = await client.get(f"/repos/{repo}/pulls/{pr_number}")
            pr_response.raise_for_status()
            pr_data = pr_response.json()

            # Fetch changed files
            files_response = await client.get(f"/repos/{repo}/pulls/{pr_number}/files")
            files_response.raise_for_status()
            files_data = files_response.json()
            changed_files = [f["filename"] for f in files_data]

            # Fetch review comments (limit to 10)
            comments_response = await client.get(
                f"/repos/{repo}/pulls/{pr_number}/comments",
                params={"per_page": 10},
            )
            comments_response.raise_for_status()
            comments_data = comments_response.json()

            review_comments = [
                GitHubReviewComment(
                    author=c["user"]["login"],
                    body=c["body"],
                    path=c.get("path"),
                    created_at=datetime.fromisoformat(c["created_at"].replace("Z", "+00:00")),
                )
                for c in comments_data
            ]

            # Determine state
            state = pr_data["state"]
            merged_at = None
            if pr_data.get("merged_at"):
                state = "merged"
                merged_at = datetime.fromisoformat(
                    pr_data["merged_at"].replace("Z", "+00:00")
                )

            return GitHubPR(
                number=pr_data["number"],
                title=pr_data["title"],
                author=pr_data["user"]["login"],
                state=state,
                url=pr_data["html_url"],
                created_at=datetime.fromisoformat(
                    pr_data["created_at"].replace("Z", "+00:00")
                ),
                merged_at=merged_at,
                changed_files=changed_files,
                review_comments=review_comments,
                body=pr_data.get("body"),
            )

        except Exception as e:
            logger.warning(f"Failed to fetch PR #{pr_number} details: {e}")
            return None

    async def _get_recent_merged_prs(self, repo: str) -> list[GitHubPR]:
        """Get recently merged PRs.

        Args:
            repo: Repository in "owner/repo" format.

        Returns:
            List of recent merged PRs.
        """
        client = self._get_client()

        try:
            # Calculate date range
            since_date = datetime.now(UTC) - timedelta(days=self._config.recent_pr_days)
            since_str = since_date.strftime("%Y-%m-%d")

            # Search for merged PRs
            query = f"repo:{repo} type:pr is:merged merged:>={since_str}"
            response = await client.get(
                "/search/issues",
                params={"q": query, "per_page": self._config.max_prs, "sort": "updated"},
            )
            response.raise_for_status()
            data = response.json()

            prs: list[GitHubPR] = []
            for item in data.get("items", [])[:self._config.max_prs]:
                pr = await self._fetch_pr_details(repo, item["number"])
                if pr:
                    prs.append(pr)

            return prs

        except Exception as e:
            logger.warning(f"Failed to fetch recent PRs: {e}")
            return []

    async def _search_issues_by_ticket(self, repo: str, task_id: str) -> list[GitHubIssue]:
        """Search for issues mentioning the ticket ID.

        Args:
            repo: Repository in "owner/repo" format.
            task_id: Ticket ID to search for.

        Returns:
            List of matching issues.
        """
        query = f"{task_id} repo:{repo} type:issue"
        return await self._search_issues(repo, query)

    async def _search_issues(
        self,
        repo: str,
        query: str,
        max_results: int = 10,
    ) -> list[GitHubIssue]:
        """Search for issues using GitHub search API.

        Args:
            repo: Repository in "owner/repo" format.
            query: Search query.
            max_results: Maximum results to return.

        Returns:
            List of matching issues.
        """
        client = self._get_client()

        # Ensure repo is in query if not already
        if f"repo:{repo}" not in query:
            query = f"{query} repo:{repo}"

        # Add type:issue if not already there
        if "type:issue" not in query:
            query = f"{query} type:issue"

        try:
            response = await client.get(
                "/search/issues",
                params={"q": query, "per_page": max_results},
            )
            response.raise_for_status()
            data = response.json()

            issues: list[GitHubIssue] = []
            for item in data.get("items", []):
                # Skip PRs (they also appear in issue search)
                if "pull_request" in item:
                    continue

                issues.append(
                    GitHubIssue(
                        number=item["number"],
                        title=item["title"],
                        author=item["user"]["login"],
                        state=item["state"],
                        url=item["html_url"],
                        created_at=datetime.fromisoformat(
                            item["created_at"].replace("Z", "+00:00")
                        ),
                        labels=[label["name"] for label in item.get("labels", [])],
                        body=item.get("body"),
                    )
                )

            return issues

        except Exception as e:
            logger.warning(f"GitHub issue search failed: {e}")
            return []

    def _extract_service_areas(self, ticket: JiraTicket) -> list[str]:
        """Extract service area paths from ticket components/labels.

        Maps component/label names to likely file paths.
        E.g., "payments-service" -> ["payments", "payment"]

        Args:
            ticket: Jira ticket with components and labels.

        Returns:
            List of path fragments to match against.
        """
        areas: list[str] = []

        for component in ticket.components:
            # Convert component name to path-like fragments
            # "payments-service" -> ["payments", "payment"]
            clean = component.lower().replace("-service", "").replace("_service", "")
            areas.append(clean)
            # Also add singular/plural variants
            if clean.endswith("s"):
                areas.append(clean[:-1])
            else:
                areas.append(clean + "s")

        for label in ticket.labels:
            # Only use labels that look like service/module names
            if not label.startswith(("P", "bug", "feature", "enhancement")):
                clean = label.lower().replace("-", "/")
                areas.append(clean)

        return list(set(areas))

    def _filter_prs_by_service_area(
        self,
        prs: list[GitHubPR],
        service_areas: list[str],
    ) -> list[GitHubPR]:
        """Filter PRs to those touching files in the service area.

        Args:
            prs: List of PRs to filter.
            service_areas: Path fragments to match against.

        Returns:
            PRs that touch files in the service area.
        """
        if not service_areas:
            return prs

        filtered: list[GitHubPR] = []
        for pr in prs:
            for file_path in pr.changed_files:
                file_lower = file_path.lower()
                if any(area in file_lower for area in service_areas):
                    filtered.append(pr)
                    break

        return filtered

    def _deduplicate_prs(self, prs: list[GitHubPR]) -> list[GitHubPR]:
        """Remove duplicate PRs (by number).

        Args:
            prs: List of PRs.

        Returns:
            Deduplicated list.
        """
        seen: set[int] = set()
        result: list[GitHubPR] = []
        for pr in prs:
            if pr.number not in seen:
                seen.add(pr.number)
                result.append(pr)
        return result

    def _format_context(self, ctx: GitHubContext) -> str:
        """Format GitHub context as raw text for synthesis.

        Args:
            ctx: GitHub context with PRs and issues.

        Returns:
            Formatted text string.
        """
        if not ctx.related_prs and not ctx.recent_prs and not ctx.related_issues:
            return ""

        parts: list[str] = ["## GITHUB CONTEXT"]
        parts.append("*Recent PRs and changes in the same service area.*\n")

        # Related PRs (mention ticket or same files)
        if ctx.related_prs:
            parts.append("### Related PRs")
            for pr in ctx.related_prs:
                status = "merged" if pr.merged_at else pr.state
                parts.append(f"\n**PR #{pr.number}**: {pr.title} ({status})")
                parts.append(f"Author: @{pr.author}")
                if pr.changed_files:
                    files_str = ", ".join(pr.changed_files[:5])
                    if len(pr.changed_files) > 5:
                        files_str += f" (+{len(pr.changed_files) - 5} more)"
                    parts.append(f"Changed: {files_str}")
                for comment in pr.review_comments[:3]:
                    body = comment.body[:200]
                    if len(comment.body) > 200:
                        body += "..."
                    parts.append(f"Review (@{comment.author}): {body}")

        # Recent PRs in same area
        if ctx.recent_prs:
            parts.append("\n### Recent PRs in Service Area")
            for pr in ctx.recent_prs[:5]:
                merge_date = pr.merged_at or pr.created_at
                days_ago = (datetime.now(UTC) - merge_date).days
                parts.append(f"- PR #{pr.number}: {pr.title} ({days_ago}d ago)")

        # Related issues
        if ctx.related_issues:
            parts.append("\n### Related Issues")
            for issue in ctx.related_issues:
                labels_str = f" [{', '.join(issue.labels)}]" if issue.labels else ""
                parts.append(f"- #{issue.number}: {issue.title} ({issue.state}){labels_str}")

        return "\n".join(parts)
