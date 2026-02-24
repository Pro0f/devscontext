# Payments Service Architecture

This document describes the architecture of the payments service.

## Overview

The payments service handles all payment processing for the platform,
including credit card transactions, refunds, and webhook handling.

## Webhook Flow

Payment webhooks are received from Stripe and processed as follows:

1. Webhook received at `/api/webhooks/stripe`
2. Signature verified using `stripe.webhooks.constructEvent()`
3. Event dispatched to appropriate handler
4. Handler processes event and updates database
5. Response sent to Stripe

### Retry Logic

Failed webhook processing triggers automatic retry:
- First retry: 1 minute
- Second retry: 5 minutes
- Third retry: 30 minutes
- Final retry: 2 hours

## File Structure

```
src/
  payments/
    handlers/
      webhook.ts      # Webhook endpoint
      charge.ts       # Charge handlers
      refund.ts       # Refund handlers
    services/
      stripe.ts       # Stripe client wrapper
      processor.ts    # Payment processor
    models/
      payment.ts      # Payment model
      transaction.ts  # Transaction model
```

## Infrastructure

### Database

PostgreSQL database with the following tables:
- `payments` - Payment records
- `transactions` - Transaction history
- `webhook_events` - Webhook event log

### Queue

Redis-backed job queue for async processing:
- Payment processing jobs
- Refund processing jobs
- Webhook retry jobs

## Security

All payment data is encrypted at rest using AES-256.
PCI DSS compliance is maintained through:
- Tokenization of card data
- Audit logging
- Access controls
