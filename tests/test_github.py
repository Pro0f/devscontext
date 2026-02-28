"""Tests for the GitHub adapter."""

from datetime import UTC, datetime
from urllib.parse import unquote

import httpx
import pytest
from pytest_httpx import HTTPXMock

from devscontext.adapters.github_adapter import GitHubAdapter
from devscontext.models import GitHubConfig, JiraTicket


@pytest.fixture
def github_config() -> GitHubConfig:
    """Create a test GitHub configuration."""
    return GitHubConfig(
        token="test-token",
        repos=["org/test-repo"],
        recent_pr_days=14,
        max_prs=10,
        enabled=True,
    )


@pytest.fixture
def github_adapter(github_config: GitHubConfig) -> GitHubAdapter:
    """Create a test GitHub adapter."""
    return GitHubAdapter(github_config)


@pytest.fixture
def sample_ticket() -> JiraTicket:
    """Create a sample Jira ticket for service area matching."""
    return JiraTicket(
        ticket_id="PROJ-123",
        title="Add retry logic to payment webhook handler",
        status="In Progress",
        assignee="Alex Chen",
        labels=["payments", "webhooks"],
        components=["payments-service"],
        created=datetime(2024, 3, 14, 9, 0, 0, tzinfo=UTC),
        updated=datetime(2024, 3, 18, 14, 30, 0, tzinfo=UTC),
    )


# Sample GitHub API responses
SAMPLE_SEARCH_PRS_RESPONSE = {
    "total_count": 1,
    "items": [
        {
            "number": 234,
            "title": "Refactor webhook handler to use Result pattern",
            "user": {"login": "developer"},
            "state": "closed",
            "html_url": "https://github.com/org/test-repo/pull/234",
            "created_at": "2024-03-15T10:00:00Z",
            "pull_request": {"merged_at": "2024-03-16T14:00:00Z"},
            "body": "This PR implements the Result pattern for webhook handlers.",
        }
    ],
}

SAMPLE_PR_DETAILS_RESPONSE = {
    "number": 234,
    "title": "Refactor webhook handler to use Result pattern",
    "user": {"login": "developer"},
    "state": "closed",
    "html_url": "https://github.com/org/test-repo/pull/234",
    "created_at": "2024-03-15T10:00:00Z",
    "merged_at": "2024-03-16T14:00:00Z",
    "body": "This PR implements the Result pattern for webhook handlers.",
}

SAMPLE_PR_FILES_RESPONSE = [
    {"filename": "src/webhooks/handler.ts"},
    {"filename": "src/webhooks/router.ts"},
    {"filename": "tests/webhooks/handler.test.ts"},
]

SAMPLE_PR_COMMENTS_RESPONSE = [
    {
        "user": {"login": "reviewer"},
        "body": "Make sure to update the integration tests when changing the handler",
        "path": "src/webhooks/handler.ts",
        "created_at": "2024-03-16T10:00:00Z",
    }
]

SAMPLE_SEARCH_ISSUES_RESPONSE = {
    "total_count": 1,
    "items": [
        {
            "number": 100,
            "title": "Webhook delivery failures not being retried",
            "user": {"login": "reporter"},
            "state": "open",
            "html_url": "https://github.com/org/test-repo/issues/100",
            "created_at": "2024-03-10T10:00:00Z",
            "labels": [{"name": "bug"}, {"name": "payments"}],
            "body": "Related to PROJ-123",
        }
    ],
}


