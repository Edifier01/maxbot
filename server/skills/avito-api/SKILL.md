---
name: avito-api
description: "Use when working with Avito Business API (api.avito.ru) — OAuth2, объявления, остатки, мессенджер, статистика, VAS. Triggers: Avito API, авито апи, объявления, чаты авито, api.avito.ru."
category: integrations
risk: safe
source: project
capabilities: [api-integration, avito, oauth2, marketplace]
tools: [claude, cursor]
---

# Avito Business API

## Overview

Integration with Avito Business API at `https://api.avito.ru`. Official docs: [developers.avito.ru](https://developers.avito.ru/api-catalog).

**Project context:** API access may be unavailable until Avito Pro tariff is confirmed. Always check `AVITO_API_ENABLED` and implement graceful fallback to Playwright via `AvitoProviderRouter`.

## Prerequisites

- Avito Pro account (Extended+ tariff recommended for full API)
- Application registered in Avito cabinet → `client_id`, `client_secret`
- `AVITO_USER_ID` — account user ID for path parameters

## Authentication

OAuth 2.0 client credentials:

```python
POST https://api.avito.ru/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id={CLIENT_ID}&client_secret={CLIENT_SECRET}
```

- Cache access token in Redis with TTL = `expires_in - 300` seconds
- Refresh proactively before expiry

## Core Endpoints

| Domain | Method | Path | Purpose |
|--------|--------|------|---------|
| Items | GET | `/core/v1/accounts/{user_id}/items/` | List listings |
| Items | GET | `/core/v1/accounts/{user_id}/items/{item_id}/` | Item details |
| Items | POST | `/core/v1/items/{item_id}/update_price` | Update price (rubles in body) |
| Stock | PUT | `/stock-management/1/stocks` | Bulk stock update |
| Stock | POST | `/stock-management/1/info` | Read stocks (max 10 ids) |
| Stats | POST | `/stats/v1/accounts/{user_id}/items` | Item statistics |
| Messenger | GET | `/messenger/v2/accounts/{user_id}/chats` | List chats |
| Messenger | POST | `/messenger/v1/accounts/{user_id}/chats/{chat_id}/messages` | Send message |
| VAS | GET | `/core/v1/accounts/{user_id}/items/{item_id}/vas/prices` | Promotion prices |
| VAS | POST | `/core/v1/accounts/{user_id}/items/{item_id}/vas` | Apply promotion |

## Implementation Rules

1. **Rate limiting:** max `max_concurrent_avito_requests` (default 5) via semaphore
2. **Retry:** tenacity with exponential backoff on 429, 502, 503
3. **Idempotency:** stock/price updates must be safe to retry
4. **Logging:** log request_id, endpoint, status — never log tokens
5. **Feature flag:** if `AVITO_API_ENABLED=false`, `is_available()` returns False

## Provider Interface

Implement `AvitoProvider` protocol from `domain/repositories.py`:

```python
class AvitoApiProvider:
    kind = ProviderKind.AVITO_API

    async def is_available(self) -> bool:
        return settings.avito_api_enabled and bool(settings.avito_client_id)

    async def update_stock(self, avito_item_id: int, quantity: int) -> None: ...
    async def update_price(self, avito_item_id: int, price_kopecks: int) -> None: ...
```

## When API Is Insufficient

Use Playwright fallback for:
- Photo upload (if API limits apply)
- Complex category-specific fields
- UI-only promotion flows
- Initial auth before OAuth credentials obtained

Route via `AvitoProviderRouter.select()` — API first, Playwright fallback.

## Error Handling

| Status | Action |
|--------|--------|
| 401 | Refresh token, retry once |
| 403 | Log + alert owner (tariff/scope issue) |
| 429 | Backoff + queue |
| 404 | Mark listing stale in DB |

## Security

- Store credentials in environment variables only (see `varlock` skill)
- Never commit `client_secret`
- Scope OAuth permissions to minimum required sections

## Related Skills

- `api-security-best-practices` — auth, rate limiting
- `playwright-skill` — UI fallback
- `workflow-automation` — retry and durable jobs

## Limitations

- API availability depends on Avito Pro tariff — verify before production
- Sandbox may differ from production behavior
- Some operations may require Autoload/XML feed instead of REST
