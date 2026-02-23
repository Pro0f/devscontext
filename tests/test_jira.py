"""Tests for the Jira adapter."""

import pytest
from pytest_httpx import HTTPXMock

from devscontext.adapters.jira import JiraAdapter
from devscontext.config import JiraConfig


@pytest.fixture
def jira_config() -> JiraConfig:
    """Create a test Jira configuration."""
    return JiraConfig(
        base_url="https://test.atlassian.net",
        email="test@example.com",
        api_token="test-token",
        enabled=True,
    )


@pytest.fixture
def jira_adapter(jira_config: JiraConfig) -> JiraAdapter:
    """Create a test Jira adapter."""
    return JiraAdapter(jira_config)


# Sample Jira API responses
SAMPLE_TICKET_RESPONSE = {
    "key": "TEST-123",
    "fields": {
        "summary": "Test ticket summary",
        "description": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Test description"}],
                }
            ],
        },
        "status": {"name": "In Progress"},
        "priority": {"name": "High"},
        "assignee": {"displayName": "Test User", "emailAddress": "test@example.com"},
        "reporter": {"displayName": "Reporter User", "emailAddress": "reporter@example.com"},
        "labels": ["test", "example"],
        "issuetype": {"name": "Story"},
        "created": "2024-01-15T10:00:00.000Z",
        "updated": "2024-01-16T10:00:00.000Z",
    },
}

SAMPLE_COMMENTS_RESPONSE = {
    "comments": [
        {
            "id": "10001",
            "author": {"displayName": "Commenter", "emailAddress": "commenter@example.com"},
            "body": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "A test comment"}]}
                ],
            },
            "created": "2024-01-15T11:00:00.000Z",
        }
    ]
}

SAMPLE_LINKED_ISSUES_RESPONSE = {
    "key": "TEST-123",
    "fields": {
        "issuelinks": [
            {
                "type": {"name": "Blocks", "outward": "blocks", "inward": "is blocked by"},
                "outwardIssue": {
                    "key": "TEST-456",
                    "fields": {
                        "summary": "Linked issue",
                        "status": {"name": "Done"},
                    },
                },
            }
        ]
    },
}


class TestJiraAdapter:
    """Tests for JiraAdapter."""

    def test_name(self, jira_adapter: JiraAdapter) -> None:
        """Test adapter name."""
        assert jira_adapter.name == "jira"

    def test_source_type(self, jira_adapter: JiraAdapter) -> None:
        """Test adapter source type."""
        assert jira_adapter.source_type == "issue_tracker"

    async def test_fetch_context_returns_list(
        self, jira_adapter: JiraAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that fetch_context returns a list of ContextData."""
        # Mock all three API calls
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/TEST-123?fields=summary%2Cdescription%2Cstatus%2Cpriority%2Cassignee%2Creporter%2Clabels%2Cissuetype%2Ccreated%2Cupdated",
            json=SAMPLE_TICKET_RESPONSE,
        )
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/TEST-123/comment?maxResults=50&orderBy=-created",
            json=SAMPLE_COMMENTS_RESPONSE,
        )
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/TEST-123?fields=issuelinks",
            json=SAMPLE_LINKED_ISSUES_RESPONSE,
        )

        result = await jira_adapter.fetch_context("TEST-123")

        assert isinstance(result, list)
        assert len(result) > 0

    async def test_fetch_context_has_required_fields(
        self, jira_adapter: JiraAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that returned context has required fields."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/TEST-123?fields=summary%2Cdescription%2Cstatus%2Cpriority%2Cassignee%2Creporter%2Clabels%2Cissuetype%2Ccreated%2Cupdated",
            json=SAMPLE_TICKET_RESPONSE,
        )
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/TEST-123/comment?maxResults=50&orderBy=-created",
            json=SAMPLE_COMMENTS_RESPONSE,
        )
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/TEST-123?fields=issuelinks",
            json=SAMPLE_LINKED_ISSUES_RESPONSE,
        )

        result = await jira_adapter.fetch_context("TEST-123")
        context = result[0]

        assert context.source == "jira:TEST-123"
        assert context.source_type == "issue_tracker"
        assert "TEST-123" in context.title
        assert "Test ticket summary" in context.title
        assert context.content

    async def test_fetch_context_empty_on_404(
        self, jira_adapter: JiraAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test that fetch_context returns empty list on 404."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/NOTFOUND-999?fields=summary%2Cdescription%2Cstatus%2Cpriority%2Cassignee%2Creporter%2Clabels%2Cissuetype%2Ccreated%2Cupdated",
            status_code=404,
        )
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/NOTFOUND-999/comment?maxResults=50&orderBy=-created",
            status_code=404,
        )
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/NOTFOUND-999?fields=issuelinks",
            status_code=404,
        )

        result = await jira_adapter.fetch_context("NOTFOUND-999")

        assert isinstance(result, list)
        assert len(result) == 0

    async def test_health_check_with_config(
        self, jira_adapter: JiraAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test health check when configured."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            json={"displayName": "Test User"},
            status_code=200,
        )

        result = await jira_adapter.health_check()

        assert isinstance(result, bool)
        assert result is True

    async def test_health_check_fails_on_401(
        self, jira_adapter: JiraAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test health check fails on authentication error."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/myself",
            status_code=401,
        )

        result = await jira_adapter.health_check()

        assert result is False

    async def test_health_check_disabled(self) -> None:
        """Test health check when adapter is disabled."""
        config = JiraConfig(enabled=False)
        adapter = JiraAdapter(config)

        result = await adapter.health_check()

        assert result is True  # Disabled adapters are "healthy"

    async def test_get_ticket(
        self, jira_adapter: JiraAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test fetching a single ticket."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/TEST-123?fields=summary%2Cdescription%2Cstatus%2Cpriority%2Cassignee%2Creporter%2Clabels%2Cissuetype%2Ccreated%2Cupdated",
            json=SAMPLE_TICKET_RESPONSE,
        )

        ticket = await jira_adapter.get_ticket("TEST-123")

        assert ticket is not None
        assert ticket.key == "TEST-123"
        assert ticket.summary == "Test ticket summary"
        assert ticket.status == "In Progress"
        assert ticket.priority == "High"

    async def test_get_comments(
        self, jira_adapter: JiraAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test fetching comments."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/TEST-123/comment?maxResults=50&orderBy=-created",
            json=SAMPLE_COMMENTS_RESPONSE,
        )

        comments = await jira_adapter.get_comments("TEST-123")

        assert len(comments) == 1
        assert comments[0].id == "10001"
        assert comments[0].author.display_name == "Commenter"
        assert "test comment" in comments[0].body

    async def test_get_linked_issues(
        self, jira_adapter: JiraAdapter, httpx_mock: HTTPXMock
    ) -> None:
        """Test fetching linked issues."""
        httpx_mock.add_response(
            url="https://test.atlassian.net/rest/api/3/issue/TEST-123?fields=issuelinks",
            json=SAMPLE_LINKED_ISSUES_RESPONSE,
        )

        linked = await jira_adapter.get_linked_issues("TEST-123")

        assert len(linked) == 1
        assert linked[0].key == "TEST-456"
        assert linked[0].summary == "Linked issue"
        assert linked[0].status == "Done"
        assert linked[0].link_type == "blocks"
