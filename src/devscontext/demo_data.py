"""Demo data for showcasing DevsContext without real API connections.

This module provides realistic sample data for the PROJ-123 ticket
(payment webhook retry logic) used in demo mode. All data is designed
to match the example output shown in the README.

Usage:
    from devscontext.demo_data import (
        get_demo_source_contexts,
        get_demo_synthesis,
        DEMO_TASK_ID,
    )

    # Get source contexts for synthesis
    contexts = get_demo_source_contexts()

    # Get pre-baked synthesis output
    synthesis = get_demo_synthesis()
"""

from __future__ import annotations

from datetime import UTC, datetime

from devscontext.models import (
    DocsContext,
    DocSection,
    JiraComment,
    JiraContext,
    JiraTicket,
    LinkedIssue,
    MeetingContext,
    MeetingExcerpt,
    SlackContext,
    SlackMessage,
    SlackThread,
)
from devscontext.plugins.base import SourceContext

# Demo ticket ID
DEMO_TASK_ID = "PROJ-123"

# =============================================================================
# JIRA DEMO DATA
# =============================================================================

DEMO_JIRA_TICKET = JiraTicket(
    ticket_id="PROJ-123",
    title="Add retry logic to payment webhook handler",
    description="""Implement exponential backoff for failed webhook deliveries.

## Background
Our payment webhooks currently fail silently when the receiving endpoint is down.
We need to add retry logic with exponential backoff to ensure eventual delivery.

## Requirements
1. Implement exponential backoff for failed webhook deliveries
2. Max 5 retry attempts over 24 hours
3. Dead-letter queue for permanently failed webhooks
4. Metrics for retry success/failure rates

## Technical Notes
- Use SQS visibility timeout for retry scheduling (decided in sprint planning)
- Follow the existing webhook processing pattern in WebhookWorker
- Add appropriate logging and metrics
""",
    status="In Progress",
    assignee="Alex Chen",
    labels=["payments", "webhooks", "reliability", "P1"],
    components=["payments-service", "webhooks"],
    acceptance_criteria="""- [ ] Webhooks retry with exponential backoff (1min, 5min, 30min, 2hr, 12hr)
- [ ] Failed webhooks move to DLQ after 5 attempts
- [ ] Dashboard shows retry metrics
- [ ] Unit tests cover retry logic
- [ ] Integration test verifies DLQ flow""",
    story_points=5.0,
    sprint="Sprint 23 - Payments Reliability",
    created=datetime(2024, 3, 14, 9, 0, 0, tzinfo=UTC),
    updated=datetime(2024, 3, 18, 14, 30, 0, tzinfo=UTC),
)

DEMO_JIRA_COMMENTS = [
    JiraComment(
        author="Sarah Kim",
        body="""For the retry scheduling, let's use SQS visibility timeout instead of a separate cron job.

Key points from our discussion:
- SQS handles timing natively - no additional infrastructure
- Visibility timeout can be set per-message
- Failed messages automatically become visible again
- Much simpler than managing a separate retry scheduler

I'll add this to the ADR once we confirm the approach works.""",
        created=datetime(2024, 3, 15, 11, 30, 0, tzinfo=UTC),
    ),
    JiraComment(
        author="Mike Johnson",
        body="""Talked to Stripe about their rate limits and recommended retry patterns.

Their guidance:
- First retry: 1 minute (handles brief network blips)
- Second retry: 5 minutes
- Third retry: 30 minutes
- Fourth retry: 2 hours
- Fifth retry: 12 hours (catch overnight issues)

This aligns with their rate limits and gives us 5 attempts over ~15 hours.

Also, they recommend using idempotency keys for any retry to prevent duplicate charges.""",
        created=datetime(2024, 3, 16, 9, 15, 0, tzinfo=UTC),
    ),
    JiraComment(
        author="Alex Chen",
        body="""Thanks for the context! I'll start implementation today.

Plan:
1. Add retry config to WebhookWorker
2. Implement calculateBackoff() helper
3. Add DLQ routing after max retries
4. Add CloudWatch metrics

Will push a draft PR by EOD for review.""",
        created=datetime(2024, 3, 18, 10, 0, 0, tzinfo=UTC),
    ),
]

