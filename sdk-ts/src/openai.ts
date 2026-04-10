/**
 * OpenAI wrapper — intercepts chat.completions.create with Parry
 * pre-call check and post-call event ingest.
 *
 * Usage:
 * ```ts
 * import OpenAI from "openai";
 * import { ParryClient, parryOpenAI } from "@parry/sdk";
 *
 * const parry = new ParryClient({ apiKey: "sk-parry-..." });
 * const openai = parryOpenAI(new OpenAI(), parry);
 *
 * // Use openai as normal — Parry intercepts automatically
 * const response = await openai.chat.completions.create({
 *   model: "gpt-4o",
 *   messages: [{ role: "user", content: "Hello" }],
 * });
 * ```
 */

import type { ParryClient } from "./client.js";

interface ChatMessage {
  role: string;
  content: string | null;
}

interface ChatCompletionRequest {
  model: string;
  messages: ChatMessage[];
  tools?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

interface ChatCompletionChoice {
  message: {
    role: string;
    content: string | null;
    tool_calls?: Array<{
      id: string;
      type: string;
      function: { name: string; arguments: string };
    }>;
  };
  [key: string]: unknown;
}

interface ChatCompletionResponse {
  id: string;
  choices: ChatCompletionChoice[];
  model: string;
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  [key: string]: unknown;
}

interface OpenAILike {
  chat: {
    completions: {
      create(body: ChatCompletionRequest, options?: unknown): Promise<ChatCompletionResponse>;
    };
  };
}

/**
 * Wrap an OpenAI client instance with Parry security checks.
 *
 * Returns a proxy that intercepts `chat.completions.create` with:
 * 1. Pre-call proxy check (blocks if detection triggers)
 * 2. Post-call event ingest (fire-and-forget telemetry)
 *
 * All other methods pass through unchanged.
 */
export function parryOpenAI<T extends OpenAILike>(
  openai: T,
  parry: ParryClient,
  options?: { agentId?: string; sessionId?: string }
): T {
  const agentId = options?.agentId ?? parry.defaultAgentId ?? undefined;
  const sessionId = options?.sessionId;

  const originalCreate = openai.chat.completions.create.bind(
    openai.chat.completions
  );

  const wrappedCreate = async (
    body: ChatCompletionRequest,
    opts?: unknown
  ): Promise<ChatCompletionResponse> => {
    const lastUserMessage = body.messages
      .filter((m) => m.role === "user")
      .pop();
    const prompt = lastUserMessage?.content ?? undefined;

    // Pre-call check — throws ParryBlockedError if blocked
    await parry.checkBeforeCall({
      agentId,
      sessionId,
      prompt,
      model: body.model,
      toolCalls: body.tools?.map((t) => ({ name: (t as Record<string, unknown>).function ? ((t as Record<string, unknown>).function as Record<string, unknown>).name : t.name })) ?? [],
    });

    // Execute the actual LLM call
    const start = Date.now();
    const response = await originalCreate(body, opts);
    const latencyMs = Date.now() - start;

    // Extract response content
    const choice = response.choices?.[0];
    const responseText = choice?.message?.content ?? undefined;
    const toolCalls = choice?.message?.tool_calls?.map((tc) => ({
      name: tc.function.name,
      arguments: tc.function.arguments,
    }));

    // Post-call event ingest (fire-and-forget)
    parry.ingestEvent({
      agentId,
      sessionId,
      prompt,
      response: responseText,
      model: response.model,
      toolCalls,
      latencyMs,
      tokenCount: response.usage?.total_tokens,
    });

    return response;
  };

  // Return a proxy that intercepts chat.completions.create
  return new Proxy(openai, {
    get(target, prop) {
      if (prop === "chat") {
        return new Proxy(target.chat, {
          get(chatTarget, chatProp) {
            if (chatProp === "completions") {
              return new Proxy(chatTarget.completions, {
                get(compTarget, compProp) {
                  if (compProp === "create") {
                    return wrappedCreate;
                  }
                  return (compTarget as Record<string | symbol, unknown>)[compProp];
                },
              });
            }
            return (chatTarget as Record<string | symbol, unknown>)[chatProp];
          },
        });
      }
      return (target as Record<string | symbol, unknown>)[prop];
    },
  }) as T;
}
