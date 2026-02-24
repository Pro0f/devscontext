# Testing Standards

## Test Requirements

### Coverage
- Minimum 80% code coverage required
- Critical paths (payments, auth) require 95%+

### Test Types
1. Unit tests: Test individual functions
2. Integration tests: Test component interactions
3. E2E tests: Test full user flows

## Mocking Strategy

### External Services
Always mock external API calls in unit tests:

```typescript
import { mock } from 'jest-mock-extended';
import { StripeClient } from './stripe';

const mockStripe = mock<StripeClient>();
mockStripe.createCharge.mockResolvedValue({ id: 'ch_123' });
```

### Database
Use in-memory database for unit tests:

```typescript
beforeEach(async () => {
  await db.migrate.latest();
  await db.seed.run();
});

afterEach(async () => {
  await db.migrate.rollback();
});
```

### Time
Mock time-dependent functions:

```typescript
jest.useFakeTimers();
jest.setSystemTime(new Date('2024-01-15T10:00:00Z'));
```

## Test Organization

### File Structure
```
src/
  payments/
    processor.ts
    processor.test.ts  # Unit tests next to source
tests/
  integration/
    payments.test.ts   # Integration tests separate
  e2e/
    checkout.test.ts   # E2E tests separate
```

### Naming
- Describe blocks: Component/function name
- It blocks: "should" + expected behavior

```typescript
describe('PaymentProcessor', () => {
  describe('process', () => {
    it('should create a successful charge', async () => {
      // ...
    });

    it('should throw PaymentError on declined card', async () => {
      // ...
    });
  });
});
```

## Assertions

### Prefer Specific Assertions
```typescript
// Good
expect(result.status).toBe('success');
expect(result.amount).toBe(1000);

// Avoid
expect(result).toMatchObject({ status: 'success' });
```

### Async Assertions
```typescript
await expect(processPayment('invalid')).rejects.toThrow(PaymentError);
```
