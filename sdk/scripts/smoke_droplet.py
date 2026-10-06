"""E2E smoke test against a deployed Parry backend.

Requires env:
  PARRY_BASE_URL=https://parry.example.com
  PARRY_API_KEY=sk-parry-...
  OPENAI_API_KEY=sk-...
"""

from __future__ import annotations

import os
import sys
import time

import httpx

from parry import init
from parry.wrappers.openai import ParryOpenAI

BASE = os.environ.get("PARRY_BASE_URL", "").rstrip("/")
AGENT_ID = "support-bot"


def main() -> int:
    parry_key = os.environ.get("PARRY_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not BASE:
        print("ERROR: PARRY_BASE_URL not set")
        return 1
    if not parry_key:
        print("ERROR: PARRY_API_KEY not set")
        return 1
    if not openai_key:
        print("ERROR: OPENAI_API_KEY not set")
        return 1

    print(f"[1/3] init Parry SDK against {BASE}")
    init(api_key=parry_key, base_url=BASE, agent_id=AGENT_ID)

    print("[2/3] OpenAI call via ParryOpenAI wrapper")
    client = ParryOpenAI(agent_id=AGENT_ID, api_key=openai_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Say 'parry smoke ok' and nothing else."}],
        max_tokens=20,
    )
    text = resp.choices[0].message.content
    print(f"    OpenAI response: {text!r}")

    print("[3/3] verify event landed in backend (poll up to 10s)")
    headers = {"Authorization": f"Bearer {parry_key}"}
    deadline = time.time() + 10
    while time.time() < deadline:
        r = httpx.get(f"{BASE}/api/v1/events?limit=1", headers=headers, timeout=5)
        r.raise_for_status()
        events = r.json()
        items = events.get("items") if isinstance(events, dict) else events
        if items:
            ev = items[0]
            print(f"    latest event id={ev.get('id')} agent={ev.get('agent_id')}")
            print("OK — event landed")
            return 0
        time.sleep(1)

    print("FAIL — no event arrived within 10s")
    return 2


if __name__ == "__main__":
    sys.exit(main())
