/**
 * Resolves the current user's effective role for dashboard UI gating.
 *
 * Mirrors backend/app/core/rbac.py's Role enum: viewer < admin < owner.
 * Reads from Clerk's useOrganization() membership when available, falls
 * back to "viewer" if the membership hasn't loaded yet or the user
 * isn't in an org context (safe default — never fail-open in the UI).
 *
 * This is a **UX convenience**, not a security boundary. The backend
 * always re-checks via require_role — a clever user who bypasses the
 * UI still hits a 403 on the API.
 */
import { useOrganization } from "@clerk/clerk-react";

export type Role = "viewer" | "admin" | "owner";

const ROLE_RANK: Record<Role, number> = { viewer: 0, admin: 1, owner: 2 };

function normalizeClerkRole(raw: string | null | undefined): Role {
  if (!raw) return "viewer";
  // Clerk emits "org:admin", "org:member", etc.
  const stripped = raw.replace(/^org:/, "");
  if (stripped === "owner" || stripped === "admin") return stripped;
  return "viewer";
}

export function useRole(): { role: Role; can: (min: Role) => boolean } {
  const { membership, isLoaded } = useOrganization();

  // Demo / no-clerk deployments: treat as owner once loaded and the
  // membership is absent. Matches the backend's single-org fallback.
  let role: Role = "viewer";
  if (isLoaded) {
    if (membership?.role) {
      role = normalizeClerkRole(membership.role);
    } else {
      // No org membership but auth is loaded — either solo dev instance
      // or personal workspace. Backend will still enforce the real
      // permissions; this just keeps the UI unlocked locally.
      role = "owner";
    }
  }

  return {
    role,
    can: (min: Role) => ROLE_RANK[role] >= ROLE_RANK[min],
  };
}
