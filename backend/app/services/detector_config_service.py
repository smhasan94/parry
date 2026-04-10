"""Per-org detector tuning configuration.

Each detector has a `trigger_threshold` (the confidence floor that flips
`triggered` to True) and an `enabled` flag. Defaults are tuned to minimize
false positives in typical usage; orgs can adjust both via the dashboard.
"""

from typing import Any

# Default thresholds — must match the values that detector code falls back to.
# When changing these, update the detector source files in lockstep.
DEFAULT_DETECTOR_CONFIG: dict[str, dict[str, Any]] = {
    "prompt_injection": {"trigger_threshold": 0.6, "enabled": True},
    "jailbreak": {"trigger_threshold": 0.7, "enabled": True},
    "privilege_escalation": {"trigger_threshold": 0.7, "enabled": True},
    "tool_misuse": {"trigger_threshold": 0.5, "enabled": True},
    "data_exfiltration": {"trigger_threshold": 0.5, "enabled": True},
    "anomaly": {"trigger_threshold": 0.5, "enabled": True, "sigma_threshold": 3.0},
    "custom_rules": {"trigger_threshold": 0.5, "enabled": True},
    "llm_fallback": {"trigger_threshold": 0.5, "enabled": True},
    "mcp_manifest": {"trigger_threshold": 0.5, "enabled": True},
    "cost_exploit_loop": {"trigger_threshold": 0.5, "enabled": True},
    "cost_exploit_verbosity": {"trigger_threshold": 0.5, "enabled": True},
    "cost_exploit_model_escalation": {"trigger_threshold": 0.5, "enabled": True},
    "threat_intel": {"trigger_threshold": 0.5, "enabled": True},
}

DETECTOR_NAMES = list(DEFAULT_DETECTOR_CONFIG.keys())

MIN_THRESHOLD = 0.0
MAX_THRESHOLD = 1.0


def merged_config(org_config: dict | None) -> dict[str, dict[str, Any]]:
    """Return defaults merged with org overrides. Always returns all detectors.

    Also preserves non-detector-config keys from the org config — in
    particular ``custom_rules`` is stored by the custom-rules API as
    a **list** of rule dicts at ``org.detector_config['custom_rules']``
    and the CustomRulesDetector reads it as a list. Without the
    passthrough below the list got clobbered with the default
    per-detector dict ``{"trigger_threshold": 0.5, "enabled": True}``
    and the detector raised AttributeError at runtime — two
    different concepts shared the same JSONB key.
    """
    result: dict[str, Any] = {}
    overrides = org_config or {}

    for name, defaults in DEFAULT_DETECTOR_CONFIG.items():
        if name == "custom_rules":
            # Special case — the storage key collides. Use the
            # user's list (or an empty one) rather than the
            # per-detector dict. The detector has no tunable
            # threshold, so there's no config to merge anyway.
            value = overrides.get("custom_rules")
            result["custom_rules"] = value if isinstance(value, list) else []
            continue

        merged = dict(defaults)
        if name in overrides and isinstance(overrides[name], dict):
            user = overrides[name]
            if "trigger_threshold" in user:
                merged["trigger_threshold"] = user["trigger_threshold"]
            if "enabled" in user:
                merged["enabled"] = user["enabled"]
            if "sigma_threshold" in user:
                merged["sigma_threshold"] = user["sigma_threshold"]
        result[name] = merged
    return result


def threshold_for(event_data: dict[str, Any], detector_name: str, default: float) -> float:
    """Look up the trigger threshold for a detector inside the event_data dict.

    Detector code calls this with its own hardcoded default so it works even
    when no detector_config is provided (tests, ad-hoc detector instantiation).
    """
    cfg = event_data.get("detector_config") or {}
    detector_cfg = cfg.get(detector_name)
    if not isinstance(detector_cfg, dict):
        return default
    threshold = detector_cfg.get("trigger_threshold")
    if not isinstance(threshold, int | float):
        return default
    return float(threshold)


def is_enabled(event_data: dict[str, Any], detector_name: str) -> bool:
    """Return False only if the org explicitly disabled this detector."""
    cfg = event_data.get("detector_config") or {}
    detector_cfg = cfg.get(detector_name)
    if not isinstance(detector_cfg, dict):
        return True
    return bool(detector_cfg.get("enabled", True))


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a config update from the API.

    Raises ValueError on invalid input. Returns a clean dict containing only
    known detectors with valid threshold values.
    """
    if not isinstance(config, dict):
        raise ValueError("detector_config must be an object")

    cleaned: dict[str, dict[str, Any]] = {}
    for name, value in config.items():
        if name not in DEFAULT_DETECTOR_CONFIG:
            raise ValueError(f"unknown detector: {name}")
        if not isinstance(value, dict):
            raise ValueError(f"{name} config must be an object")

        entry: dict[str, Any] = {}
        if "trigger_threshold" in value:
            t = value["trigger_threshold"]
            if not isinstance(t, int | float):
                raise ValueError(f"{name}.trigger_threshold must be a number")
            if t < MIN_THRESHOLD or t > MAX_THRESHOLD:
                raise ValueError(
                    f"{name}.trigger_threshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}"
                )
            entry["trigger_threshold"] = float(t)
        if "enabled" in value:
            if not isinstance(value["enabled"], bool):
                raise ValueError(f"{name}.enabled must be a boolean")
            entry["enabled"] = value["enabled"]
        if "sigma_threshold" in value:
            s = value["sigma_threshold"]
            if not isinstance(s, int | float):
                raise ValueError(f"{name}.sigma_threshold must be a number")
            if s <= 0 or s > 10:
                raise ValueError(f"{name}.sigma_threshold must be between 0 and 10")
            entry["sigma_threshold"] = float(s)

        if entry:
            cleaned[name] = entry

    return cleaned