DEMO_LINKED_ISSUES = [
    LinkedIssue(
        ticket_id="PROJ-456",
        title="Payment webhook initial implementation",
        status="Done",
        link_type="relates to",
    ),
    LinkedIssue(
        ticket_id="PROJ-789",
        title="Add webhook monitoring dashboard",
        status="In Progress",
        link_type="is blocked by",
    ),
    LinkedIssue(
        ticket_id="PROJ-100",
        title="Set up webhook DLQ infrastructure",
        status="Done",
        link_type="depends on",
    ),
]

DEMO_JIRA_CONTEXT = JiraContext(
    ticket=DEMO_JIRA_TICKET,
    comments=DEMO_JIRA_COMMENTS,
    linked_issues=DEMO_LINKED_ISSUES,
)

# =============================================================================
# MEETING DEMO DATA
# =============================================================================

DEMO_MEETINGS = [
    MeetingExcerpt(
        meeting_title="Sprint 23 Planning - Payments Team",
        meeting_date=datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC),
        participants=["Sarah Kim", "Alex Chen", "Mike Johnson", "David Lee"],
        excerpt="""**David Lee (PM):** Let's discuss PROJ-123 - the webhook retry logic. Alex, you're taking this one?

**Alex Chen:** Yes, I've looked at the requirements. We need to decide on the retry approach first.

**Sarah Kim:** I've been thinking about this. We could use a cron job that checks for failed webhooks, or we could use SQS visibility timeout.

**Alex Chen:** What's the difference in practice?

**Sarah Kim:** With SQS visibility timeout, when a message fails, we set a longer timeout before it becomes visible again. The queue handles the timing automatically. With cron, we'd need to manage retry timestamps ourselves and poll regularly.

**David Lee:** Which is simpler to operate?

**Sarah Kim:** Definitely SQS. We're already using it for webhooks, so no new infrastructure. The timeout is set per-message, so each webhook can have its own retry schedule.

**Mike Johnson:** I like the SQS approach. Less moving parts.

**David Lee:** Let's go with that then. Sarah, can you document this decision?

**Sarah Kim:** I'll add it to the ADRs.""",
        action_items=[
            "Alex: Implement retry logic using SQS visibility timeout",
            "Sarah: Document the SQS approach in ADR",
            "Mike: Share Stripe rate limit documentation",
        ],
        decisions=[
            "Use SQS visibility timeout for retry scheduling instead of cron jobs",
            "Max 5 retry attempts before moving to DLQ",
        ],
    ),
]

DEMO_MEETING_CONTEXT = MeetingContext(meetings=DEMO_MEETINGS)

# =============================================================================
# DOCUMENTATION DEMO DATA
# =============================================================================

