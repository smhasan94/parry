# Python SDK

The Parry Python SDK is the most-used integration path. It ships
drop-in wrappers for the major LLM clients (`ParryOpenAI`,
`ParryAnthropic`) and framework hooks for everything else
(LangChain, CrewAI, AutoGen, LlamaIndex, Pydantic AI), an MCP
security client (`SentinelMCPClient`), and a global monkey-patch
mode (`auto_instrument`) for codebases you can't easily edit.

The integration philosophy is two lines of code, never blocks the
agent's hot path, and always fails open. Every claim in that
sentence is enforced in the SDK source — this guide explains what
that means in practice and shows you how each surface behaves so
you can pick the right one for your codebase.

If you've never used Parry before, read [Getting Started](../getting-started.md)
first — this document assumes you have an API key and an `agent_id`
in hand and want a complete reference for the Python surface.

---

## Install

The base package has one runtime dependency (`httpx`) and works on
Python 3.10+:

```bash
pip install parry
```

Each LLM/framework integration ships as an optional extra so you
only pull in the pieces you actually use:

| Extra | Installs | Used by |
| --- | --- | --- |
| `parry[openai]` | `openai>=1.50` | `ParryOpenAI` wrapper |
| `parry[anthropic]` | `anthropic>=0.40` | `ParryAnthropic` wrapper |
| `parry[langchain]` | `langchain-core>=0.3` | `ParryCallbackHandler` |
| `parry[crewai]` | `crewai>=0.28` | `ParryCrewAICallback` |
| `parry[autogen]` | `pyautogen>=0.2` | `ParryConversableAgent` |
| `parry[llamaindex]` | `llama-index-core>=0.10` | `ParryCallbackHandler` (LlamaIndex) |
| `parry[pydantic-ai]` | `pydantic-ai>=0.2` | `parry_instrument` |
| `parry[mcp]` | `mcp>=1.0` | `SentinelMCPClient` |
| `parry[all]` | all of the above | mixed codebases |

If you import a wrapper without its extra you get a clean
`ImportError` with the exact `pip install` command — the SDK never
imports the upstream library at module load time so the base
package stays small.

---

## Initialize the SDK

`parry.init` configures a single process-wide client. Call it once
at startup, before any wrapper or callback runs:

```python
import parry

parry.init(
    api_key="sk-parry-...",          # required
    agent_id="support-bot",          # default agent_id for this process
    base_url="https://api.parry.dev",  # override for self-hosted/staging
)
```

The client is held in a module-level singleton; subsequent
`parry.get_client()` calls return the same instance. Wrappers and
the LangChain/LlamaIndex/CrewAI callbacks all resolve the client
through `get_client()`, which means **you must call `init` before
any LLM call you want monitored**. The interceptor catches the
"not initialized" case and skips silently rather than crashing the
host app, so missing init never breaks production — it just turns
Parry off until init is reached.

The `agent_id` argument is the default. Every wrapper and callback
takes its own `agent_id=` parameter that overrides the default per
call site, which is how a single process can monitor multiple
named agents.

### Configuration

| Argument | Default | Notes |
| --- | --- | --- |
| `api_key` | (required) | Sent as `X-Parry-Secret` header |
| `base_url` | `https://api.parry.dev` | Strip trailing slash; use the URL of your self-hosted backend or staging environment |
| `agent_id` | `None` | Default agent identifier when wrappers don't pass one |

The underlying `ParryClient` also takes a `timeout=5.0` argument
for the HTTP client. The async ingest path is fire-and-forget so
this rarely matters; if you're tunnelling through a slow proxy you
can construct a `ParryClient` directly and assign it.

---

## Drop-in wrappers

`ParryOpenAI` and `ParryAnthropic` are subclass-shaped wrappers
that accept everything their underlying client does. The intent is
that you change two import lines and your existing code works
unchanged:

```python
# before
from openai import OpenAI
client = OpenAI()

# after
from parry.wrappers.openai import ParryOpenAI
client = ParryOpenAI(agent_id="support-bot")
```

