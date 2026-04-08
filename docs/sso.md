# Parry SSO (WorkOS SAML)

Parry layers WorkOS SAML SSO on top of its default Clerk auth for
enterprise customers who need to route users through their own
identity provider (Okta, Azure AD, Google Workspace, OneLogin, etc.).

**Clerk is still the source of truth** for session state. SSO is a
pre-authentication layer: the customer's IdP confirms the user, the
backend verifies the WorkOS assertion, and the dashboard bridges the
verified profile into a Clerk session. This keeps the number of
identity stores at exactly one.

## Who this is for

SSO is an opt-in enterprise feature. Default SaaS orgs keep using
Clerk's regular email/password or Google auth — nothing changes for
them. Flip on SSO only when a customer explicitly requires it (usually
as part of a security review or compliance mandate).

## Architecture

```
  browser                backend                 WorkOS                   IdP
     │                      │                       │                      │
     │  POST /sso/login     │                       │                      │
     ├─────────────────────▶│                       │                      │
     │  {authorization_url} │                       │                      │
     │◀─────────────────────│                       │                      │
     │                      │                       │                      │
     │                    (redirect)                │                      │
     ├──────────────────────┼──────────────────────▶│                      │
     │                      │                       │─────SAML AuthnReq───▶│
     │                      │                       │                      │
     │                      │                       │◀────SAML Assertion───│
     │                      │                       │                      │
     │  GET /sso/callback?code=...                   │                      │
     ├─────────────────────▶│                       │                      │
     │                      │   exchange_code       │                      │
     │                      ├──────────────────────▶│                      │
     │                      │   profile             │                      │
     │                      │◀──────────────────────│                      │
     │  CallbackResponse    │                       │                      │
     │  (bridged to Clerk)  │                       │                      │
     │◀─────────────────────│                       │                      │
```

The backend never touches the IdP directly. WorkOS handles the SAML
protocol details and gives Parry a normalised profile in exchange for
the authorization code.

## Config

Three backend settings drive the feature:

| Setting | Purpose |
| --- | --- |
| `WORKOS_API_KEY` | Workspace API key — backend-only |
| `WORKOS_CLIENT_ID` | Workspace client id — also used on the IdP side |
| `WORKOS_REDIRECT_URI` | Where WorkOS sends the browser after a successful assertion (usually `https://dashboard.parry.dev/auth/sso/callback`) |

Plus one per-org field in the database:

| Column | Purpose |
| --- | --- |
| `orgs.workos_organization_id` | The WorkOS Organization id that maps to this Parry org |

When the backend settings are empty, `sso_service.get_client()`
returns `None` and every `/sso` route responds **503 Service
Unavailable**. This is the intended posture for deployments that
don't sell enterprise tiers — no feature leak, no confusing errors.

## Enabling SSO for a customer (operator steps)

1. Create a new Organization in the WorkOS dashboard, tied to the
   customer's company name.
2. Run the signup flow with the customer so they link their IdP
   through WorkOS's AdminPortal (you can use `POST /sso/admin-portal`
   to generate the link for them — see **Admin Portal** below).
3. Copy the Organization id (`org_01XXXXXX`) out of WorkOS.
4. Set it on the Parry org row:

   ```sql
   UPDATE orgs
   SET workos_organization_id = 'org_01XXXXXX'
   WHERE id = '<parry_org_uuid>';
   ```

5. Test by opening `POST /api/v1/sso/login` with `org_slug` =
   `clerk_org_id`. The response's `authorization_url` should redirect
   to the IdP.

From the customer's point of view, step 2 is the only thing they
do — everything else is operator work.

## Routes

### `POST /api/v1/sso/login`
**Unauthenticated.** Starts a SAML flow. Accepts either `org_slug`
(the org's `clerk_org_id`) or an explicit `workos_organization_id`,
plus optional `state` and `redirect_uri` overrides. Returns
`{ "authorization_url": "..." }`. The dashboard redirects the browser
to that URL.

### `GET /api/v1/sso/callback?code=...`
**Unauthenticated.** Exchanges the WorkOS code for a profile, looks
up the matching Parry org by `workos_organization_id`, audit-logs
the login, and returns a `CallbackResponse` with `org_id`, `email`,
`display_name`, etc.

**Important: this route does not set a session cookie.** The
dashboard is responsible for bridging the profile into a Clerk
session (via Clerk's custom token flow). We deliberately keep
session minting in one place so there's no possibility of drift
between "auth provider" and "session issuer".

### `POST /api/v1/sso/admin-portal`
**Owner-gated.** Generates a WorkOS AdminPortal link so a customer
can configure their SAML metadata without Parry touching it. Pass
`return_url` so WorkOS sends them back to the settings page after
they're done. The request is audit-logged.

### `GET /api/v1/sso/status`
**Viewer+.** Returns `{ enabled, configured_on_backend,
workos_organization_id }` so the dashboard can render three distinct
states (unavailable / disabled / enabled).

## The integration gap

The callback handler returns a profile but **does not** mint a
session. That's intentional — Clerk stays the source of truth — but
it means the dashboard needs a small amount of glue code:

1. Receive the `CallbackResponse` from `/sso/callback`.
2. Hand the `workos_user_id` + `email` to Clerk via its custom
   authentication token flow (server-side):
   https://clerk.com/docs/custom-flows/custom-authentication
3. Clerk issues a session token.
4. Store the token in the browser the same way a normal Clerk login
   would.

The dashboard side of that glue is left as an operator TODO — SSO
customers are rare enough that the manual setup cost is
acceptable and doing it properly requires a Clerk app that allows
custom auth, which isn't enabled on every Parry deployment.

## Audit trail

Every SSO event is recorded in `audit_log` as a system-actor entry:

| action | when |
| --- | --- |
| `sso.login_completed` | After a successful `/sso/callback` exchange |
| `sso.admin_portal_generated` | When an owner requests an AdminPortal link |

These entries flow into the SOC 2 audit export alongside regular
dashboard mutations, so a compliance reviewer sees SSO activity in
the same timeline as agent creation or policy changes.
