# Agni AI - Platform guide

Multi-tenant voice-AI platform. **Organization = `clients` row.** Every tenant-owned
table has `client_id`; every query is scoped by the caller's organization.

## Roles

| Role | Scope | Can |
|---|---|---|
| `superadmin` | whole platform (no org) | create/suspend orgs, grant credits, platform stats, audit log, act on any org by passing `client_id` |
| `admin` | own org | everything in the org: users, agents, numbers, campaigns, billing, API keys, webhooks, integrations |
| `user` | own org | create/use agents, contacts, campaigns (read most things); cannot manage users, keys, webhooks, billing changes |

The *end user* (the person called) is a **contact**, not a login.

Auth: `Authorization: Bearer <JWT>` (dashboard) **or** `X-Api-Key: agni_...` (servers).
An API key acts as the admin who created it. A suspended org is locked out of every route.

## Money

* Balance on `clients.credit_balance`; every change is one row in `credit_transactions` (ledger).
* Rate: `clients.credits_per_minute` or `CREDITS_PER_MINUTE`. Billed by exact seconds, rounded up to 0.001.
* Calls are blocked *before* starting when the org is suspended / at 0 credits / at its concurrency limit (402/403/429).
* **Unanswered, busy, cancelled, provider-error and timed-out calls are never billed.**
* Each call is billed once (DB unique index + row lock). Verified under concurrency on PostgreSQL.
* `credits.low` webhook fires when the balance crosses `settings.low_credit_threshold` (default 5).
* Payment gateway is NOT integrated: superadmin records purchases via `POST /admin/organizations/{id}/credits`.

## Call lifecycle (`app/services/call_lifecycle.py`)

`finalize_call()` -> duration -> billing -> campaign counters / retry scheduling -> `call.failed` event.
Then `run_post_call_pipeline()` -> AI analysis -> signed `call.completed` webhook (transcript, summary,
sentiment, extraction, recording). Entry points: web sessions (`sessions.py`), Exotel callback
(`POST /telephony/exotel/status`), dialer (provider errors), reaper (stuck calls).

## Campaigns & dialer (`app/services/dialer.py`)

`POST /campaigns/{id}/contacts` adds audience -> `start` (validates caller ID, contacts, credits) ->
dialer loop dials respecting: calling window/timezone/days, per-campaign `max_concurrent`, org
`max_concurrent_calls`, credits; retries no-answer/busy up to `max_attempts` every `retry_delay_minutes`;
pauses the campaign (with `paused_reason`) if credits run out; completes it (+ `campaign.completed`) when done.

Run the worker: `python -m app.workers.run` (production) or `RUN_BACKGROUND_WORKERS=True` (dev).
Multiple worker processes are safe (`FOR UPDATE SKIP LOCKED`).

## Webhooks

Org admins register endpoints (`/webhooks`), choose events (`GET /webhooks/events`). Each delivery is
stored, signed and retried (30s, 2m, 10m, 1h, 6h; `WEBHOOK_MAX_ATTEMPTS`). Verify on your server:

```
X-Agni-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, f"{t}.{raw_body}")>
```
Reject timestamps older than 5 minutes. Destinations are SSRF-checked at registration **and** at send time.
`POST /webhooks/{id}/test`, `GET /webhooks/deliveries`, `POST /webhooks/deliveries/{id}/retry`.

## Endpoint map (new in this version)

Superadmin: `/admin/organizations[...]`, `/admin/stats`, `/admin/audit-logs`
Org: `/organization`, `/billing/{balance,transactions,usage}`, `/api-keys`, `/webhooks`
Campaigns: `/campaigns/{id}/{contacts,resume}`   Contacts: `/contacts/{id}/{notes,calls,stats,activities,campaigns}`, `/contacts/bulk-delete`
Agents: `PATCH /agents/{id}/status`, `/models`, `/models/{id}/voices`
Analytics: `/analytics/{overview,timeseries,sentiment,channels-by-hour,top-countries,agents}`
Integrations: `/integrations`, `/integrations/{calcom,ghl}/...`, `/appointments`, `POST /appointments/agent`
Telephony callback: `POST /telephony/exotel/status`

## Production checklist

1. `APP_ENV=production` -> app refuses to start with default JWT secret, missing
   `INBOUND_WEBHOOK_SECRET` / `SECRETS_ENCRYPTION_KEY`, or `DEBUG=True`.
2. `alembic upgrade head`.
3. Run API and `python -m app.workers.run` as separate processes (`RUN_BACKGROUND_WORKERS=False` on the API).
4. HTTPS in front; run uvicorn with `--proxy-headers` so rate limiting sees real client IPs.
5. The chat rate limiter is in-memory per process: use Redis/gateway limits if you run several API instances.

## NOT verified / still to do (be honest with your team)

* **Real phone calls have never been run.** `ExotelTelephonyProvider` follows Exotel's public
  `Calls/connect` API and is unit-tested against a mocked HTTP server only. The Exotel flow -> LiveKit SIP
  bridge and a LiveKit dispatch rule are configured in those dashboards; the inbound webhook records and
  gates the call but does **not** start an agent for phone calls.
* Cal.com and GoHighLevel clients are written from their public API docs and tested with fakes only.
* Voice sessions still spawn one subprocess per call (`AgentSessionManager`) - fine for testing, will not scale.
* Not built: payment gateway, SSO/2FA, email invites/password reset, per-user permissions beyond 3 roles,
  GHL OAuth (uses a private-integration token), call recording storage (only the provider URL is kept).
