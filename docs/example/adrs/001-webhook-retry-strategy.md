# ADR 001: Webhook Retry Strategy

> **Note:** This is SAMPLE documentation for testing DevsContext. It demonstrates what good ADR docs look like for optimal context retrieval.

## Status

Accepted (2024-01-15)

## Context

We receive webhooks from payment providers (Stripe, PayPal) that must be processed reliably. Webhook processing can fail due to:

- Transient network errors
- Database connection issues
- Temporary service unavailability
- Rate limiting from downstream services

We need a retry strategy that:
1. Recovers from transient failures automatically
2. Doesn't overwhelm failing services
3. Provides visibility into persistent failures
4. Ensures events are eventually processed or escalated

### Options Considered

**Option A: Linear backoff**
- Retry every 60 seconds, up to 5 times
- Simple to implement
- Risk: hammers failing services at constant rate

**Option B: Exponential backoff with max 3 retries**
- Retry at 1min, 5min, 15min intervals
- Backs off quickly for sustained failures
- 3 retries balances recovery vs. escalation speed

**Option C: Exponential backoff with jitter, unlimited retries**
- Similar to B but keeps retrying indefinitely
- Risk: events stuck in retry loop forever
- Harder to know when human intervention needed

## Decision

We will use **exponential backoff with a maximum of 3 retries** (Option B).

### Retry Schedule

| Attempt | Delay | Cumulative Time |
|---------|-------|-----------------|
| 1 | Immediate | 0 |
| 2 | 1 minute | 1 minute |
| 3 | 5 minutes | 6 minutes |
| 4 | 15 minutes | 21 minutes |
| DLQ | - | After 21 minutes |

### Implementation

```typescript
const RETRY_DELAYS_MS = [0, 60_000, 300_000, 900_000]; // 0, 1m, 5m, 15m

async function processWithRetry(event: WebhookEvent): Promise<void> {
  const attempt = event.retryCount + 1;

  if (attempt > 3) {
    await moveToDeadLetterQueue(event);
    await alertOncall('Webhook moved to DLQ', { eventId: event.id });
    return;
  }

  try {
    await processEvent(event);
  } catch (error) {
    if (isRetryable(error)) {
      const delay = RETRY_DELAYS_MS[attempt];
      await scheduleRetry(event, delay);
    } else {
      await markFailed(event, error);
    }
  }
}
```

### Retryable vs Non-Retryable Errors

**Retryable (transient):**
- Network timeouts
- HTTP 429 (rate limited)
- HTTP 503 (service unavailable)
- Database connection errors
- Redis connection errors

**Non-retryable (permanent):**
- HTTP 400 (bad request - our bug)
- HTTP 401/403 (auth failure - config issue)
- Validation errors
- Unknown event types
- Duplicate event (already processed)

## Consequences

### Positive

- **Automatic recovery**: Most transient failures resolve within 3 retries
- **Bounded time**: Events escalate to DLQ within 21 minutes
- **Reduced load**: Exponential backoff prevents overwhelming failing services
- **Clear escalation**: DLQ + alerts ensure humans know when intervention needed

### Negative

- **Requires idempotent handlers**: Since events may be processed multiple times during retries, all handlers must be idempotent
- **21-minute delay worst case**: Some events take up to 21 minutes to reach DLQ
- **DLQ monitoring required**: Team must monitor and process DLQ items

### Mitigations

**Idempotency requirement:**
- All handlers check `event_id` before processing
- Database unique constraint on `event_id` prevents duplicates
- Code review checklist includes idempotency check

**DLQ monitoring:**
- CloudWatch alarm when DLQ depth > 5
- PagerDuty alert for DLQ items older than 1 hour
- Weekly review of DLQ patterns

## Related

- [Architecture: Payments Service](../architecture/payments-service.md)
- [Standards: Error Handling](../standards/typescript.md#error-handling)
