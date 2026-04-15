import { describe, it, expect } from "vitest";
import {
  canonicalManifest,
  manifestHash,
  normalizeText,
} from "./normalize.js";

function decode(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes);
}

describe("normalizeText", () => {
  it("returns empty string for non-strings", () => {
    expect(normalizeText(null)).toBe("");
    expect(normalizeText(undefined)).toBe("");
    expect(normalizeText(42)).toBe("");
    expect(normalizeText({})).toBe("");
  });

  it("strips whitespace", () => {
    expect(normalizeText("  hello  ")).toBe("hello");
  });

  it("NFC-normalizes combining forms", () => {
    // "é" as U+0065 U+0301 → U+00E9
    const decomposed = "e\u0301";
    const composed = "\u00e9";
    expect(normalizeText(decomposed)).toBe(composed);
    expect(normalizeText(decomposed).length).toBe(1);
  });
});

describe("canonicalManifest", () => {
  it("sorts tools by name", () => {
    const manifest = {
      tools: [
        { name: "zebra", description: "z", inputSchema: {} },
        { name: "alpha", description: "a", inputSchema: {} },
      ],
    };
    const out = decode(canonicalManifest(manifest));
    expect(out.indexOf("alpha")).toBeLessThan(out.indexOf("zebra"));
  });

  it("sorts schema keys recursively", () => {
    const manifest = {
      tools: [
        {
          name: "t",
          description: "",
          inputSchema: {
            type: "object",
            properties: {
              b: { type: "string" },
              a: { type: "string" },
            },
            required: ["b", "a"],
          },
        },
      ],
    };
    const out = decode(canonicalManifest(manifest));
    // "a":{... appears before "b":{...} in properties
    const aIdx = out.indexOf('"a":{"type":"string"}');
    const bIdx = out.indexOf('"b":{"type":"string"}');
    expect(aIdx).toBeGreaterThan(-1);
    expect(bIdx).toBeGreaterThan(-1);
    expect(aIdx).toBeLessThan(bIdx);
    // Top-level keys are sorted alphabetically: properties < required < type
    const propIdx = out.indexOf('"properties"');
    const reqIdx = out.indexOf('"required"');
    const typeIdx = out.indexOf('"type":"object"');
    expect(propIdx).toBeLessThan(reqIdx);
    expect(reqIdx).toBeLessThan(typeIdx);
  });

  it("preserves array order in required lists", () => {
    const manifest = {
      tools: [
        {
          name: "t",
          description: "",
          inputSchema: { required: ["b", "a"] },
        },
      ],
    };
    const out = decode(canonicalManifest(manifest));
    expect(out).toContain('"required":["b","a"]');
  });

  it("uses no whitespace in JSON output", () => {
    const manifest = {
      tools: [{ name: "t", description: "d", inputSchema: { a: 1 } }],
    };
    const out = decode(canonicalManifest(manifest));
    expect(out).not.toMatch(/: /);
    expect(out).not.toMatch(/, /);
  });

  it("skips non-object tools defensively", () => {
    const manifest = {
      tools: [
        null as unknown as { name: string },
        "bogus" as unknown as { name: string },
        { name: "t", description: "d", inputSchema: {} },
      ],
    };
    const out = decode(canonicalManifest(manifest));
    expect(out).toContain('"name":"t"');
    expect(out).not.toContain("bogus");
  });

  it("handles missing tools array", () => {
    const out = decode(canonicalManifest({}));
    expect(out).toBe('{"tools":[]}');
  });

  it("NFC-normalizes string fields", () => {
    const decomposed = "caf\u0065\u0301"; // "café" decomposed
    const manifest = {
      tools: [{ name: decomposed, description: decomposed, inputSchema: {} }],
    };
    const out = decode(canonicalManifest(manifest));
    expect(out).toContain("caf\u00e9");
    expect(out).not.toContain("\u0301");
  });

  it("produces byte-identical output regardless of input key order", () => {
    const a = {
      tools: [{ inputSchema: {}, description: "d", name: "t" }],
    };
    const b = {
      tools: [{ name: "t", description: "d", inputSchema: {} }],
    };
    expect(decode(canonicalManifest(a))).toBe(decode(canonicalManifest(b)));
  });
});

describe("manifestHash", () => {
  it("returns a 64-char sha256 hex digest", () => {
    const h = manifestHash({ tools: [] });
    expect(h).toMatch(/^[a-f0-9]{64}$/);
  });

  it("matches known fixture (parity with Python SDK)", () => {
    // This exact manifest, when hashed by
    // parry.mcp.normalize.manifest_hash in Python, must produce
    // the same digest. If this changes, the backend's stored hash
    // history would drift from SDK-computed hashes and all clients
    // would see trust downgrades.
    const manifest = {
      tools: [
        {
          name: "read_file",
          description: "Read a file",
          inputSchema: {
            type: "object",
            properties: { path: { type: "string" } },
            required: ["path"],
          },
        },
      ],
    };
    // Canonical bytes + hash verified against the Python SDK
    // (`parry.mcp.normalize`) — if these drift, backend-stored hashes
    // computed by Python agents and TS agents will stop matching.
    const expected =
      '{"tools":[{"description":"Read a file","inputSchema":{"properties":{"path":{"type":"string"}},"required":["path"],"type":"object"},"name":"read_file"}]}';
    expect(decode(canonicalManifest(manifest))).toBe(expected);
    expect(manifestHash(manifest)).toBe(
      "ef61816c6ca35e2b4490df16eb4a1483545a9afb3d404118ccdce27b2041a23c"
    );
  });

  it("changes when tool description changes", () => {
    const h1 = manifestHash({
      tools: [{ name: "t", description: "a", inputSchema: {} }],
    });
    const h2 = manifestHash({
      tools: [{ name: "t", description: "b", inputSchema: {} }],
    });
    expect(h1).not.toBe(h2);
  });

  it("stable across reorderings", () => {
    const h1 = manifestHash({
      tools: [
        { name: "a", description: "", inputSchema: {} },
        { name: "b", description: "", inputSchema: {} },
      ],
    });
    const h2 = manifestHash({
      tools: [
        { name: "b", description: "", inputSchema: {} },
        { name: "a", description: "", inputSchema: {} },
      ],
    });
    expect(h1).toBe(h2);
  });
});