Any constructor kwargs you pass (`api_key=`, `base_url=`,
`organization=`, `default_headers=` etc.) are forwarded to the
real client. Attribute access falls through to the wrapped client,
so `client.embeddings`, `client.audio`, `client.beta` and so on
work exactly as before. Only the chat-completion path is
instrumented — embeddings and audio aren't agent calls, so they
don't get observed.

### What happens on every call

`client.chat.completions.create(...)` (OpenAI) and
`client.messages.create(...)` (Anthropic) both go through the same
five-step pipeline:

1. **Pre-flight check.** Parry calls `/api/v1/proxy/check`
   synchronously with a 2 s timeout. If your org has blocking
   enabled and a detector triggers above the configured severity,
   the wrapper raises `ParryBlockedError` *before* the LLM call
   happens. If the check fails for any other reason — network
   error, timeout, 5xx — the wrapper proceeds (fail-open).
2. **The actual LLM call.** Once cleared, the wrapper invokes the
   underlying client. Streaming and tool-use kwargs pass through
   unchanged.
3. **Async ingest.** After the response arrives, the wrapper sends
   the prompt, response, model, tool calls, token count, and
   latency to `/api/v1/events/ingest` on a background thread. The
   caller never waits for this.
4. **Post-LLM response scan.** Parry calls
   `/api/v1/proxy/scan-response` synchronously (also 2 s timeout)
   to look for sensitive data exfiltration. Three outcomes:
   - response unchanged → returned as-is;
   - redacted in place → the wrapper substitutes the cleaned text
     into the result object before returning;
   - blocked → `ParryBlockedError` raised with `detector="data_exfiltration"`.
5. **Return.** The host agent gets back the original (or redacted)
   response object — same type, same shape.

The async ingest in step 3 always sees the **original** response
text, even when step 4 redacts it, so your incident view in the
dashboard has full forensic evidence regardless of what the host
agent ultimately saw.

### Streaming

Both wrappers detect `stream=True` and return a generator that
yields the underlying chunks unchanged. The wrapper accumulates
the streamed text in the background and ingests one event after
the stream closes. Latency is measured from `create()` to last
chunk:

```python
stream = client.chat.completions.create(
    model="gpt-4o",
    messages=[...],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

The pre-flight blocking check still happens before the stream
opens; the post-LLM response scan does **not** run on streamed
responses (you can't redact a stream after it's been delivered),
so streaming bypasses data-exfiltration redaction by design.

### Tool calls

Tool calls are extracted and sent as structured `tool_calls=[{name, arguments}]`
on the event. OpenAI's `choice.message.tool_calls` and Anthropic's
`tool_use` content blocks are normalised to the same wire format,
so the dashboard tool-misuse view treats them identically.

---

## Framework callbacks

The drop-in wrappers cover raw OpenAI and Anthropic. For
agent frameworks you typically already have a callback or
instrumentation hook — Parry plugs into each one's native
extension point so the framework keeps owning the lifecycle.

### LangChain

```python
from parry.wrappers.langchain import ParryCallbackHandler

handler = ParryCallbackHandler(agent_id="research-agent")
chain.invoke(question, config={"callbacks": [handler]})
```

`ParryCallbackHandler` extends `BaseCallbackHandler` and hooks
`on_chat_model_start`, `on_llm_start`, `on_llm_end`,
`on_llm_error`, `on_tool_start`, `on_tool_end`. Per-run state is
keyed by `run_id` so it's safe to share one handler across
parallel chains. Every LLM invocation in your chain — top-level
or nested inside a tool — produces one event.

The LangChain handler does **not** run the pre-flight blocking
check (that path requires a synchronous prompt boundary, which
LangChain doesn't expose). To get blocking with LangChain, use the
`auto_instrument` mode below or wrap your model with `ParryOpenAI`
inside a `ChatOpenAI(client=...)` configuration.

### CrewAI

```python
from parry.wrappers.crewai import ParryCrewAICallback

crew = Crew(
    agents=[...],
    tasks=[...],
    callbacks=[ParryCrewAICallback(agent_id="research-crew")],
)
```

CrewAI's callback class moved between minor versions, so the
Parry implementation is duck-typed (`on_llm_start` /
`on_llm_end` / `on_llm_error`) rather than subclassing CrewAI's
`BaseCallback` directly. This makes it resilient across the 0.28+
release line.

### AutoGen

```python
from parry.wrappers.autogen import ParryConversableAgent