DEMO_DOCS_SECTIONS = [
    DocSection(
        file_path="docs/architecture/payments-service.md",
        section_title="Webhook Processing Flow",
        content="""## Webhook Processing Flow

```
Stripe ──▶ POST /webhooks/stripe ──▶ Signature Check ──▶ SQS Queue
                                                            │
                                          ┌─────────────────┘
                                          ▼
                                    Event Processor ──▶ Handler ──▶ Database
                                          │
                                          ▼ (on failure)
                                    Dead Letter Queue
```

### File Paths

| Component | Path | Purpose |
|-----------|------|---------|
| Webhook endpoint | `src/api/webhooks/stripe.ts` | Receives POST, verifies signature |
| Event processor | `src/workers/webhook-processor.ts` | Polls SQS, routes to handlers |
| Charge handler | `src/handlers/stripe/charge-succeeded.ts` | Processes successful charges |

### Processing Steps

1. **Receive** - Webhook hits `/webhooks/stripe`, signature verified
2. **Queue** - Raw event published to `payments-webhooks` SQS queue
3. **Process** - Worker polls queue, checks idempotency, routes to handler
4. **Handle** - Handler updates database, publishes domain events
5. **Retry** - Failed events retry with exponential backoff, then DLQ""",
        doc_type="architecture",
    ),
    DocSection(
        file_path="docs/architecture/payments-service.md",
        section_title="Dead Letter Queue Strategy",
        content="""## Dead Letter Queue Strategy

Events move to DLQ after max retry attempts:

1. First failure → retry after 1 minute
2. Second failure → retry after 5 minutes
3. Third failure → retry after 30 minutes
4. Fourth failure → retry after 2 hours
5. Fifth failure → move to DLQ, alert on-call

**DLQ monitoring:** CloudWatch alarm triggers PagerDuty when DLQ depth > 5.

DLQ table schema in `migrations/004_webhook_dlq.sql`:

```sql
CREATE TABLE webhook_dlq (
    id UUID PRIMARY KEY,
    event_id VARCHAR(255) UNIQUE NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    failure_reason TEXT,
    attempts INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```""",
        doc_type="architecture",
    ),
    DocSection(
        file_path="docs/standards/typescript.md",
        section_title="Error Handling",
        content="""## Error Handling

### Result Pattern
Use `Result<T, E>` pattern for operations that can fail. Never throw exceptions from business logic.

```typescript
import { Result, ok, err } from '@/utils/result';

async function processWebhook(event: WebhookEvent): Promise<Result<void, WebhookError>> {
    const validated = validateEvent(event);
    if (!validated.ok) {
        return err(new WebhookError('VALIDATION_FAILED', validated.error));
    }

    try {
        await handleEvent(validated.value);
        return ok(undefined);
    } catch (e) {
        return err(new WebhookError('PROCESSING_FAILED', e.message));
    }
}
```

### Error Classes
Define specific error classes for each domain:

```typescript
class WebhookError extends BaseError {
    constructor(
        public code: 'VALIDATION_FAILED' | 'PROCESSING_FAILED' | 'RETRY_EXHAUSTED',
        message: string
    ) {
        super(message);
    }
}
```""",
        doc_type="standards",
    ),
    DocSection(
        file_path="docs/standards/testing.md",
        section_title="Testing AWS Services",
        content="""## Testing AWS Services

### Mocking SQS
Use `@aws-sdk/client-sqs-mock` for unit tests:

```typescript
import { mockClient } from 'aws-sdk-client-mock';
import { SQSClient, SendMessageCommand } from '@aws-sdk/client-sqs';

const sqsMock = mockClient(SQSClient);

beforeEach(() => {
    sqsMock.reset();
});

it('should retry failed webhooks', async () => {
    sqsMock.on(SendMessageCommand).resolves({
        MessageId: 'test-123',
    });

    await retryWebhook(failedEvent);

    expect(sqsMock.calls()).toHaveLength(1);
    const call = sqsMock.calls()[0];
    expect(call.args[0].input.DelaySeconds).toBe(60); // 1 minute retry
});
```

### Test File Location
Place tests in `tests/workers/` for worker-related code:
- `tests/workers/webhook-processor.test.ts`
- `tests/workers/retry-handler.test.ts`""",
        doc_type="standards",
    ),
]

DEMO_DOCS_CONTEXT = DocsContext(sections=DEMO_DOCS_SECTIONS)

# =============================================================================
# SLACK DEMO DATA
# =============================================================================

DEMO_SLACK_MESSAGES = [
    SlackMessage(
        message_id="1710763200.000100",
        channel_id="C01234567",
        channel_name="payments-team",
        user_id="U12345678",
        user_name="Sarah Kim",
        text="@channel Starting work on webhook retries today. Quick q: should we use SQS visibility timeout or build a separate retry service?",
        timestamp=datetime(2024, 3, 18, 10, 0, 0, tzinfo=UTC),
        thread_ts=None,
        permalink="https://slack.com/archives/C01234567/p1710763200000100",
        reactions=["eyes", "thinking_face"],
    ),
]

