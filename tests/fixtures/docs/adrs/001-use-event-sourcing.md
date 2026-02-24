# ADR 001: Use Event Sourcing for Payment History

## Status

Accepted

## Context

We need to maintain a complete, auditable history of all payment-related
changes for compliance and debugging purposes. Traditional CRUD operations
lose historical state.

## Decision

We will use event sourcing for the payments domain:

1. All payment state changes are recorded as immutable events
2. Current state is derived by replaying events
3. Events are stored in an append-only event store

### Event Types

```typescript
type PaymentEvent =
  | { type: 'PaymentInitiated'; amount: number; currency: string }
  | { type: 'PaymentAuthorized'; authCode: string }
  | { type: 'PaymentCaptured'; captureId: string }
  | { type: 'PaymentRefunded'; amount: number; reason: string }
  | { type: 'PaymentFailed'; error: string };
```

## Consequences

### Positive
- Complete audit trail
- Easy debugging (replay to any point)
- Natural fit for distributed systems

### Negative
- More complex than CRUD
- Requires event store infrastructure
- Learning curve for team

### Mitigations
- Use existing event store library
- Create helper functions for common patterns
- Document patterns and provide examples

## Related

- ADR 002: Event Store Selection
- Architecture: payments-service.md
