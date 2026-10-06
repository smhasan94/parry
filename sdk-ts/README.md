# @parry/sdk

Parry SDK for TypeScript/JavaScript — AI Agent Runtime Security.

Sits between your AI agents and the LLMs/tools they call. Detects prompt injection,
tool misuse, sensitive-data exfiltration, and anomalous behavior in real time.

This is the TypeScript counterpart to the Python [`parry`](https://pypi.org/project/parry/) package.

## Install

```bash
npm install @parry/sdk
```

Peer dependencies are optional — install only the ones you use:

```bash
npm install openai                        # for parryOpenAI
npm install @anthropic-ai/sdk             # for parryAnthropic
npm install @modelcontextprotocol/sdk     # for SentinelMCPClient
```

## Quickstart

```ts
import { ParryClient } from "@parry/sdk";

const parry = new ParryClient({
  apiKey: process.env.PARRY_API_KEY!,
  agentId: "agent_support_bot",
});

await parry.checkBeforeCall({ prompt: userInput });
// ...call the LLM...
await parry.ingestEvent({ prompt: userInput, response, latencyMs: 420 });
```

If the call is blocked, `checkBeforeCall` throws `ParryBlockedError` (or
`ParryPermissionDeniedError` for tool permission boundaries). All network/timeout
errors are swallowed — Parry **fails open** so it can never break your app.

## Wrappers

### OpenAI

```ts
import OpenAI from "openai";
import { ParryClient, parryOpenAI } from "@parry/sdk";

const parry = new ParryClient({
  apiKey: process.env.PARRY_API_KEY!,
  agentId: "agent_123",
});
const openai = parryOpenAI(new OpenAI(), parry);

const res = await openai.chat.completions.create({
  model: "gpt-4o",
  messages: [{ role: "user", content: "hello" }],
});
```

### Anthropic

```ts
import Anthropic from "@anthropic-ai/sdk";
import { ParryClient, parryAnthropic } from "@parry/sdk";

const parry = new ParryClient({
  apiKey: process.env.PARRY_API_KEY!,
  agentId: "agent_123",
});
const anthropic = parryAnthropic(new Anthropic(), parry);

const msg = await anthropic.messages.create({
  model: "claude-sonnet-4-6",
  max_tokens: 1024,
  messages: [{ role: "user", content: "hello" }],
});
```

The wrappers handle `checkBeforeCall` before the request, `scanResponse` after,
and `ingestEvent` in the background. Text and `tool_use` blocks are both scanned.

### Vercel AI SDK

```ts
import { generateText } from "ai";
import { ParryClient, parryWrap } from "@parry/sdk";

const parry = new ParryClient({
  apiKey: process.env.PARRY_API_KEY!,
  agentId: "agent_123",
});

const result = await parryWrap(
  parry,
  () => generateText({ model, prompt: userInput }),
  { prompt: userInput },
);
```

## MCP security (SentinelMCPClient)

Wraps an MCP client session with Parry's manifest-drift detection and
prompt-injection scanning over tool descriptions and input schemas.

```ts
import { SentinelMCPClient, MCPBlockedError } from "@parry/sdk";

await using mcp = await SentinelMCPClient.stdio({
  command: "npx",
  args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
  agentId: "agent_123",
  apiKey: process.env.PARRY_API_KEY!,
});

try {
  const manifest = await mcp.listTools();
  const result = await mcp.callTool("read_file", { path: "/tmp/a.txt" });
} catch (e) {
  if (e instanceof MCPBlockedError) {
    // manifest was rejected — suspicious/blocked trust level or critical finding
  }
}
```

The manifest canonicalizer (`manifestHash`, `canonicalManifest`) is byte-identical
to the Python SDK's (`sdk/parry/mcp/normalize.py`) — hashes computed in either
language are comparable.

## Configuration

```ts
new ParryClient({
  apiKey: "sk-parry-...",       // required
  baseUrl: "https://api.parry.dev",  // default
  agentId: "agent_123",         // optional default for all calls
  timeout: 2000,                // pre-flight check timeout in ms
});
```

Environment variables are not read automatically — pass your API key explicitly.

## Error handling

```ts
import { ParryBlockedError, ParryPermissionDeniedError } from "@parry/sdk";

try {
  await parry.checkBeforeCall({ prompt });
} catch (e) {
  if (e instanceof ParryPermissionDeniedError) {
    // tool blocked by permission boundary — e.toolName available
  } else if (e instanceof ParryBlockedError) {
    // detection fired — e.detector, e.severity, e.confidence, e.reason
  }
}
```

## Fail-open contract

Parry will never drop a valid LLM call due to its own failure. Specifically:

- Network errors, timeouts, and non-2xx responses from the Parry API are
  swallowed in `checkBeforeCall`, `scanResponse`, and `ingestEvent`.
- `scanResponse` returns the original response text on failure rather than
  throwing, so a scan failure cannot corrupt what your user sees.
- `ingestEvent` is fire-and-forget.

The only things that throw are explicit `blocked=true` / `allowed=false`
responses from the backend.

## Development

```bash
npm install
npx vitest run        # 69 tests
npm run typecheck
npm run build
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