agent = ParryConversableAgent(
    name="assistant",
    agent_id="my-autogen-agent",
    llm_config={"model": "gpt-4o"},
)
```

`ParryConversableAgent` is a factory that returns a
`ConversableAgent` subclass with an instrumented `generate_reply`.
The factory pattern is needed because `pyautogen` is imported
lazily — declaring `class ParryConversableAgent(ConversableAgent)`
at module level would break the import for users who haven't
installed the `[autogen]` extra.

### LlamaIndex

```python
from llama_index.core import Settings
from parry.wrappers.llamaindex import ParryCallbackHandler

Settings.callback_manager.add_handler(
    ParryCallbackHandler(agent_id="rag-agent")
)
```

Same factory pattern as AutoGen for the same reason. The handler
listens to `CBEventType.LLM` events and pulls model/usage info
from the response object across LlamaIndex's evolving payload
shapes.

### Pydantic AI

```python
from pydantic_ai import Agent
from parry.wrappers.pydantic_ai import parry_instrument

agent = Agent("openai:gpt-4o")
parry_instrument(agent, agent_id="my-pydantic-agent")
```

Pydantic AI doesn't have a public callback protocol — it's built
around typed `Agent`/`Model` pairs — so `parry_instrument`
monkey-patches the agent's underlying `model.request`. If the
attribute path ever changes between releases the patch logs a
warning and no-ops; your pipeline keeps running, just without
Parry events for that agent.

---

## Auto-instrument mode

When you can't easily replace your LLM client (third-party
libraries, deeply nested code, large legacy codebases), use
`auto_instrument` to monkey-patch `openai.Completions.create` and
`anthropic.Messages.create` globally:

```python
import parry
parry.init(api_key="sk-parry-...", agent_id="my-agent")

from parry.middleware.auto_instrument import auto_instrument
auto_instrument()

# Every openai/anthropic call in this process is now monitored —
# including calls inside LangGraph, CrewAI, raw SDK usage, etc.
```

Auto-instrument is idempotent — calling it twice is safe. It only
patches the client classes if they're already imported and
silently skips any client that isn't installed. There's a `reset()`
helper for tests.

Auto-instrument doesn't run the pre-flight blocking check or the
response scan — it's observe-only. Use the wrappers if you need
blocking; use auto-instrument if you only need observation across
many call sites.

---

## Async client

If your service is fully async (FastAPI, aiohttp), use
`AsyncParryClient` for direct event submission without the
background-thread machinery:

```python
from parry import AsyncParryClient

client = AsyncParryClient(api_key="sk-parry-...", default_agent_id="api")

await client.send_event(prompt=user_prompt, response=llm_output, model="gpt-4o")
# or, when you need delivery confirmation:
await client.send_event_blocking(prompt=..., response=..., model=...)
```

`send_event` schedules an `asyncio.create_task` and returns
immediately. `send_event_blocking` awaits the HTTP call before
returning. Use the blocking variant only when you need delivery
guarantees — most apps want the fire-and-forget version so a slow
Parry backend never adds latency to user-facing requests.

The async client is for direct event submission only — the
wrappers above already use the sync client internally, and the
sync client uses a background thread per event so it doesn't
block your event loop either.

---

## MCP security

`SentinelMCPClient` wraps an MCP `ClientSession` to detect
manifest injection, server-policy blocks, and trust-graph
anomalies. It currently supports stdio transport (the default for
Claude Desktop, Cursor, Zed, Continue):

```python
from parry.mcp import SentinelMCPClient, MCPBlockedError

async with SentinelMCPClient.stdio(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    agent_id="dev-assistant",
    api_key="sk-parry-...",
) as client:
    tools = await client.list_tools()
    result = await client.call_tool("read_file", {"path": "/tmp/notes.md"})
