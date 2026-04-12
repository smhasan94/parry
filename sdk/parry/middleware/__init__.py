"""Framework middleware — zero-config agent security.

Import and call the middleware function once. All LLM calls through
the framework are automatically intercepted and sent to Parry.

Usage:
    import parry
    parry.init(api_key="sk-parry-...")

    from parry.middleware import auto_instrument
    auto_instrument()  # patches OpenAI + Anthropic globally
"""
