# Parry SDK

Runtime security for AI agents. Parry sits between your agents and the LLMs they call, detecting prompt injection, data exfiltration, tool misuse, and anomalous behavior in real time.

## Installation

```bash
pip install parry
```

With LLM provider wrappers:

```bash
pip install parry[openai]        # OpenAI support
pip install parry[anthropic]     # Anthropic support
pip install parry[langchain]     # LangChain support
pip install parry[crewai]        # CrewAI support
pip install parry[autogen]       # AutoGen support
pip install parry[llamaindex]    # LlamaIndex support
pip install parry[pydantic-ai]   # Pydantic AI support
pip install parry[all]           # Everything
```

## Quick Start

### 1. Initialize

```python
import parry

parry.init(api_key="sk-parry-...", agent_id="my-agent")
```

### 2. Wrap your LLM client

**OpenAI:**

```python
from parry.wrappers.openai import ParryOpenAI

client = ParryOpenAI()  # drop-in replacement for openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
)
# Works exactly like OpenAI — Parry intercepts transparently
```

**Anthropic:**

```python
from parry.wrappers.anthropic import ParryAnthropic

client = ParryAnthropic()  # drop-in replacement for anthropic.Anthropic()
message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
```

**LangChain:**

```python
from parry.wrappers.langchain import ParryCallbackHandler

handler = ParryCallbackHandler(agent_id="my-agent")

# Works with any LangChain model, chain, or agent
chain.invoke("What is 2+2?", config={"callbacks": [handler]})
```

**CrewAI:**

```python
from crewai import Crew
from parry.wrappers.crewai import ParryCrewAICallback

crew = Crew(
    agents=[...],
    tasks=[...],
    callbacks=[ParryCrewAICallback(agent_id="my-crew")],
)
```

**AutoGen:**

```python
from parry.wrappers.autogen import ParryConversableAgent

assistant = ParryConversableAgent(
    name="assistant",
    agent_id="my-autogen-agent",
    llm_config={"model": "gpt-4o"},
)
# Drop-in replacement for autogen.ConversableAgent
```

**LlamaIndex:**

```python
from llama_index.core import Settings
from parry.wrappers.llamaindex import ParryCallbackHandler

Settings.callback_manager.add_handler(
    ParryCallbackHandler(agent_id="my-llamaindex-agent")
)
# Every LLM call through LlamaIndex now flows through Parry
```

**Pydantic AI:**

```python
from pydantic_ai import Agent
from parry.wrappers.pydantic_ai import parry_instrument

agent = Agent("openai:gpt-4o")
parry_instrument(agent, agent_id="my-pydantic-agent")
# Instrumentation patches agent.model.request in place
```

### 3. Streaming

Both OpenAI and Anthropic wrappers support streaming out of the box:

```python
client = ParryOpenAI()
stream = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content, end="")
# Parry captures the full response after the stream completes
```

## Async Client

For async codebases (FastAPI, aiohttp, etc.):

```python
from parry import AsyncParryClient

client = AsyncParryClient(
    api_key="sk-parry-...",
    default_agent_id="my-agent",
)

# Fire-and-forget (non-blocking)
await client.send_event(
    prompt="user input",
    response="llm output",
    model="gpt-4o",
)

# Or await delivery confirmation
await client.send_event_blocking(
    prompt="user input",
    response="llm output",
    model="gpt-4o",
)

await client.close()
```

## How It Works

1. Your app calls the LLM through a Parry wrapper
2. The wrapper captures the prompt, response, model, tool calls, latency, and token count
3. PII (credit cards, SSNs, emails) is stripped client-side before sending
4. The event is sent to the Parry backend asynchronously (fire-and-forget)
5. Your app gets the LLM response with zero added latency

The SDK never blocks your application. If the Parry backend is unreachable, the SDK logs a warning and passes the call through unchanged.

## What Gets Detected

The Parry backend runs 6 detectors on every event:

- **Prompt Injection** -- attempts to override system instructions
- **Jailbreak** -- known jailbreak patterns (DAN, developer mode, etc.)
- **Tool Misuse** -- tool calls that violate org policies
- **Data Exfiltration** -- PII or secrets in LLM responses
- **Privilege Escalation** -- attempts to gain elevated access
- **Anomaly Detection** -- behavioral drift from agent baselines

## Configuration

```python
import parry

parry.init(
    api_key="sk-parry-...",       # Required: your Parry API key
    base_url="https://api.parry.dev",  # Optional: custom backend URL
    agent_id="my-agent",          # Optional: default agent ID for all events
)
```

Per-wrapper agent/session IDs:

```python
client = ParryOpenAI(
    agent_id="specific-agent",    # Override default agent ID
    session_id="session-123",     # Group related calls
)
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
