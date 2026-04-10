/**
 * Vercel AI SDK integration — wraps generateText/streamText calls
 * with Parry security checks.
 *
 * The Vercel AI SDK (`ai` package) is the dominant way Next.js
 * developers interact with LLMs. This wrapper provides a middleware
 * function that intercepts calls at the provider level.
 *
 * Usage with generateText:
 * ```ts
 * import { generateText } from "ai";
 * import { openai } from "@ai-sdk/openai";
 * import { ParryClient } from "@parry/sdk";
 * import { parryWrap } from "@parry/sdk/vercel-ai";
 *
 * const parry = new ParryClient({ apiKey: "sk-parry-..." });
 *
 * const result = await parryWrap(parry, () =>
 *   generateText({
 *     model: openai("gpt-4o"),
 *     prompt: "Hello!",
 *   })
 * );
 * ```
 *
 * Usage with streamText:
 * ```ts
 * const result = await parryWrap(parry, () =>
 *   streamText({
 *     model: openai("gpt-4o"),
 *     prompt: "Hello!",
 *   }),
 *   { agentId: "my-agent", prompt: "Hello!" }
 * );
 * ```
 */

import type { ParryClient } from "./client.js";

export interface ParryWrapOptions {
  /** Agent ID for this call (overrides client default) */
  agentId?: string;
  /** Session ID for grouping calls */
  sessionId?: string;
  /** The prompt being sent (extracted automatically from generateText, but must be provided for streamText) */
  prompt?: string;
  /** The model identifier (e.g., "gpt-4o") */
  model?: string;
  /** Tool names being invoked */
  toolNames?: string[];
}

/**
 * Wrap a Vercel AI SDK call with Parry pre-call check and post-call ingest.
 *
 * Works with both `generateText` and `streamText`. For `generateText`,
 * the response text is automatically captured. For `streamText`, only
 * the pre-call check runs (response capture requires consuming the stream).
 *
 * @param parry - ParryClient instance
 * @param fn - The Vercel AI SDK call to wrap (e.g., `() => generateText(...)`)
 * @param options - Optional metadata for the call
 * @returns The result of the wrapped call
 * @throws ParryBlockedError if the pre-call check blocks the call
 */
export async function parryWrap<T>(
  parry: ParryClient,
  fn: () => Promise<T>,
  options?: ParryWrapOptions,
): Promise<T> {
  const agentId = options?.agentId;
  const sessionId = options?.sessionId;
  const prompt = options?.prompt;
  const model = options?.model;

  // Pre-call check — throws ParryBlockedError if blocked
  await parry.checkBeforeCall({
    agentId,
    sessionId,
    prompt,
    model,
    toolCalls: options?.toolNames?.map((name) => ({ name })),
  });

  // Execute the actual call with timing
  const start = Date.now();
  const result = await fn();
  const latencyMs = Date.now() - start;

  // Post-call ingest — try to extract response from result
  const extracted = extractFromResult(result);

  parry.ingestEvent({
    agentId,
    sessionId,
    prompt,
    response: extracted.text,
    model: extracted.model ?? model,
    toolCalls: extracted.toolCalls,
    latencyMs,
    tokenCount: extracted.totalTokens,
  });

  return result;
}

/**
 * Create a reusable wrapper bound to a ParryClient and default options.
 *
 * ```ts
 * const withParry = createParryWrapper(parryClient, { agentId: "my-agent" });
 *
 * const result = await withParry(() => generateText({ ... }));
 * ```
 */
export function createParryWrapper(
  parry: ParryClient,
  defaultOptions?: ParryWrapOptions,
) {
  return <T>(fn: () => Promise<T>, options?: ParryWrapOptions): Promise<T> => {
    return parryWrap(parry, fn, { ...defaultOptions, ...options });
  };
}

// ── Result extraction ──────────────────────────────────────────

interface ExtractedResult {
  text?: string;
  model?: string;
  toolCalls?: Array<Record<string, unknown>>;
  totalTokens?: number;
}

function extractFromResult(result: unknown): ExtractedResult {
  if (result == null || typeof result !== "object") {
    return {};
  }

  const r = result as Record<string, unknown>;
  const extracted: ExtractedResult = {};

  // generateText returns { text, toolCalls, usage, ... }
  if (typeof r.text === "string") {
    extracted.text = r.text;
  }

  // Tool calls
  if (Array.isArray(r.toolCalls)) {
    extracted.toolCalls = (r.toolCalls as Array<Record<string, unknown>>).map(
      (tc) => ({
        name: tc.toolName ?? tc.name,
        arguments: tc.args ?? tc.arguments,
      }),
    );
  }

  // Usage
  if (r.usage && typeof r.usage === "object") {
    const usage = r.usage as Record<string, unknown>;
    const prompt = (usage.promptTokens as number) ?? 0;
    const completion = (usage.completionTokens as number) ?? 0;
    if (prompt + completion > 0) {
      extracted.totalTokens = prompt + completion;
    }
  }

  // Model info (some results include this)
  if (typeof r.modelId === "string") {
    extracted.model = r.modelId;
  }

  return extracted;
}
