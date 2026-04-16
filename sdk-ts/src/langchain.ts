/**
 * LangChain.js callback handler that intercepts LLM calls for Parry.
 *
 * Usage:
 * ```ts
 * import { ParryClient } from "@parry/sdk";
 * import { ParryCallbackHandler } from "@parry/sdk";
 * import { ChatOpenAI } from "@langchain/openai";
 *
 * const parry = new ParryClient({ apiKey: "sk-parry-..." });
 * const handler = new ParryCallbackHandler(parry, { agentId: "my-agent" });
 *
 * const model = new ChatOpenAI({ model: "gpt-4o" });
 * const result = await model.invoke("Hello", { callbacks: [handler] });
 * ```
 *
 * The handler is compatible with LangChain.js's `CallbackHandlerMethods`
 * interface — no `@langchain/core` peer dependency required.
 */

import type { ParryClient } from "./client.js";

interface Serialized {
  id?: string[];
  kwargs?: Record<string, unknown>;
  [key: string]: unknown;
}

interface BaseMessageLike {
  content: string | Array<{ type: string; text?: string; [k: string]: unknown }>;
  [key: string]: unknown;
}

interface GenerationLike {
  text: string;
  message?: {
    tool_calls?: Array<{ name: string; args?: unknown }>;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

interface LLMResultLike {
  generations: GenerationLike[][];
  llm_output?: Record<string, unknown> | null;
  [key: string]: unknown;
}

interface RunState {
  prompt: string | undefined;
  model: string | undefined;
  startTime: number;
  toolCalls: Array<Record<string, unknown>>;
}

export interface ParryCallbackHandlerOptions {
  agentId?: string;
  sessionId?: string;
}

export class ParryCallbackHandler {
  name = "ParryCallbackHandler";

  private readonly parry: ParryClient;
  private readonly agentId: string | undefined;
  private readonly sessionId: string | undefined;
  private readonly runs = new Map<string, RunState>();

  constructor(parry: ParryClient, options?: ParryCallbackHandlerOptions) {
    this.parry = parry;
    this.agentId = options?.agentId ?? parry.defaultAgentId ?? undefined;
    this.sessionId = options?.sessionId;
  }

  handleChatModelStart(
    serialized: Serialized,
    messages: BaseMessageLike[][],
    runId: string,
  ): void {
    let prompt: string | undefined;
    if (messages?.[0]?.length) {
      const lastMsg = messages[0][messages[0].length - 1];
      if (typeof lastMsg.content === "string") {
        prompt = lastMsg.content;
      } else if (Array.isArray(lastMsg.content)) {
        const texts = lastMsg.content
          .filter((b) => b.type === "text" && typeof b.text === "string")
          .map((b) => b.text!);
        prompt = texts.length > 0 ? texts.join(" ") : undefined;
      }
    }

    const model = extractModel(serialized);

    this.runs.set(runId, {
      prompt,
      model,
      startTime: Date.now(),
      toolCalls: [],
    });
  }

  handleLLMStart(
    serialized: Serialized,
    prompts: string[],
    runId: string,
  ): void {
    this.runs.set(runId, {
      prompt: prompts[0] ?? undefined,
      model: extractModel(serialized),
      startTime: Date.now(),
      toolCalls: [],
    });
  }

  handleLLMEnd(output: LLMResultLike, runId: string): void {
    const run = this.runs.get(runId);
    this.runs.delete(runId);
    if (!run) return;

    const latencyMs = Date.now() - run.startTime;

    let responseText: string | undefined;
    if (output.generations?.[0]?.[0]) {
      responseText = output.generations[0][0].text || undefined;
    }

    let tokenCount: number | undefined;
    if (output.llm_output) {
      const usage = output.llm_output.token_usage as
        | Record<string, number>
        | undefined;
      tokenCount = usage?.total_tokens;
    }

    let toolCalls: Array<Record<string, unknown>> | undefined;
    const gen = output.generations?.[0]?.[0];
    if (gen?.message?.tool_calls?.length) {
      toolCalls = gen.message.tool_calls.map((tc) => ({
        name: tc.name,
        arguments: tc.args ?? {},
      }));
    }

    if (!toolCalls && run.toolCalls.length > 0) {
      toolCalls = run.toolCalls;
    }

    this.parry.ingestEvent({
      agentId: this.agentId,
      sessionId: this.sessionId,
      prompt: run.prompt,
      response: responseText,
      model: run.model,
      toolCalls,
      latencyMs,
      tokenCount,
    });
  }

  handleLLMError(_error: unknown, runId: string): void {
    this.runs.delete(runId);
  }

  handleToolStart(
    serialized: Serialized,
    _input: string,
    runId: string,
    parentRunId?: string,
  ): void {
    if (parentRunId && this.runs.has(parentRunId)) {
      const toolName =
        (serialized as Record<string, unknown>).name ??
        serialized.id?.[serialized.id.length - 1] ??
        "tool";
      this.runs.get(parentRunId)!.toolCalls.push({ name: toolName });
    }
  }

  handleToolEnd(
    _output: unknown,
    _runId: string,
    _parentRunId?: string,
  ): void {
    // no-op — tool output captured by the LLM's response
  }
}

function extractModel(serialized: Serialized): string | undefined {
  return (
    (serialized.kwargs?.model_name as string) ??
    (serialized.kwargs?.model as string) ??
    serialized.id?.[serialized.id.length - 1] ??
    undefined
  );
}
