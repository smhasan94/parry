# Cost and Budgets

Every event Parry observes is tagged with an estimated USD cost
the moment it lands. That cost feeds three different surfaces:
the dashboard's cost views, the cost-exploitation detectors, and
the budget-enforcement layer that can stop an agent at the
proxy when its spend crosses a configured cap.

This guide covers the full flow — how cost is computed, how
budgets enforce caps, the alert thresholds, and the operational
patterns that keep cost from being a surprise. If you've already
read the [Detection Catalog](detection-catalog.md), the three
cost-exploit detectors there describe the *anomaly-driven* side
of cost monitoring; budgets describe the *threshold-driven* side.
Both are useful and they cover different attacks.

---

## How cost gets computed

Parry maintains a pricing registry mapping known model
identifiers to their per-token pricing. When the SDK sends an
event with `model`, `input_tokens`, and `output_tokens`, the
ingest pipeline computes:

```
cost_usd = (input_tokens / 1000) × input_per_1k
        + (output_tokens / 1000) × output_per_1k
```

The figure is stored on the event row, aggregated into per-agent
spend counters, and is what every cost view in the dashboard is
ultimately displaying.

### The pricing registry

Pricing is hard-coded in `app/core/model_pricing.py`. Hard-coded
because provider pricing pages change layout constantly and a
scraper failure must never break ingest. The registry currently
includes all major OpenAI models (`gpt-4o`, `gpt-4o-mini`,
`gpt-4-turbo`, `gpt-4`, `gpt-3.5-turbo`, `o1`, `o1-mini`),
Anthropic models (`claude-opus-4-6`, `claude-sonnet-4-6`,
`claude-haiku-4-5`, plus the 3.5 family), and Google models
(`gemini-1.5-pro`, `gemini-1.5-flash`).

Two operational notes about the registry:

- **Unknown models cost $0.** When a model identifier isn't in
  the registry the cost is recorded as zero rather than rejecting
  the event. We never block ingest over a missing price entry.
  The downside is silent under-counting; the dashboard's cost
  views surface "unknown model" warnings so you notice.
- **Pricing has a freshness deadline.** Each entry comes with a
  human-reviewed audit date and a 120-day review interval. After
  that window, `is_pricing_stale()` returns `true` and the
  dashboard shows a "pricing stale — review" warning on cost
  surfaces. The check exists because providers cut prices
  meaningfully every quarter or two and stale entries
  systematically over-bill.

If you're using a model not in the registry, file a request
with the provider's published pricing — adding entries is a
two-line change and we ship them in patch releases.

### What "input tokens" and "output tokens" mean