DEMO_SLACK_REPLIES = [
    SlackMessage(
        message_id="1710763500.000200",
        channel_id="C01234567",
        channel_name="payments-team",
        user_id="U87654321",
        user_name="Mike Johnson",
        text="SQS visibility timeout is way simpler. We used that at my last company for the same use case.",
        timestamp=datetime(2024, 3, 18, 10, 5, 0, tzinfo=UTC),
        thread_ts="1710763200.000100",
        permalink="https://slack.com/archives/C01234567/p1710763500000200",
        reactions=["+1"],
    ),
    SlackMessage(
        message_id="1710763800.000300",
        channel_id="C01234567",
        channel_name="payments-team",
        user_id="U12345678",
        user_name="Sarah Kim",
        text="Perfect, that matches what we discussed in planning. I'll use calculateBackoff() helper for the delay calculation.",
        timestamp=datetime(2024, 3, 18, 10, 10, 0, tzinfo=UTC),
        thread_ts="1710763200.000100",
        permalink="https://slack.com/archives/C01234567/p1710763800000300",
        reactions=[],
    ),
]

DEMO_SLACK_THREAD = SlackThread(
    parent_message=DEMO_SLACK_MESSAGES[0],
    replies=DEMO_SLACK_REPLIES,
    participant_names=["Sarah Kim", "Mike Johnson"],
    decisions=["Use SQS visibility timeout for retry scheduling"],
    action_items=[],
)

DEMO_SLACK_CONTEXT = SlackContext(
    threads=[DEMO_SLACK_THREAD],
    standalone_messages=[],
)


# =============================================================================
# SOURCE CONTEXT BUILDERS
# =============================================================================


def get_demo_source_contexts() -> dict[str, SourceContext]:
    """Get demo source contexts for synthesis.

    Returns:
        Dictionary mapping source names to SourceContext instances.
    """
    return {
        "jira": SourceContext(
            source_name="jira",
            source_type="issue_tracker",
            data=DEMO_JIRA_CONTEXT,
            raw_text=_format_jira_raw_text(DEMO_JIRA_CONTEXT),
            metadata={"ticket_id": DEMO_TASK_ID},
        ),
        "fireflies": SourceContext(
            source_name="fireflies",
            source_type="meeting_transcript",
            data=DEMO_MEETING_CONTEXT,
            raw_text=_format_meeting_raw_text(DEMO_MEETING_CONTEXT),
            metadata={"meeting_count": len(DEMO_MEETINGS)},
        ),
        "local_docs": SourceContext(
            source_name="local_docs",
            source_type="documentation",
            data=DEMO_DOCS_CONTEXT,
            raw_text=_format_docs_raw_text(DEMO_DOCS_CONTEXT),
            metadata={"section_count": len(DEMO_DOCS_SECTIONS)},
        ),
        "slack": SourceContext(
            source_name="slack",
            source_type="chat",
            data=DEMO_SLACK_CONTEXT,
            raw_text=_format_slack_raw_text(DEMO_SLACK_CONTEXT),
            metadata={"thread_count": 1},
        ),
    }


def _format_jira_raw_text(context: JiraContext) -> str:
    """Format Jira context as raw text for synthesis."""
    ticket = context.ticket
    parts = [
        f"# Jira Ticket: {ticket.ticket_id}",
        f"## {ticket.title}",
        f"**Status:** {ticket.status}",
        f"**Assignee:** {ticket.assignee}",
        f"**Sprint:** {ticket.sprint}",
        f"**Components:** {', '.join(ticket.components)}",
        f"**Labels:** {', '.join(ticket.labels)}",
        "",
        "### Description",
        ticket.description or "(no description)",
        "",
        "### Acceptance Criteria",
        ticket.acceptance_criteria or "(no acceptance criteria)",
        "",
    ]

    if context.comments:
        parts.append("### Comments")
        for comment in context.comments:
            date_str = comment.created.strftime("%Y-%m-%d %H:%M")
            parts.append(f"**{comment.author}** ({date_str}):")
            parts.append(comment.body)
            parts.append("")

    if context.linked_issues:
        parts.append("### Linked Issues")
        for link in context.linked_issues:
            parts.append(f"- {link.ticket_id}: {link.title} [{link.status}] ({link.link_type})")

    return "\n".join(parts)


