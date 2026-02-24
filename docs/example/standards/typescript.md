# TypeScript Coding Standards

> **Note:** This is SAMPLE documentation for testing DevsContext. It demonstrates what good coding standards docs look like for optimal context retrieval.

## Error Handling

### Use Result Types, Don't Throw

Functions that can fail should return `Result<T, E>` instead of throwing:

```typescript
type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };

// Good - explicit error handling
async function getUser(id: string): Promise<Result<User, UserError>> {
  const user = await db.users.find(id);
  if (!user) {
    return { ok: false, error: { code: 'NOT_FOUND', message: `User ${id} not found` } };
  }
  return { ok: true, value: user };
}

// Usage
const result = await getUser(id);
if (!result.ok) {
  logger.warn('User lookup failed', { error: result.error });
  return;
}
const user = result.value;
```

### When Throwing Is Acceptable

Only throw for programmer errors (bugs), never for expected failures:
- Assertion failures in development
- Invalid arguments that indicate a bug
- Unrecoverable system errors

```typescript
// OK to throw - this is a bug if it happens
function divide(a: number, b: number): number {
  if (b === 0) throw new Error('Division by zero - this is a bug');
  return a / b;
}
```

## Naming Conventions

### Variables and Functions: camelCase

```typescript
const userId = 'user_123';
const isActive = true;
function calculateTotal(items: Item[]): number { ... }
async function fetchUserProfile(id: string): Promise<User> { ... }
```

### Classes, Types, Interfaces: PascalCase

```typescript
class PaymentProcessor { ... }
interface UserProfile { ... }
type PaymentStatus = 'pending' | 'completed' | 'failed';
```

### Constants and Enums: UPPER_SNAKE_CASE

```typescript
const MAX_RETRY_COUNT = 3;
const DEFAULT_TIMEOUT_MS = 5000;

enum PaymentStatus {
  PENDING = 'pending',
  COMPLETED = 'completed',
  FAILED = 'failed',
}
```

### Files: kebab-case

```
payment-processor.ts
user-profile.service.ts
webhook-handler.test.ts
```

## Testing Requirements

### Unit Tests

Every exported function needs unit tests covering:
- Happy path (expected inputs → expected outputs)
- Edge cases (empty arrays, null values, boundaries)
- Error cases (invalid inputs, failure scenarios)

```typescript
describe('calculateTotal', () => {
  it('returns sum of item prices', () => {
    const items = [{ price: 100 }, { price: 200 }];
    expect(calculateTotal(items)).toBe(300);
  });

  it('returns 0 for empty array', () => {
    expect(calculateTotal([])).toBe(0);
  });

  it('handles items with zero price', () => {
    const items = [{ price: 0 }, { price: 100 }];
    expect(calculateTotal(items)).toBe(100);
  });
});
```

### Integration Tests

Required for:
- API endpoints (full request/response cycle)
- Database operations (real queries, transactions)
- External service integrations (with mocked services)

### Test Factories

Use factories to create test data:

```typescript
// factories/user.factory.ts
export function createUser(overrides: Partial<User> = {}): User {
  return {
    id: 'user_test_123',
    email: 'test@example.com',
    name: 'Test User',
    createdAt: new Date('2024-01-01'),
    ...overrides,
  };
}

// In tests
const user = createUser({ email: 'custom@example.com' });
```

### Mocking

Mock external dependencies, not internal modules:

```typescript
// Good - mock external HTTP client
jest.mock('axios');
const mockAxios = axios as jest.Mocked<typeof axios>;
mockAxios.get.mockResolvedValue({ data: { user: mockUser } });

// Bad - don't mock internal modules
jest.mock('../services/user.service'); // Avoid this
```

## Async Patterns

### Always Use async/await

Never use raw `.then()` chains:

```typescript
// Good
async function processPayment(id: string): Promise<Payment> {
  const payment = await fetchPayment(id);
  const result = await chargeCard(payment);
  await saveResult(result);
  return result;
}

// Bad - harder to read, error handling is awkward
function processPayment(id: string): Promise<Payment> {
  return fetchPayment(id)
    .then(payment => chargeCard(payment))
    .then(result => saveResult(result).then(() => result));
}
```

### Parallel vs Sequential

Use `Promise.all` for independent operations:

```typescript
// Good - parallel execution
const [user, payments, settings] = await Promise.all([
  fetchUser(userId),
  fetchPayments(userId),
  fetchSettings(userId),
]);

// Bad - unnecessary sequential execution
const user = await fetchUser(userId);
const payments = await fetchPayments(userId);
const settings = await fetchSettings(userId);
```

### Error Handling in Async

Wrap async operations that might fail:

```typescript
async function safeProcess(id: string): Promise<Result<Payment, ProcessError>> {
  try {
    const payment = await processPayment(id);
    return { ok: true, value: payment };
  } catch (error) {
    logger.error('Payment processing failed', { id, error });
    return { ok: false, error: { code: 'PROCESS_FAILED', cause: error } };
  }
}
```
