/**
 * Canonical MCP manifest normalization — mirrors the Python SDK
 * (`parry.mcp.normalize`) and the backend (`app.detection.mcp_normalize`).
 *
 * Must produce byte-identical output to the Python implementation so
 * the hash matches what the backend stores. The pinned behaviour:
 *
 *   - NFC-normalize all strings, then .strip()
 *   - Recursively sort dict keys (depth-first)
 *   - Sort tools by name
 *   - JSON-encode with sorted keys and no whitespace separators
 *   - SHA-256 hex of the UTF-8 bytes
 */

import { createHash } from "node:crypto";

export interface MCPTool {
  name?: string;
  description?: string;
  inputSchema?: unknown;
  [key: string]: unknown;
}

export interface MCPManifest {
  tools?: MCPTool[];
  [key: string]: unknown;
}

export function normalizeText(text: unknown): string {
  if (typeof text !== "string") return "";
  return text.normalize("NFC").trim();
}

function canonicalSchema(schema: unknown): unknown {
  if (Array.isArray(schema)) {
    return schema.map(canonicalSchema);
  }
  if (schema !== null && typeof schema === "object") {
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(schema).sort()) {
      sorted[key] = canonicalSchema((schema as Record<string, unknown>)[key]);
    }
    return sorted;
  }
  if (typeof schema === "string") {
    return normalizeText(schema);
  }
  return schema;
}

/**
 * Serialize an object with sorted keys (recursive) and `(",", ":")` separators,
 * matching Python's `json.dumps(obj, sort_keys=True, separators=(",", ":"))`.
 */
function canonicalJSON(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "number") {
    // Python and JS agree on finite numbers via this path; NaN/Inf aren't
    // emitted by our inputs, so we don't need Python's allow_nan handling.
    return Number.isFinite(value) ? JSON.stringify(value) : "null";
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJSON).join(",") + "]";
  }
  if (typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    const parts = keys.map(
      (k) => JSON.stringify(k) + ":" + canonicalJSON((value as Record<string, unknown>)[k])
    );
    return "{" + parts.join(",") + "}";
  }
  // Functions / undefined / symbols — stringify drops these in Python too.
  return "null";
}

export function canonicalManifest(manifest: MCPManifest): Uint8Array {
  const toolsIn = manifest.tools ?? [];
  const toolsOut: Array<Record<string, unknown>> = [];
  for (const t of toolsIn) {
    if (t === null || typeof t !== "object" || Array.isArray(t)) continue;
    toolsOut.push({
      name: normalizeText(t.name ?? ""),
      description: normalizeText(t.description ?? ""),
      inputSchema: canonicalSchema(t.inputSchema ?? {}),
    });
  }
  toolsOut.sort((a, b) => {
    const an = a.name as string;
    const bn = b.name as string;
    return an < bn ? -1 : an > bn ? 1 : 0;
  });
  const canonical = { tools: toolsOut };
  return new TextEncoder().encode(canonicalJSON(canonical));
}

export function manifestHash(manifest: MCPManifest): string {
  const hash = createHash("sha256");
  hash.update(Buffer.from(canonicalManifest(manifest)));
  return hash.digest("hex");
}
