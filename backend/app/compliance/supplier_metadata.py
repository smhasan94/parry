"""Known model → supplier mapping for the Article 26 supplier register.

Auto-enriches supplier records with jurisdiction, provider URL, and DPA
link when available. Unknown models still get recorded — just without
the enrichment fields.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SupplierInfo:
    supplier_name: str
    jurisdiction: str
    provider_url: str
    dpa_url: str | None = None


SUPPLIER_METADATA: dict[str, SupplierInfo] = {
    # OpenAI
    "gpt-4o": SupplierInfo(
        supplier_name="OpenAI",
        jurisdiction="US",
        provider_url="https://openai.com",
        dpa_url="https://openai.com/policies/data-processing-addendum",
    ),
    "gpt-4o-mini": SupplierInfo(
        supplier_name="OpenAI",
        jurisdiction="US",
        provider_url="https://openai.com",
        dpa_url="https://openai.com/policies/data-processing-addendum",
    ),
    "gpt-4-turbo": SupplierInfo(
        supplier_name="OpenAI",
        jurisdiction="US",
        provider_url="https://openai.com",
        dpa_url="https://openai.com/policies/data-processing-addendum",
    ),
    "gpt-4": SupplierInfo(
        supplier_name="OpenAI",
        jurisdiction="US",
        provider_url="https://openai.com",
        dpa_url="https://openai.com/policies/data-processing-addendum",
    ),
    "gpt-3.5-turbo": SupplierInfo(
        supplier_name="OpenAI",
        jurisdiction="US",
        provider_url="https://openai.com",
        dpa_url="https://openai.com/policies/data-processing-addendum",
    ),
    "o1": SupplierInfo(
        supplier_name="OpenAI",
        jurisdiction="US",
        provider_url="https://openai.com",
    ),
    "o1-mini": SupplierInfo(
        supplier_name="OpenAI",
        jurisdiction="US",
        provider_url="https://openai.com",
    ),
    "o3-mini": SupplierInfo(
        supplier_name="OpenAI",
        jurisdiction="US",
        provider_url="https://openai.com",
    ),
    # Anthropic
    "claude-opus-4-6": SupplierInfo(
        supplier_name="Anthropic",
        jurisdiction="US",
        provider_url="https://anthropic.com",
        dpa_url="https://anthropic.com/legal/dpa",
    ),
    "claude-sonnet-4-6": SupplierInfo(
        supplier_name="Anthropic",
        jurisdiction="US",
        provider_url="https://anthropic.com",
        dpa_url="https://anthropic.com/legal/dpa",
    ),
    "claude-haiku-4-5-20251001": SupplierInfo(
        supplier_name="Anthropic",
        jurisdiction="US",
        provider_url="https://anthropic.com",
        dpa_url="https://anthropic.com/legal/dpa",
    ),
    "claude-3-5-sonnet-20241022": SupplierInfo(
        supplier_name="Anthropic",
        jurisdiction="US",
        provider_url="https://anthropic.com",
        dpa_url="https://anthropic.com/legal/dpa",
    ),
    # Google
    "gemini-2.0-flash": SupplierInfo(
        supplier_name="Google",
        jurisdiction="US",
        provider_url="https://ai.google.dev",
    ),
    "gemini-2.5-pro": SupplierInfo(
        supplier_name="Google",
        jurisdiction="US",
        provider_url="https://ai.google.dev",
    ),
    "gemini-1.5-pro": SupplierInfo(
        supplier_name="Google",
        jurisdiction="US",
        provider_url="https://ai.google.dev",
    ),
    "gemini-1.5-flash": SupplierInfo(
        supplier_name="Google",
        jurisdiction="US",
        provider_url="https://ai.google.dev",
    ),
    # Mistral
    "mistral-large-latest": SupplierInfo(
        supplier_name="Mistral AI",
        jurisdiction="FR",
        provider_url="https://mistral.ai",
    ),
    "mistral-small-latest": SupplierInfo(
        supplier_name="Mistral AI",
        jurisdiction="FR",
        provider_url="https://mistral.ai",
    ),
    # Cohere
    "command-r-plus": SupplierInfo(
        supplier_name="Cohere",
        jurisdiction="CA",
        provider_url="https://cohere.com",
    ),
    "command-r": SupplierInfo(
        supplier_name="Cohere",
        jurisdiction="CA",
        provider_url="https://cohere.com",
    ),
}


def get_supplier_info(model_id: str) -> SupplierInfo | None:
    """Look up supplier info for a model ID, with prefix fallback."""
    if model_id in SUPPLIER_METADATA:
        return SUPPLIER_METADATA[model_id]
    # Try prefix match (e.g. "gpt-4o-2024-08-06" → "gpt-4o")
    for key, info in SUPPLIER_METADATA.items():
        if model_id.startswith(key):
            return info
    return None


def supplier_name_for_model(model_id: str) -> str:
    """Return the supplier name for a model, or 'Unknown' if not mapped."""
    info = get_supplier_info(model_id)
    return info.supplier_name if info else "Unknown"
