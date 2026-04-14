/**
 * Anthropic wrapper — intercepts messages.create with Parry pre-call
 * check, post-call response scan, and event ingest.
 *
 * Usage:
 * ```ts
 * import Anthropic from "@anthropic-ai/sdk";
 * import { ParryClient, parryAnthropic } from "@parry/sdk";
 *
 * const parry = new ParryClient({ apiKey: "sk-parry-..." });
 * const anthropic = parryAnthropic(new Anthropic(), parry);
 *
 * const response = await anthropic.messages.create({
 *   model: "claude-sonnet-4-6",
 *   max_tokens: 1024,
 *   messages: [{ role: "user", content: "Hello" }],
 * });
 * ```
 */

import type { ParryClient } from "./client.js";

interface AnthropicTextBlock {
  type: "text";
  text: string;
}

interface AnthropicToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: unknown;
}

type AnthropicContentBlock = AnthropicTextBlock | AnthropicToolUseBlock | { type: string; [k: string]: unknown };

interface AnthropicMessage {
  role: string;
  content: string | AnthropicContentBlock[];
}

interface AnthropicMessageRequest {
  model: string;
  messages: AnthropicMessage[];
  max_tokens: number;
  tools?: Array<Record<string, unknown>>;
  system?: string | AnthropicContentBlock[];
  [key: string]: unknown;
}

interface AnthropicMessageResponse {
  id: string;
  model: string;
  content: AnthropicContentBlock[];
  usage?: { input_tokens: number; output_tokens: number };
  [key: string]: unknown;
}

interface AnthropicLike {
  messages: {
    create(
      body: AnthropicMessageRequest,
      options?: unknown
    ): Promise<AnthropicMessageResponse>;
  };
}

function extractPromptFromMessages(messages: AnthropicMessage[]): string | undefined {
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  if (!lastUser) return undefined;
  if (typeof lastUser.content === "string") return lastUser.content;
  for (const block of lastUser.content) {
    if (block.type === "text" && typeof (block as AnthropicTextBlock).text === "string") {
      return (block as AnthropicTextBlock).text;
    }
  }
  return undefined;
}

function extractResponseText(content: AnthropicContentBlock[]): string | undefined {
  const parts: string[] = [];
  for (const block of content ?? []) {
    if (block.type === "text" && typeof (block as AnthropicTextBlock).text === "string") {
      parts.push((block as AnthropicTextBlock).text);
    }
  }
  return parts.length > 0 ? parts.join("") : undefined;
}

function extractToolCalls(
  content: AnthropicContentBlock[]
): Array<Record<string, unknown>> | undefined {
  const calls: Array<Record<string, unknown>> = [];
  for (const block of content ?? []) {
    if (block.type === "tool_use") {
      const tu = block as AnthropicToolUseBlock;
      calls.push({ name: tu.name, arguments: JSON.stringify(tu.input ?? {}) });
    }
  }
  return calls.length > 0 ? calls : undefined;
}

/**
 * Wrap an Anthropic client instance with Parry security checks.
 *
 * Returns a proxy that intercepts `messages.create` with:
 * 1. Pre-call proxy check (throws ParryBlockedError on detection)
 * 2. Post-call response scan (throws on exfiltration / applies redaction)
 * 3. Post-call event ingest (fire-and-forget telemetry)
 *
 * All other methods pass through unchanged.
 */
export function parryAnthropic<T extends AnthropicLike>(
  anthropic: T,
  parry: ParryClient,
  options?: { agentId?: string; sessionId?: string }
): T {
  const agentId = options?.agentId ?? parry.defaultAgentId ?? undefined;
  const sessionId = options?.sessionId;

  const originalCreate = anthropic.messages.create.bind(anthropic.messages);

  const wrappedCreate = async (
    body: AnthropicMessageRequest,
    opts?: unknown
  ): Promise<AnthropicMessageResponse> => {
    const prompt = extractPromptFromMessages(body.messages);

    await parry.checkBeforeCall({
      agentId,
      sessionId,
      prompt,
      model: body.model,
      toolCalls:
        body.tools?.map((t) => ({
          name: (t as Record<string, unknown>).name,
        })) ?? [],
    });

    const start = Date.now();
    const response = await originalCreate(body, opts);
    const latencyMs = Date.now() - start;

    let responseText = extractResponseText(response.content);
    const toolCalls = extractToolCalls(response.content);

    if (responseText) {
      const scanned = await parry.scanResponse({
        response: responseText,
        agentId,
        sessionId,
      });
      if (scanned !== responseText) {
        responseText = scanned;
        // Replace the first text block with the redacted text so callers
        // that read response.content see the scrubbed version.
        const firstText = response.content?.find(
          (b) => b.type === "text"
        ) as AnthropicTextBlock | undefined;
        if (firstText) firstText.text = scanned;
      }
    }

    const tokenCount =
      (response.usage?.input_tokens ?? 0) + (response.usage?.output_tokens ?? 0) || undefined;

    parry.ingestEvent({
      agentId,
      sessionId,
      prompt,
      response: responseText,
      model: response.model,
      toolCalls,
      latencyMs,
      tokenCount,
    });

    return response;
  };

  return new Proxy(anthropic, {
    get(target, prop) {
      if (prop === "messages") {
        return new Proxy(target.messages, {
          get(msgTarget, msgProp) {
            if (msgProp === "create") return wrappedCreate;
            return (msgTarget as Record<string | symbol, unknown>)[msgProp];
          },
        });
      }
      return (target as Record<string | symbol, unknown>)[prop];
    },
  }) as T;
}