class TestGitHubAdapter:
    """Tests for GitHubAdapter."""

    def test_name(self, github_adapter: GitHubAdapter) -> None:
        """Test adapter name."""
        assert github_adapter.name == "github"

    def test_source_type(self, github_adapter: GitHubAdapter) -> None:
        """Test adapter source type."""
        assert github_adapter.source_type == "version_control"

    async def test_health_check_success(
        self, github_adapter: GitHubAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test health check with valid token."""
        httpx_mock.add_response(
            url="https://api.github.com/user",
            json={"login": "testuser"},
            status_code=200,
        )

        result = await github_adapter.health_check()
        assert result is True

    async def test_health_check_invalid_token(
        self, github_adapter: GitHubAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test health check with invalid token."""
        httpx_mock.add_response(
            url="https://api.github.com/user",
            status_code=401,
        )

        result = await github_adapter.health_check()
        assert result is False

    async def test_health_check_disabled(self) -> None:
        """Test health check when adapter is disabled."""
        config = GitHubConfig(enabled=False)
        adapter = GitHubAdapter(config)

        result = await adapter.health_check()
        assert result is True

    async def test_health_check_no_token(self) -> None:
        """Test health check with no token configured."""
        config = GitHubConfig(token="", enabled=True)
        adapter = GitHubAdapter(config)

        result = await adapter.health_check()
        assert result is False

    async def test_fetch_task_context_disabled(self) -> None:
        """Test fetch_task_context when adapter is disabled."""
        config = GitHubConfig(enabled=False)
        adapter = GitHubAdapter(config)

        result = await adapter.fetch_task_context("PROJ-123")

        assert result.source_name == "github"
        assert result.data is None

    async def test_fetch_task_context_no_repos(self) -> None:
        """Test fetch_task_context with no repos configured."""
        config = GitHubConfig(token="test", repos=[], enabled=True)
        adapter = GitHubAdapter(config)

        result = await adapter.fetch_task_context("PROJ-123")

        assert result.source_name == "github"
        assert result.data is None
        assert result.metadata.get("error") == "no_repos_configured"

    async def test_fetch_task_context_finds_related_prs(
        self, github_adapter: GitHubAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test fetching context finds PRs mentioning the ticket."""

        def github_api_callback(request: httpx.Request) -> httpx.Response:
            url = unquote(str(request.url))

            # Search for PRs mentioning ticket
            if "/search/issues" in url and "PROJ-123" in url and "type:pr" in url:
                return httpx.Response(200, json=SAMPLE_SEARCH_PRS_RESPONSE)

            # Search for issues mentioning ticket
            if "/search/issues" in url and "PROJ-123" in url and "type:issue" in url:
                return httpx.Response(200, json=SAMPLE_SEARCH_ISSUES_RESPONSE)

            # Search for recent merged PRs
            if "/search/issues" in url and "is:merged" in url:
                return httpx.Response(200, json={"total_count": 0, "items": []})

            # PR details
            if "/repos/org/test-repo/pulls/234" in url and "/files" not in url and "/comments" not in url:
                return httpx.Response(200, json=SAMPLE_PR_DETAILS_RESPONSE)

            # PR files
            if "/repos/org/test-repo/pulls/234/files" in url:
                return httpx.Response(200, json=SAMPLE_PR_FILES_RESPONSE)

            # PR comments
            if "/repos/org/test-repo/pulls/234/comments" in url:
                return httpx.Response(200, json=SAMPLE_PR_COMMENTS_RESPONSE)

            # Fallback - return empty for any other search
            if "/search/issues" in url:
                return httpx.Response(200, json={"total_count": 0, "items": []})

            return httpx.Response(404)

        httpx_mock.add_callback(callback=github_api_callback, is_reusable=True)

        result = await github_adapter.fetch_task_context("PROJ-123")

        assert result.source_name == "github"
        assert result.data is not None
        assert len(result.data.related_prs) == 1
        assert result.data.related_prs[0].number == 234
        assert result.data.related_prs[0].title == "Refactor webhook handler to use Result pattern"
        assert "src/webhooks/handler.ts" in result.data.related_prs[0].changed_files

    async def test_fetch_task_context_finds_related_issues(
        self, github_adapter: GitHubAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test fetching context finds issues mentioning the ticket."""

        def github_api_callback(request: httpx.Request) -> httpx.Response:
            url = unquote(str(request.url))

            # Search for PRs (empty)
            if "/search/issues" in url and "PROJ-123" in url and "type:pr" in url:
                return httpx.Response(200, json={"total_count": 0, "items": []})

            # Search for issues
            if "/search/issues" in url and "PROJ-123" in url and "type:issue" in url:
                return httpx.Response(200, json=SAMPLE_SEARCH_ISSUES_RESPONSE)

            # Search for recent merged PRs
            if "/search/issues" in url and "is:merged" in url:
                return httpx.Response(200, json={"total_count": 0, "items": []})

            # Fallback - return empty for any other search
            if "/search/issues" in url:
                return httpx.Response(200, json={"total_count": 0, "items": []})

            return httpx.Response(404)

        httpx_mock.add_callback(callback=github_api_callback, is_reusable=True)

        result = await github_adapter.fetch_task_context("PROJ-123")

        assert result.data is not None
        assert len(result.data.related_issues) == 1
        assert result.data.related_issues[0].number == 100
        assert result.data.related_issues[0].title == "Webhook delivery failures not being retried"
        assert "bug" in result.data.related_issues[0].labels

    async def test_fetch_task_context_with_service_area_filter(
        self, github_adapter: GitHubAdapter, httpx_mock: HTTPXMock, sample_ticket: JiraTicket
    ) -> None:
        """Test that recent PRs are filtered by service area from ticket."""
        recent_prs = {
            "total_count": 2,
            "items": [
                {
                    "number": 300,
                    "title": "Update payments service",
                    "user": {"login": "dev1"},
                    "state": "closed",
                    "html_url": "https://github.com/org/test-repo/pull/300",
                    "created_at": "2024-03-15T10:00:00Z",
                    "pull_request": {"merged_at": "2024-03-16T10:00:00Z"},
                },
                {
                    "number": 301,
                    "title": "Update unrelated service",
                    "user": {"login": "dev2"},
                    "state": "closed",
                    "html_url": "https://github.com/org/test-repo/pull/301",
                    "created_at": "2024-03-15T10:00:00Z",
                    "pull_request": {"merged_at": "2024-03-16T10:00:00Z"},
                },
            ],
        }

        def github_api_callback(request: httpx.Request) -> httpx.Response:
            url = unquote(str(request.url))

            # Search for PRs mentioning ticket (empty)
            if "/search/issues" in url and "PROJ-123" in url and "type:pr" in url:
                return httpx.Response(200, json={"total_count": 0, "items": []})

            # Search for issues mentioning ticket (empty)
            if "/search/issues" in url and "PROJ-123" in url and "type:issue" in url:
                return httpx.Response(200, json={"total_count": 0, "items": []})

            # Search for recent merged PRs
            if "/search/issues" in url and "is:merged" in url:
                return httpx.Response(200, json=recent_prs)

            # PR 300 details (payments)
            if "/repos/org/test-repo/pulls/300" in url and "/files" not in url and "/comments" not in url:
                return httpx.Response(200, json={
                    "number": 300,
                    "title": "Update payments service",
                    "user": {"login": "dev1"},
                    "state": "closed",
                    "html_url": "https://github.com/org/test-repo/pull/300",
                    "created_at": "2024-03-15T10:00:00Z",
                    "merged_at": "2024-03-16T10:00:00Z",
                })

            if "/repos/org/test-repo/pulls/300/files" in url:
                return httpx.Response(200, json=[{"filename": "src/payments/processor.ts"}])

            if "/repos/org/test-repo/pulls/300/comments" in url:
                return httpx.Response(200, json=[])

            # PR 301 details (unrelated)
            if "/repos/org/test-repo/pulls/301" in url and "/files" not in url and "/comments" not in url:
                return httpx.Response(200, json={
                    "number": 301,
                    "title": "Update unrelated service",
                    "user": {"login": "dev2"},
                    "state": "closed",
                    "html_url": "https://github.com/org/test-repo/pull/301",
                    "created_at": "2024-03-15T10:00:00Z",
                    "merged_at": "2024-03-16T10:00:00Z",
                })

            if "/repos/org/test-repo/pulls/301/files" in url:
                return httpx.Response(200, json=[{"filename": "src/auth/login.ts"}])

            if "/repos/org/test-repo/pulls/301/comments" in url:
                return httpx.Response(200, json=[])

            # Fallback - return empty for any other search
            if "/search/issues" in url:
                return httpx.Response(200, json={"total_count": 0, "items": []})

            return httpx.Response(404)

        httpx_mock.add_callback(callback=github_api_callback, is_reusable=True)

        result = await github_adapter.fetch_task_context("PROJ-123", ticket=sample_ticket)

        assert result.data is not None
        # Only PR 300 should be in recent_prs because it matches "payments" service area
        assert len(result.data.recent_prs) == 1
        assert result.data.recent_prs[0].number == 300

    async def test_search(
        self, github_adapter: GitHubAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test freeform search."""

        def github_api_callback(request: httpx.Request) -> httpx.Response:
            url = unquote(str(request.url))

            # PR search
            if "/search/issues" in url and "webhook" in url and "type:pr" in url:
                return httpx.Response(200, json=SAMPLE_SEARCH_PRS_RESPONSE)

            # Issue search
            if "/search/issues" in url and "webhook" in url and "type:issue" in url:
                return httpx.Response(200, json=SAMPLE_SEARCH_ISSUES_RESPONSE)

            # PR details
            if "/repos/org/test-repo/pulls/234" in url and "/files" not in url and "/comments" not in url:
                return httpx.Response(200, json=SAMPLE_PR_DETAILS_RESPONSE)

            # PR files
            if "/repos/org/test-repo/pulls/234/files" in url:
                return httpx.Response(200, json=SAMPLE_PR_FILES_RESPONSE)

            # PR comments
            if "/repos/org/test-repo/pulls/234/comments" in url:
                return httpx.Response(200, json=SAMPLE_PR_COMMENTS_RESPONSE)

            return httpx.Response(404)

        httpx_mock.add_callback(callback=github_api_callback, is_reusable=True)

        results = await github_adapter.search("webhook", max_results=10)

        assert len(results) >= 1
        # First result should be the PR
        pr_results = [r for r in results if r.metadata.get("type") == "pr"]
        assert len(pr_results) == 1
        assert "PR #234" in pr_results[0].title

    async def test_search_disabled(self) -> None:
        """Test search when adapter is disabled."""
        config = GitHubConfig(enabled=False)
        adapter = GitHubAdapter(config)

        results = await adapter.search("webhook")

        assert results == []

    async def test_format_context(self, github_adapter: GitHubAdapter) -> None:
        """Test that context is formatted correctly."""
        from devscontext.models import GitHubContext, GitHubIssue, GitHubPR

        ctx = GitHubContext(
            related_prs=[
                GitHubPR(
                    number=234,
                    title="Refactor webhook handler",
                    author="developer",
                    state="merged",
                    url="https://github.com/org/repo/pull/234",
                    created_at=datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC),
                    merged_at=datetime(2024, 3, 16, 14, 0, 0, tzinfo=UTC),
                    changed_files=["src/webhooks/handler.ts"],
                )
            ],
            recent_prs=[],
            related_issues=[
                GitHubIssue(
                    number=100,
                    title="Webhook failures",
                    author="reporter",
                    state="open",
                    url="https://github.com/org/repo/issues/100",
                    created_at=datetime(2024, 3, 10, 10, 0, 0, tzinfo=UTC),
                    labels=["bug"],
                )
            ],
        )

        formatted = github_adapter._format_context(ctx)

        assert "GITHUB CONTEXT" in formatted
        assert "PR #234" in formatted
        assert "Refactor webhook handler" in formatted
        assert "src/webhooks/handler.ts" in formatted
        assert "#100" in formatted
        assert "Webhook failures" in formatted

    def test_extract_service_areas(
        self, github_adapter: GitHubAdapter, sample_ticket: JiraTicket
    ) -> None:
        """Test service area extraction from ticket."""
        areas = github_adapter._extract_service_areas(sample_ticket)

        # Should include "payments" from payments-service component
        assert "payments" in areas
        # Should include "payment" (singular)
        assert "payment" in areas

    def test_filter_prs_by_service_area(self, github_adapter: GitHubAdapter) -> None:
        """Test filtering PRs by service area."""
        from devscontext.models import GitHubPR

        prs = [
            GitHubPR(
                number=1,
                title="Update payments",
                author="dev",
                state="merged",
                url="https://github.com/org/repo/pull/1",
                created_at=datetime.now(UTC),
                changed_files=["src/payments/handler.ts"],
            ),
            GitHubPR(
                number=2,
                title="Update auth",
                author="dev",
                state="merged",
                url="https://github.com/org/repo/pull/2",
                created_at=datetime.now(UTC),
                changed_files=["src/auth/login.ts"],
            ),
        ]

        filtered = github_adapter._filter_prs_by_service_area(prs, ["payments"])

        assert len(filtered) == 1
        assert filtered[0].number == 1

    def test_deduplicate_prs(self, github_adapter: GitHubAdapter) -> None:
        """Test PR deduplication."""
        from devscontext.models import GitHubPR

        prs = [
            GitHubPR(
                number=1,
                title="PR 1",
                author="dev",
                state="merged",
                url="https://github.com/org/repo/pull/1",
                created_at=datetime.now(UTC),
            ),
            GitHubPR(
                number=1,
                title="PR 1 duplicate",
                author="dev",
                state="merged",
                url="https://github.com/org/repo/pull/1",
                created_at=datetime.now(UTC),
            ),
            GitHubPR(
                number=2,
                title="PR 2",
                author="dev",
                state="merged",
                url="https://github.com/org/repo/pull/2",
                created_at=datetime.now(UTC),
            ),
        ]

        deduped = github_adapter._deduplicate_prs(prs)

        assert len(deduped) == 2
        assert deduped[0].number == 1
        assert deduped[1].number == 2
