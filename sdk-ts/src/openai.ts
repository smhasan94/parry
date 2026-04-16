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

interface ChatCompletionChunk {
  id: string;
  choices: Array<{
    delta: {
      role?: string;
      content?: string | null;
      tool_calls?: Array<{
        index: number;
        id?: string;
        type?: string;
        function?: { name?: string; arguments?: string };
      }>;
    };
    [key: string]: unknown;
  }>;
  model: string;
  [key: string]: unknown;
}

interface OpenAIStream extends AsyncIterable<ChatCompletionChunk> {
  [Symbol.asyncIterator](): AsyncIterator<ChatCompletionChunk>;
}

interface OpenAILike {
  chat: {
    completions: {
      create(
        body: ChatCompletionRequest & { stream?: boolean },
        options?: unknown,
      ): Promise<ChatCompletionResponse> | OpenAIStream;
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

  function extractPrompt(body: ChatCompletionRequest): string | undefined {
    const lastUserMessage = body.messages.filter((m) => m.role === "user").pop();
    return lastUserMessage?.content ?? undefined;
  }

  function extractToolDefs(body: ChatCompletionRequest) {
    return (
      body.tools?.map((t) => ({
        name: (t as Record<string, unknown>).function
          ? ((t as Record<string, unknown>).function as Record<string, unknown>).name
          : t.name,
      })) ?? []
    );
  }

  const wrappedCreate = async (
    body: ChatCompletionRequest & { stream?: boolean },
    opts?: unknown
  ): Promise<ChatCompletionResponse | OpenAIStream> => {
    const prompt = extractPrompt(body);

    await parry.checkBeforeCall({
      agentId,
      sessionId,
      prompt,
      model: body.model,
      toolCalls: extractToolDefs(body),
    });

    if (body.stream) {
      const start = Date.now();
      const stream = originalCreate(body, opts) as unknown as OpenAIStream;
      return wrapOpenAIStream(stream, parry, {
        agentId,
        sessionId,
        prompt,
        model: body.model,
        start,
      });
    }

    const start = Date.now();
    const response = await (originalCreate(body, opts) as Promise<ChatCompletionResponse>);
    const latencyMs = Date.now() - start;

    const choice = response.choices?.[0];
    let responseText = choice?.message?.content ?? undefined;
    const toolCalls = choice?.message?.tool_calls?.map((tc) => ({
      name: tc.function.name,
      arguments: tc.function.arguments,
    }));

    if (responseText) {
      const scanned = await parry.scanResponse({
        response: responseText,
        agentId,
        sessionId,
      });
      if (scanned !== responseText) {
        responseText = scanned;
        if (choice?.message) choice.message.content = scanned;
      }
    }

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

interface StreamIngestContext {
  agentId?: string;
  sessionId?: string;
  prompt?: string;
  model: string;
  start: number;
}

function wrapOpenAIStream(
  stream: OpenAIStream,
  parry: ParryClient,
  ctx: StreamIngestContext,
): OpenAIStream {
  const chunks: string[] = [];

  async function* iterate(): AsyncGenerator<ChatCompletionChunk> {
    try {
      for await (const chunk of stream) {
        const delta = chunk.choices?.[0]?.delta;
        if (delta?.content) {
          chunks.push(delta.content);
        }
        yield chunk;
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