```

On `__aenter__` the wrapper opens the underlying MCP session,
fetches the tool manifest, hashes it, and POSTs the manifest to
`/api/v1/mcp/connections`. The backend runs three checks:

- **Drift detection** against the previous manifest hash for the
  same `server_uri`.
- **Manifest injection** scanning across tool descriptions and
  schemas.
- **Org policy** — explicit allow/blocklists.

A `403` from the backend or a `critical`-severity detection
raises `MCPBlockedError` and closes the underlying session. Any
other failure is logged as a warning and the connection
proceeds — fail-open here too. See `docs/mcp-security.md` for the
full threat model and detection details.

---

## Error types

| Exception | Raised when | How to handle |
| --- | --- | --- |
| `ParryBlockedError` | Pre-flight or response scan blocked the call. Has `reason`, `detector`, `severity`, `confidence` | Catch in agent code; show user a refusal, retry with sanitised input, or escalate to a human |
| `ParryPermissionDeniedError` | Subclass of `ParryBlockedError`. The agent attempted a tool call its permission boundary forbids. Has `tool_name` | Catch separately when you want different UX for authorisation failures vs threat blocks |
| `MCPBlockedError` | MCP server blocked by org policy or critical detection. Has `reason`, `detections`, `server_uri` | Treat as a fatal connection error; refuse to use this server |
| `MCPManifestError` | MCP manifest is structurally invalid or `SentinelMCPClient` was used outside `async with` | Programmer error — fix the call site |

`ParryPermissionDeniedError` is intentionally a subclass of
`ParryBlockedError` so a generic `except ParryBlockedError` catch
still covers it. Code that wants different handling can put the
specific catch first:

```python
try:
    response = client.chat.completions.create(model="gpt-4o", messages=[...])
except ParryPermissionDeniedError as e:
    log.warn("agent_not_authorized", tool=e.tool_name)
    return canned_refusal()
except ParryBlockedError as e:
    log.warn("security_block", detector=e.detector, reason=e.reason)
    return canned_refusal()
```

---

## The fail-open contract

Parry must never be the reason a valid LLM call fails. Every
network or backend interaction in the SDK enforces this:

- **Event ingest** runs on a background thread and swallows every
  exception; the worst case is a missing event in the dashboard.
- **Pre-flight check** has a 2 s hard timeout. Anything other
  than an explicit `allowed=false` verdict — network error,
  non-200 status, malformed JSON, timeout — proceeds with the
  call.
- **Response scan** has the same 2 s timeout and the same
  fail-open contract. If the scanner is down, your agent's
  responses go through unredacted rather than getting dropped.
- **MCP register** fails open too. A backend outage means MCP
  connections proceed without manifest checks; an explicit `403`
  or critical detection still blocks.

The one place this **doesn't** apply is when the backend
explicitly tells the SDK to block — that's the whole point of
blocking mode, and it propagates `ParryBlockedError` directly.

If you want to verify fail-open behaviour in your own deployment,
the simplest test is to point `base_url` at a black-hole address
and confirm your agent still serves traffic.

---

## PII stripping

Sensitive patterns are stripped client-side before any data
leaves your process. The interceptor runs three regexes against
both `prompt` and `response`:

| Pattern | Replacement |
| --- | --- |
| 16-digit card numbers (with optional separators) | `[CREDIT_CARD]` |
| US Social Security numbers (`XXX-XX-XXXX`) | `[SSN]` |
| Email addresses | `[EMAIL]` |

This is a defense-in-depth layer, not a substitute for proper
data classification — the heavy detection lives server-side. If
your prompts contain regulated data not covered by these patterns,
talk to us about pre-processing hooks before sending to Parry.

Prompts and responses are also truncated to 4000 characters before
upload to keep payloads small; the dashboard always shows the
truncated version. Tool-call arguments are not truncated.

---

## Where to go next

- [Concepts](../concepts.md) — what the events you're sending
  actually become inside Parry.
- [Getting Started](../getting-started.md) — the end-to-end
  walkthrough if you skipped it.
- [`docs/mcp-security.md`](../../mcp-security.md) — MCP threat
  model, detector list, and the drift-detection algorithm.
- [`docs/red-team.md`](../../red-team.md) — how to verify your
  Parry deployment with adversarial inputs before you trust it
  with production traffic.
