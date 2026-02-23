# TypeScript Coding Standards

## General Guidelines

- Use TypeScript strict mode
- Prefer `const` over `let`, never use `var`
- Use meaningful variable names

## Authentication Patterns

When implementing authentication:

1. Always use the `AuthMiddleware` from `@company/auth`
2. Never store tokens in localStorage - use httpOnly cookies
3. Implement token refresh logic in the API client

```typescript
import { AuthMiddleware } from '@company/auth';

app.use('/api', AuthMiddleware.verify());
```

## Error Handling

Authentication errors should return:
- 401 for invalid/expired tokens
- 403 for insufficient permissions

```typescript
if (!token) {
  return res.status(401).json({ error: 'Unauthorized' });
}

if (!hasPermission(user, requiredScope)) {
  return res.status(403).json({ error: 'Forbidden' });
}
```

## Testing

- All authentication logic must have unit tests
- Use mock tokens for testing
- Test both success and failure paths
