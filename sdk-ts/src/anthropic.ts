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

interface AnthropicStreamEvent {
  type: string;
  delta?: { type?: string; text?: string };
  message?: AnthropicMessageResponse;
  [key: string]: unknown;
}

interface AnthropicStream extends AsyncIterable<AnthropicStreamEvent> {
  [Symbol.asyncIterator](): AsyncIterator<AnthropicStreamEvent>;
}

interface AnthropicLike {
  messages: {
    create(
      body: AnthropicMessageRequest & { stream?: boolean },
      options?: unknown
    ): Promise<AnthropicMessageResponse> | AnthropicStream;
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

  async function preCheck(body: AnthropicMessageRequest) {
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
    return prompt;
  }

  const wrappedCreate = async (
    body: AnthropicMessageRequest & { stream?: boolean },
    opts?: unknown
  ): Promise<AnthropicMessageResponse | AnthropicStream> => {
    const prompt = await preCheck(body);

    if (body.stream) {
      const start = Date.now();
      const stream = originalCreate(body, opts) as unknown as AnthropicStream;
      return wrapAnthropicStream(stream, parry, {
        agentId,
        sessionId,
        prompt,
        model: body.model,
        start,
      });
    }

    const start = Date.now();
    const response = await (originalCreate(body, opts) as Promise<AnthropicMessageResponse>);
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

interface StreamIngestContext {
  agentId?: string;
  sessionId?: string;
  prompt?: string;
  model: string;
  start: number;
}

function wrapAnthropicStream(
  stream: AnthropicStream,
  parry: ParryClient,
  ctx: StreamIngestContext,
): AnthropicStream {
  const chunks: string[] = [];

  async function* iterate(): AsyncGenerator<AnthropicStreamEvent> {
    try {
      for await (const event of stream) {
        if (event.type === "content_block_delta" && event.delta?.text) {
          chunks.push(event.delta.text);
        }
        yield event;
      }
    } finally {
      const latencyMs = Date.now() - ctx.start;
      const responseText = chunks.length > 0 ? chunks.join("") : undefined;
      parry.ingestEvent({
        agentId: ctx.agentId,
        sessionId: ctx.sessionId,
        prompt: ctx.prompt,
        response: responseText,
        model: ctx.model,
        latencyMs,
      });
    }
  }

  const gen = iterate();
  return {
    [Symbol.asyncIterator]() {
      return gen;
    },
  };
}
