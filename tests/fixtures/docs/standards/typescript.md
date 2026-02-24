# TypeScript Coding Standards

## Error Handling

Always use typed errors and proper error boundaries:

```typescript
class PaymentError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly retryable: boolean = false
  ) {
    super(message);
    this.name = 'PaymentError';
  }
}
```

### Error Responses

API errors should follow this structure:
- 4xx errors: Client errors, include helpful message
- 5xx errors: Server errors, log details, return generic message

## Naming Conventions

### Files
- Use kebab-case for file names: `payment-processor.ts`
- Use PascalCase for component files: `PaymentForm.tsx`

### Variables
- Use camelCase for variables and functions
- Use PascalCase for classes and types
- Use SCREAMING_SNAKE_CASE for constants

### Functions
- Prefix boolean functions with `is`, `has`, `can`: `isValidPayment()`
- Prefix async functions clearly when needed: `fetchPayment()`

## Testing Requirements

### Unit Tests
- Every exported function needs a test
- Mock external dependencies
- Test error cases, not just happy paths

### Integration Tests
- Test full API flows
- Use test database
- Clean up after tests

## Async Patterns

### Prefer async/await
```typescript
// Good
async function processPayment(id: string): Promise<Payment> {
  const payment = await fetchPayment(id);
  return await processor.process(payment);
}

// Avoid
function processPayment(id: string): Promise<Payment> {
  return fetchPayment(id).then(payment => processor.process(payment));
}
```

### Error Handling in Async
Always wrap async operations in try/catch:

```typescript
async function safeProcess(id: string): Promise<Result<Payment, Error>> {
  try {
    const payment = await processPayment(id);
    return { ok: true, value: payment };
  } catch (error) {
    logger.error('Payment processing failed', { id, error });
    return { ok: false, error };
  }
}
```
