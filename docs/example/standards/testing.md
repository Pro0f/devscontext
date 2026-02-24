# Testing Standards

> **Note:** This is SAMPLE documentation for testing DevsContext. It demonstrates what good testing standards docs look like for optimal context retrieval.

## Test Structure and Organization

### Directory Layout

```
src/
├── services/
│   ├── payment.service.ts
│   └── payment.service.test.ts    # Unit tests colocated
├── api/
│   └── routes/
│       └── payments.ts
tests/
├── integration/
│   ├── api/
│   │   └── payments.test.ts       # API integration tests
│   └── services/
│       └── payment-flow.test.ts   # Service integration tests
├── e2e/
│   └── checkout.test.ts           # End-to-end tests
└── factories/
    ├── user.factory.ts            # Test data factories
    └── payment.factory.ts
```

### Naming Conventions

- Test files: `*.test.ts` or `*.spec.ts`
- Describe blocks: Name of module/function being tested
- It blocks: Start with "should" + expected behavior

```typescript
describe('PaymentService', () => {
  describe('processPayment', () => {
    it('should create a charge for valid payment', async () => { ... });
    it('should return error for insufficient funds', async () => { ... });
    it('should be idempotent for duplicate requests', async () => { ... });
  });
});
```

## Unit vs Integration Tests

### Unit Tests

**What to unit test:**
- Pure functions (no side effects)
- Business logic and calculations
- Data transformations
- Validation functions
- Individual class methods

**Characteristics:**
- Fast (< 10ms per test)
- No I/O (database, network, filesystem)
- All dependencies mocked
- Test one thing per test

```typescript
// Unit test example
describe('calculateTax', () => {
  it('should apply 10% tax rate', () => {
    expect(calculateTax(100, 0.10)).toBe(10);
  });

  it('should round to 2 decimal places', () => {
    expect(calculateTax(33.33, 0.10)).toBe(3.33);
  });
});
```

### Integration Tests

**What to integration test:**
- API endpoints (full HTTP request/response)
- Database queries and transactions
- Service-to-service communication
- Message queue producers/consumers
- Caching behavior

**Characteristics:**
- Slower (100ms - 5s per test)
- Uses real database (test instance)
- External services mocked at boundary
- May test multiple components together

```typescript
// Integration test example
describe('POST /api/payments', () => {
  beforeEach(async () => {
    await db.payments.deleteAll();
  });

  it('should create payment and return 201', async () => {
    const response = await request(app)
      .post('/api/payments')
      .send({ amount: 1000, userId: 'user_123' });

    expect(response.status).toBe(201);
    expect(response.body.id).toBeDefined();

    const saved = await db.payments.findById(response.body.id);
    expect(saved.amount).toBe(1000);
  });
});
```

## Mocking Guidelines

### What to Mock

✅ **Do mock:**
- External HTTP APIs (Stripe, SendGrid, etc.)
- Time/dates (`jest.useFakeTimers()`)
- Random values when determinism needed
- Environment-specific services

❌ **Don't mock:**
- Internal modules/services (test them together)
- The database in integration tests
- Simple utility functions

### Mock Patterns

**HTTP client mocking:**

```typescript
import nock from 'nock';

beforeEach(() => {
  nock('https://api.stripe.com')
    .post('/v1/charges')
    .reply(200, { id: 'ch_123', status: 'succeeded' });
});

afterEach(() => {
  nock.cleanAll();
});
```

**Time mocking:**

```typescript
beforeEach(() => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date('2024-01-15T10:00:00Z'));
});

afterEach(() => {
  jest.useRealTimers();
});
```

**Dependency injection for testability:**

```typescript
// Good - dependencies injected
class PaymentService {
  constructor(
    private stripe: StripeClient,
    private db: Database
  ) {}
}

// In tests
const mockStripe = { createCharge: jest.fn() };
const service = new PaymentService(mockStripe, testDb);
```

### Assertions

Prefer specific assertions over generic ones:

```typescript
// Good - specific
expect(result.status).toBe('succeeded');
expect(result.amount).toBe(1000);
expect(result.createdAt).toBeInstanceOf(Date);

// Bad - too broad
expect(result).toMatchObject({ status: 'succeeded' });
expect(result).toBeDefined();
```

## Test Data

### Use Factories

```typescript
// factories/payment.factory.ts
export function createPayment(overrides: Partial<Payment> = {}): Payment {
  return {
    id: `pay_${Date.now()}`,
    amount: 1000,
    currency: 'USD',
    status: 'pending',
    userId: 'user_test_123',
    createdAt: new Date(),
    ...overrides,
  };
}

// Usage
const payment = createPayment({ amount: 5000, status: 'succeeded' });
```

### Database Seeding

```typescript
// tests/setup.ts
beforeEach(async () => {
  await db.migrate.latest();
});

afterEach(async () => {
  await db.truncateAll(); // Fast cleanup
});

afterAll(async () => {
  await db.destroy();
});
```

## Coverage Requirements

| Type | Minimum | Target |
|------|---------|--------|
| Statements | 80% | 90% |
| Branches | 75% | 85% |
| Functions | 80% | 90% |
| Lines | 80% | 90% |

Critical paths (payments, auth) require 95%+ coverage.
