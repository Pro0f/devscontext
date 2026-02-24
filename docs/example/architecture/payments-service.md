# Payments Service Architecture

> **Note:** This is SAMPLE documentation for testing DevsContext. It demonstrates what good architecture docs look like for optimal context retrieval.

## Overview

The payments service processes all financial transactions for the platform, including one-time charges, subscription billing, refunds, and payment provider webhooks.

**Responsibilities:**
- Process credit card and ACH payments via Stripe
- Handle subscription lifecycle (create, upgrade, cancel)
- Process refunds and chargebacks
- Receive and process payment provider webhooks
- Maintain payment audit trail

**Does NOT handle:**
- User authentication (uses auth-service tokens)
- Email notifications (publishes events to notification-service)
- Raw card storage (uses Stripe tokenization)

## Webhook Processing Flow

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
| Refund handler | `src/handlers/stripe/charge-refunded.ts` | Processes refunds |
| Subscription handler | `src/handlers/stripe/subscription-updated.ts` | Processes subscription changes |

### Processing Steps

1. **Receive** - Webhook hits `/webhooks/stripe`, signature verified
2. **Queue** - Raw event published to `payments-webhooks` SQS queue
3. **Process** - Worker polls queue, checks idempotency, routes to handler
4. **Handle** - Handler updates database, publishes domain events
5. **Retry** - Failed events retry 3x with exponential backoff, then DLQ

## Infrastructure

### SQS Queues

| Queue | Purpose | Visibility Timeout |
|-------|---------|-------------------|
| `payments-webhooks` | Primary webhook events | 30 seconds |
| `payments-webhooks-dlq` | Failed events for manual review | 5 minutes |
| `payments-jobs` | Async jobs (reports, reconciliation) | 60 seconds |

### Dead Letter Queue Strategy

Events move to DLQ after 3 failed processing attempts:

1. First failure → retry after 1 minute
2. Second failure → retry after 5 minutes
3. Third failure → retry after 15 minutes
4. Fourth failure → move to DLQ, alert on-call

**DLQ monitoring:** CloudWatch alarm triggers PagerDuty when DLQ depth > 5.

### Environment Variables

```
STRIPE_SECRET_KEY        # Stripe API key
STRIPE_WEBHOOK_SECRET    # Webhook signature verification
PAYMENTS_QUEUE_URL       # SQS queue URL
PAYMENTS_DLQ_URL         # Dead letter queue URL
DATABASE_URL             # PostgreSQL connection string
```

## Database Schema

### payment_events

Immutable log of all payment events for audit and replay.

```sql
CREATE TABLE payment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(255) UNIQUE NOT NULL,  -- Stripe event ID (idempotency key)
    event_type VARCHAR(100) NOT NULL,       -- charge.succeeded, refund.created, etc.
    payment_id UUID REFERENCES payments(id),
    payload JSONB NOT NULL,                 -- Raw Stripe event
    status VARCHAR(20) DEFAULT 'pending',   -- pending, processed, failed
    processed_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_payment_events_status ON payment_events(status);
CREATE INDEX idx_payment_events_type ON payment_events(event_type);
```

### payments

```sql
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    status VARCHAR(20) NOT NULL,  -- pending, succeeded, failed, refunded
    stripe_payment_id VARCHAR(255),
    stripe_customer_id VARCHAR(255),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Idempotency

All webhook handlers must be idempotent. Before processing:

```typescript
const existing = await db.paymentEvents.findByEventId(event.id);
if (existing?.status === 'processed') {
  logger.info('Skipping duplicate event', { eventId: event.id });
  return;
}
```
