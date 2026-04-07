# Plan 03 — Team RBAC (Role-Based Access Control)

**Priority:** 3 of 12.

**Goal:** Enforce `owner / admin / viewer` roles at the API level. Clerk provides role data
in the JWT. The backend reads the role from JWT claims and enforces it per endpoint.
Viewers can read everything but cannot mutate. Admins can mutate everything except billing
and org deletion. Owners have full access.

**Role definitions:**
| Role | Can do |
|---|---|
| `viewer` | GET on all resources. No POST/PATCH/DELETE. |
| `admin` | Full CRUD on agents, policies, api-keys, incidents, detector-config, alerts. Cannot access billing or delete org. |
| `owner` | Everything. Billing. Org deletion. |

**Architecture:** Add a `require_role(min_role)` FastAPI dependency. Inject it into route
handlers that need protection. API key auth (SDK) is always `admin` level — API keys are
used by agents, not humans, and need write access to ingest events.

**New files:**
- `backend/app/core/rbac.py` — role enum, `require_role()` dependency
- `backend/tests/test_rbac.py`
- `backend/tests/e2e/test_rbac_flow.py`

**Files to modify:**
- `backend/app/core/dependencies.py` — expose role from JWT claims
- `backend/app/api/v1/agents.py` — add role requirements
- `backend/app/api/v1/policies.py` — add role requirements
- `backend/app/api/v1/api_keys.py` — add role requirements
- `backend/app/api/v1/incidents.py` — add role requirements
- `backend/app/api/v1/billing.py` — owner only
- `backend/app/api/v1/alerts.py` — admin+
- `backend/app/api/v1/detector_config.py` — admin+

---

### Task 1: RBAC module

**File:** `backend/app/core/rbac.py`

```python
import enum
from fastapi import Depends, HTTPException, status
from app.core.dependencies import get_current_actor, Actor

class Role(enum.IntEnum):
    """Integer enum so comparisons work: Role.OWNER >= Role.ADMIN."""
    VIEWER = 0
    ADMIN = 1
    OWNER = 2

ROLE_MAP = {
    "org:viewer": Role.VIEWER,
    "org:admin": Role.ADMIN,
    "org:owner": Role.OWNER,
    # API key auth is always treated as ADMIN
    "api_key": Role.ADMIN,
}

def _actor_role(actor: Actor) -> Role:
    if actor.actor_type == "api_key":
        return Role.ADMIN
    # Clerk puts role in actor metadata — extend Actor dataclass to carry it
    role_str = actor.clerk_role or "org:viewer"
    return ROLE_MAP.get(role_str, Role.VIEWER)

def require_role(min_role: Role):
    """Dependency factory. Use as: Depends(require_role(Role.ADMIN))"""
    async def _check(actor_tuple = Depends(get_current_actor)):
        org, actor = actor_tuple
        if _actor_role(actor) < min_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {min_role.name.lower()} role",
                headers={"X-Required-Role": min_role.name.lower()},
            )
        return org, actor
    return _check
```

---

### Task 2: Expose role from Clerk JWT

**File:** `backend/app/core/dependencies.py`

Extend `Actor` dataclass:
```python
@dataclass
class Actor:
    actor_type: str
    actor_id: str | None = None
    label: str | None = None
    clerk_role: str | None = None  # NEW — e.g. "org:owner", "org:admin", "org:viewer"
```

In `_resolve_from_clerk_jwt()`, extract the role from the JWT payload:
```python
# Clerk puts org role in `org_role` claim when org context is present
clerk_role = payload.get("org_role")  # "org:owner" | "org:admin" | "org:viewer"
actor = Actor(actor_type="user", actor_id=user_id, label=label, clerk_role=clerk_role)
```

---

### Task 3: Apply role requirements to routes

Apply `Depends(require_role(Role.X))` to the following:

**`backend/app/api/v1/agents.py`**
- `GET /agents` → viewer+
- `POST /agents` → admin+
- `GET /agents/{id}` → viewer+
- `PATCH /agents/{id}` → admin+
- `DELETE /agents/{id}` → admin+

**`backend/app/api/v1/policies.py`**
- `GET /policies` → viewer+
- `POST /policies` → admin+
- `PUT /policies/{id}` → admin+
- `DELETE /policies/{id}` → admin+

**`backend/app/api/v1/api_keys.py`**
- `GET /api-keys` → admin+
- `POST /api-keys` → admin+
- `DELETE /api-keys/{id}` → owner only

**`backend/app/api/v1/incidents.py`**
- `GET /incidents` → viewer+
- `GET /incidents/{id}` → viewer+
- `PATCH /incidents/{id}` (status update) → admin+

**`backend/app/api/v1/billing.py`**
- All routes → owner only

**`backend/app/api/v1/alerts.py`**
- `GET /alerts` → viewer+
- `PUT /alerts` → admin+
- `POST /alerts/test` → admin+

**`backend/app/api/v1/detector_config.py`**
- `GET` → viewer+
- `PUT` → admin+

**`backend/app/api/v1/audit.py`**
- `GET /audit-log` → admin+ (viewers cannot see raw audit trail)

---

### Task 4: Unit tests

**File:** `backend/tests/test_rbac.py`

Test cases:
1. `require_role(Role.ADMIN)` with owner actor → passes
2. `require_role(Role.ADMIN)` with admin actor → passes
3. `require_role(Role.ADMIN)` with viewer actor → 403
4. `require_role(Role.OWNER)` with admin actor → 403
5. `require_role(Role.VIEWER)` with any actor → passes
6. API key actor → treated as ADMIN
7. No role claim in JWT → defaults to VIEWER

```bash
cd backend && uv run pytest tests/test_rbac.py -v
```

---

### Task 5: E2E test

**File:** `backend/tests/e2e/test_rbac_flow.py`

Test flow using real HTTP client with mock JWTs carrying different role claims:
1. Viewer JWT → `POST /agents` → 403
2. Viewer JWT → `GET /agents` → 200
3. Admin JWT → `POST /agents` → 201
4. Admin JWT → `POST /billing/checkout` → 403
5. Owner JWT → `POST /billing/checkout` → 200 (or 503 if Stripe not configured)
6. API key → `POST /events/ingest` → 202 (API keys are always admin)

---

### Task 6: Dashboard — role-aware UI

**Files:** `dashboard/src/lib/store.ts`, relevant page components

Store the user's role from the Clerk session in the global store. Use it to:
- Hide "Create", "Delete" buttons from viewers
- Show a "Read-only" badge in the header for viewer role
- Disable form inputs on PoliciesPage and SettingsPage for viewers

Clerk's `useOrganization()` hook provides `membership.role` — use that directly.

---

### Notes

- **Default to VIEWER on missing role claim.** Never default to a permissive role.
- **API keys are always ADMIN.** They are used by agents and need to ingest events.
  They should never have OWNER privileges.
- **Audit all role changes.** When a user's role is changed in Clerk, the Clerk webhook
  (`organization_membership.updated`) should write an audit log entry.
- **Don't block the Clerk webhook receiver with RBAC.** The `/webhooks/clerk` endpoint
  is authenticated via Svix signature, not Clerk JWT — it must remain open.
- **Demo mode (single org, no Clerk) is always OWNER.** The fallback org resolution
  in `dependencies.py` already handles this — extend it to set `clerk_role="org:owner"`.