Parry uses the provider's reported token usage when the SDK can
extract it from the response (OpenAI's `usage.total_tokens`,
Anthropic's `usage.input_tokens + output_tokens`). When the
provider doesn't report or the wrapper can't extract them, the
event records `token_count=null` and the cost is also `null`.
Cost-exploit detectors that depend on token counts are no-ops
for these events.

The SDK passes `latency_ms` and `token_count` through verbatim;
no client-side estimation is done. The reasoning is that token
counters are the only authoritative source — anything else
(character counts, word counts) is a guess that will diverge
from actual billing.

---

## Where cost shows up in the dashboard

Cost is surfaced in five places, each tuned to a different
question:

| Surface | Question it answers |
| --- | --- |
| **Dashboard → Org Cost Summary** | "What did we spend this billing cycle?" |
| **Agent Detail → Cost card** | "What is *this* agent costing me?" |
| **Agent Detail → Model Usage donut** | "Which models is this agent reaching for?" |
| **Detection Catalog → cost-exploit detectors** | "Is anyone exploiting cost?" |
| **Settings → Budgets** | "What caps are configured?" |

The org and per-agent surfaces use the cost-tagged events
directly; the cost-exploit detectors use baselines and session
history (see [Detection Catalog](detection-catalog.md) for the
full mechanics of `cost_exploit_loop`,
`cost_exploit_verbosity`, and `cost_exploit_model_escalation`).

---

## Budgets

Budgets are caps on USD spend over a fixed period. When an agent
crosses its cap, the proxy returns a denial response — the LLM
call doesn't happen. They're the hard floor that every other
cost mechanism complements.

### Fields

| Field | Values | Notes |
| --- | --- | --- |
| `period` | `hour` / `day` / `month` | Reset cadence |
| `cap_usd` | numeric | Hard cap in dollars |
| `enabled` | bool | When `false`, the budget is configured but not enforced |
| `alert_at_pcts` | list of integers | Percent thresholds at which to fire alerts. Default `[75, 90, 100]` |
| `agent_id` | UUID or NULL | NULL = org-wide default |

A budget is uniquely keyed by `(org_id, agent_id, period)` —
which means the same agent can have an `hour` and a `day` budget
simultaneously and both apply. Agent-specific budgets take
precedence over org defaults. Per-agent budgets at multiple
periods are checked together; an event is allowed only if it
fits *every* applicable cap.

### How enforcement works

When the proxy receives a check request, the budget service:

1. Loads the most specific enabled budget for the agent
   (agent-specific first, then org-default).
2. Reads the current period's spend from a Redis counter.
3. Computes the projected spend (`current + event_cost`).
4. **Blocks at 95% of cap** to leave headroom for the call
   that's already in flight when this one arrives. The 5% gap
   is intentional — without it, two concurrent calls could
   collectively exceed the cap before either finishes.
5. Fires any newly-crossed threshold alerts (more on those
   below).
6. Returns either an allow or a denial.

Spend counters are kept in Redis with TTLs that match the period
(hourly: 1h+5min, daily: 25h, monthly: 32 days). When a period
rolls over the counter expires and starts fresh — there's no
explicit reset job because the TTL handles it. A stop-spend
`record_spend` call increments all three period counters (hour,
day, month) atomically using a Redis pipeline so dashboards see
consistent values across periods.

Both `record_spend` and `check_spend` **fail open** on any
Redis error. A Redis outage means budgets aren't enforced for
the duration of the outage, but agents keep working. The
alternative — blocking calls when we can't read counters —
would turn an internal incident into a customer-visible one,
which is exactly the failure mode budgets are supposed to
prevent.

### Threshold alerts

`alert_at_pcts` defines the percentage thresholds at which Parry
fires `budget.exceeded` webhooks and configured alert-channel
notifications. The default `[75, 90, 100]` gives you three
warnings: "halfway through", "almost there", "blocking now."

Each threshold fires **at most once per period**, enforced via
a Redis NX key whose TTL matches the period. New period, new
alert. The dedup also covers the case where many concurrent
events all cross the same threshold simultaneously — only one
of them wins the SETNX race and emits the alert.

A threshold at exactly 100% is the moment the proxy starts
blocking (enforced at 95% as described above; the 100% alert
fires when projected spend reaches the actual cap). Many
operators add a 50% threshold for additional warning lead-time
on monthly budgets.

---

## Operational patterns

### Tier your defaults

The simplest budget posture is one tiered org-default budget:

| Period | Cap | Why |
| --- | --- | --- |
| `hour` | $5 | Catches runaway loops within minutes, not hours |
| `day` | $50 | Bounds a bad day even if hourly thresholds are silent |
| `month` | $1000 | Backstop against quiet drift |

The hour cap is the most important. A prompt-injection that
tells an agent to keep retrying tools doesn't blow the monthly
budget for hours; it blows the hourly budget for hours.

Per-agent caps override org defaults, so high-volume production
agents can have their own larger caps without weakening the
org-wide protection on dev or experimental agents.

### Use disabled-but-configured records

Same trick as permissions: configure budgets with `enabled=false`
when you're still measuring. The record exists, the alert
thresholds are documented, but enforcement is off. Watch the
threshold alerts fire (or not) for a representative period,
then flip `enabled=true` once the cap looks right.

### Pair budgets with the cost-exploit detectors

Budgets catch *aggregate* overspend — the cap is hit by the
combined effect of all events. The cost-exploit detectors catch
*individual* anomalous events: a single 100K-token call, a tight
tool-call loop, a silent model escalation. Both layers matter.
A bad actor exploiting cost will trigger the detectors *before*
the cap, and that's the right outcome — you'd rather catch the
attack than just stop the bleeding after it's already cost you.

### Don't budget what you don't price

Budgets can only block based on cost, and cost requires a model
in the pricing registry. Agents that use unknown models will
have their costs recorded as $0 and their budgets will never
trigger. If you're rolling out a new model, add it to the
pricing registry first or expect cost monitoring to be blind.

### Review pricing freshness

The 120-day review nudge isn't decorative. Provider price cuts
happen every quarter or two, and stale entries systematically
over-bill — your dashboard says you're spending more than you
actually are, your budget thresholds fire earlier than they
should, and your forecast is wrong. When you see the
"pricing stale — review" warning, check the provider's pricing
page and submit updated numbers.

---

## Where to go next

- [Detection Catalog](detection-catalog.md) — the three
  cost-exploit detectors that complement budgets at the
  per-event level.
- [Permissions](permissions.md) — agent-level tool boundaries;
  combined with budgets, these are the "what an agent can do
  and how much it can spend" pair.
- [Dashboard tour](dashboard-tour.md) — the Org Cost Summary,
  Agent Detail Cost card, and Settings → Budgets surfaces.
- [Integrations](integrations.md) — wiring `budget.exceeded`
  alerts into Slack, PagerDuty, or Opsgenie.