def _format_meeting_raw_text(context: MeetingContext) -> str:
    """Format meeting context as raw text for synthesis."""
    parts = ["# Meeting Transcripts"]

    for meeting in context.meetings:
        date_str = meeting.meeting_date.strftime("%Y-%m-%d")
        parts.extend(
            [
                f"## {meeting.meeting_title} ({date_str})",
                f"**Participants:** {', '.join(meeting.participants)}",
                "",
                "### Transcript Excerpt",
                meeting.excerpt,
                "",
            ]
        )

        if meeting.decisions:
            parts.append("### Decisions")
            for decision in meeting.decisions:
                parts.append(f"- {decision}")
            parts.append("")

        if meeting.action_items:
            parts.append("### Action Items")
            for item in meeting.action_items:
                parts.append(f"- {item}")
            parts.append("")

    return "\n".join(parts)


def _format_docs_raw_text(context: DocsContext) -> str:
    """Format docs context as raw text for synthesis."""
    parts = ["# Documentation"]

    for section in context.sections:
        title = section.section_title or section.file_path
        parts.extend(
            [
                f"## {title}",
                f"*Source: {section.file_path}* [{section.doc_type}]",
                "",
                section.content,
                "",
            ]
        )

    return "\n".join(parts)


def _format_slack_raw_text(context: SlackContext) -> str:
    """Format Slack context as raw text for synthesis."""
    parts = ["# Slack Discussions"]

    for thread in context.threads:
        parent = thread.parent_message
        parts.extend(
            [
                f"## #{parent.channel_name}",
                f"**{parent.user_name}** ({parent.timestamp.strftime('%Y-%m-%d %H:%M')}):",
                parent.text,
                "",
            ]
        )

        for reply in thread.replies:
            parts.extend(
                [
                    f"**{reply.user_name}** ({reply.timestamp.strftime('%H:%M')}):",
                    reply.text,
                    "",
                ]
            )

        if thread.decisions:
            parts.append("**Decisions identified:**")
            for decision in thread.decisions:
                parts.append(f"- {decision}")
            parts.append("")

    return "\n".join(parts)


# =============================================================================
# PRE-BAKED SYNTHESIS
# =============================================================================

# Pre-baked synthesis output - exactly matches README example
_DEMO_SYNTHESIS = """## Task: PROJ-123 — Add retry logic to payment webhook handler

### Requirements
1. Implement exponential backoff for failed webhook deliveries
2. Max 5 retry attempts over 24 hours
3. Dead-letter queue for permanently failed webhooks
4. Metrics for retry success/failure rates

Acceptance criteria: [Jira PROJ-123]
- [ ] Webhooks retry with exponential backoff (1min, 5min, 30min, 2hr, 12hr)
- [ ] Failed webhooks move to DLQ after 5 attempts
- [ ] Dashboard shows retry metrics

### Key Decisions
- **Use SQS with visibility timeout** for retry scheduling, not cron jobs.
  Decided by @sarah in March 15 sprint planning. Rationale: SQS handles
  timing natively, reduces operational overhead. [Meeting: Sprint 23 Planning]

- **Exponential backoff schedule**: 1min → 5min → 30min → 2hr → 12hr.
  Based on payment processor rate limits. [Comment by @mike, Mar 16]

### Architecture Context
Webhook flow: `PaymentController` → `WebhookService.dispatch()` → SQS queue
→ `WebhookWorker.process()` → external endpoint.

Add retry logic in `WebhookWorker.process()` at:
`src/workers/webhook_worker.ts:45-80`

DLQ table schema in `migrations/004_webhook_dlq.sql`. [Architecture: payments-service.md]

### Coding Standards
- Use `Result<T, WebhookError>` pattern, don't throw exceptions
- Retry delays: use `calculateBackoff(attempt)` helper from `src/utils/retry.ts`
- Tests: mock SQS with `@aws-sdk/client-sqs-mock`, see `tests/workers/` for examples
[Standards: typescript.md, testing.md]

### Related Work
- PROJ-456: "Payment webhook initial implementation" (Done) — base implementation
- PROJ-789: "Add webhook monitoring dashboard" (In Progress) — will consume the metrics
"""


def get_demo_synthesis() -> str:
    """Get pre-baked synthesis output for demo mode.

    This returns the exact output shown in the README, which demonstrates
    the quality of synthesis users can expect.

    Returns:
        Pre-baked synthesis markdown string.
    """
    return _DEMO_SYNTHESIS
