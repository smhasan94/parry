# Parry on-prem

Parry ships an on-prem variant for customers who can't send events
to the SaaS backend. Everything runs inside your network: the
detection engine, the dashboard, Postgres, Redis. No phone-home, no
metered-usage reporting, no S3 audit uploads.

## What "on-prem" means here

| Capability | SaaS | On-prem |
| --- | --- | --- |
| Detection engine (rule-based) | ✅ | ✅ |
| Detection engine (LLM fallback) | ✅ | ❌ (disabled — no outbound) |
| Dashboard + API | ✅ | ✅ |
| Session replay | ✅ | ✅ |
| Compliance report export (PDF) | ✅ | ✅ |
| Audit log export (CSV/JSON) | ✅ | ✅ (admin-triggered) |
| Monthly S3 audit export | ✅ | ❌ |
| Stripe billing | ✅ | ❌ (license file instead) |
| Metered usage reporting | ✅ | ❌ |
| PagerDuty / Opsgenie / Slack alerts | ✅ | ✅ (you configure the endpoints) |

The LLM fallback detector is the only Parry feature that loses
functionality in on-prem mode. The other four detectors
(prompt injection, jailbreak, tool misuse, privilege escalation) +
the anomaly detector + custom rules all run locally and carry the
full detection load.

## Licensing

On-prem uses a signed offline license file. The flow:

1. Parry issues you a `.license` file (JSON envelope with an
   Ed25519 signature) and a public key.
2. You drop the file on the host at `./license/parry.license`.
3. The backend verifies the signature at startup against the
   public key baked into the image. If verification fails
   (missing file, tampered payload, wrong key, empty public
   key config) the process **hard-fails** — it will not come
   up in a degraded state.

The license payload carries:

```json
{
  "schema_version": "1.0",
  "license_id": "lic_abc123",
  "customer_name": "Acme Corp",
  "issued_at": "2026-01-01T00:00:00+00:00",
  "expires_at": "2027-01-01T00:00:00+00:00",
  "max_agents": 100,
  "max_events_per_month": 5000000,
  "features": ["custom_rules", "compliance_export"]
}
```

Expired licenses log a warning but don't immediately lock you out —
you've got a short grace period while renewal is in flight. Contact
us before expiry to get a new file.

## First-time install

```bash
# 1. Drop the license into place
mkdir -p ./license
cp /path/to/your.license ./license/parry.license
chmod 644 ./license/parry.license

# 2. Set the baked-in public key (Parry ships this alongside the license)
export LICENSE_PUBLIC_KEY_PEM="$(cat /path/to/parry_license_ed25519.pub)"

# 3. Build the on-prem image
docker compose -f docker-compose.onprem.yml build

# 4. Start everything
docker compose -f docker-compose.onprem.yml up -d

# 5. Check startup logs — look for the license.loaded event
docker compose -f docker-compose.onprem.yml logs backend | grep license
```

The dashboard is available at `http://<host>:5173`, the API at
`http://<host>:8000`. Run database migrations with:

```bash
docker compose -f docker-compose.onprem.yml exec backend \
  uv run alembic upgrade head
```

## Verifying the air-gap

Everything Parry does should be visible to a packet capture on the
host. In on-prem mode the backend should make **zero** outbound
connections beyond the database + redis containers.

Quick sanity checks:

```bash
# 1. Confirm on_prem mode is active
docker compose -f docker-compose.onprem.yml exec backend \
  uv run python -c "from app.core import on_prem; print('on_prem:', on_prem.is_on_prem())"

# 2. Confirm the license was loaded
docker compose -f docker-compose.onprem.yml exec backend \
  uv run python -c "from app.core import on_prem; l = on_prem.get_license(); print(l.customer_name, l.license_id, l.expires_at)"

# 3. Confirm the metered-usage and S3 export tasks are no-ops
docker compose -f docker-compose.onprem.yml logs worker | \
  grep -E "metered.skipped_on_prem|audit.export_skipped_on_prem"
```

The Celery Beat schedule still runs those tasks — they immediately
return `{"reported": 0, "skipped": 0, "errored": 0}` and log their
skip reason. No network calls happen.

## What about LLM fallback?

The LLM fallback detector normally calls Anthropic's API to
adjudicate ambiguous rule-based results (confidence in the 0.4–0.7
band). In on-prem mode that path is disabled — ambiguous detections
fall through to whatever verdict the rule-based detectors reach on
their own.

In practice this means slightly more false positives and false
negatives at the margin. If the fallback matters to your use case,
the alternative is to:

1. Run a local LLM server (vLLM, TGI, etc.) inside the same
   network.
2. Point `ANTHROPIC_BASE_URL` at it (the Anthropic SDK honours
   this variable).
3. Flip the `on_prem_mode` flag off and set
   `ANTHROPIC_API_KEY` to whatever your local server expects.

You're still air-gapped from the public internet, but you give up
the "no outbound calls at all" guarantee. Most customers start
without it.

## Renewals

Licenses expire. Parry issues a new file before the old one runs
out. To roll it in:

```bash
cp /path/to/new.license ./license/parry.license
docker compose -f docker-compose.onprem.yml restart backend worker
```

No downtime for the database or dashboard. Detection stays live
through the restart.

## Upgrades

On-prem releases follow the same version numbers as SaaS. Upgrade
procedure:

```bash
git pull  # or fetch a new release tarball
docker compose -f docker-compose.onprem.yml build --pull
docker compose -f docker-compose.onprem.yml up -d
docker compose -f docker-compose.onprem.yml exec backend \
  uv run alembic upgrade head
```

Any migration that would have run in SaaS runs here too. See
[docs/runbook.md](./runbook.md) for rollback procedure.

## Limits enforcement

On-prem replaces the SaaS plan table with the license file. The
`plan_service` enforcement paths (agent creation, event ingest,
custom rules, compliance export) all read from the license:

| License field | Enforced at |
| --- | --- |
| `max_agents` | `POST /api/v1/agents` |
| `max_events_per_month` | `POST /api/v1/events/ingest` (rolling 30d) |
| `features["custom_rules"]` | `POST /api/v1/custom-rules` |
| `features["compliance_export"]` | `GET /api/v1/reports/compliance` |

A limit breach returns HTTP 402 with `X-Upgrade-Required: true`,
same as SaaS — the dashboard's upgrade modal surfaces the message.
"Upgrade" in this context means "get a new license file from
Parry", not "pay Stripe".
