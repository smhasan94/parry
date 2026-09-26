"""Tests for detector_config_service: merge, lookup, validation."""

import pytest

from app.services.detector_config_service import (
    DEFAULT_DETECTOR_CONFIG,
    DETECTOR_NAMES,
    is_enabled,
    merged_config,
    threshold_for,
    validate_config,
)


class TestMergedConfig:
    def test_none_returns_defaults(self) -> None:
        result = merged_config(None)
        assert set(result.keys()) == set(DETECTOR_NAMES)
        for name, defaults in DEFAULT_DETECTOR_CONFIG.items():
            if name == "custom_rules":
                # custom_rules is a list, not a per-detector dict —
                # see the merged_config docstring.
                assert result[name] == []
            else:
                assert result[name] == defaults

    def test_empty_returns_defaults(self) -> None:
        result = merged_config({})
        for name, defaults in DEFAULT_DETECTOR_CONFIG.items():
            if name == "custom_rules":
                assert result[name] == []
            else:
                assert result[name] == defaults

    def test_custom_rules_list_passes_through(self) -> None:
        """Regression: the custom_rules list used to get clobbered
        by the default per-detector dict, breaking the detector at
        runtime with AttributeError."""
        rules = [
            {"id": "r1", "name": "test", "pattern": "foo", "enabled": True},
            {"id": "r2", "name": "test2", "pattern": "bar", "enabled": False},
        ]
        result = merged_config({"custom_rules": rules})
        assert result["custom_rules"] == rules

    def test_partial_override_only_replaces_specified_fields(self) -> None:
        result = merged_config({"prompt_injection": {"trigger_threshold": 0.4}})
        assert result["prompt_injection"]["trigger_threshold"] == 0.4
        # enabled should still be the default
        assert result["prompt_injection"]["enabled"] is True
        # Other detectors untouched
        assert result["jailbreak"] == DEFAULT_DETECTOR_CONFIG["jailbreak"]

    def test_disable_a_detector(self) -> None:
        result = merged_config({"anomaly": {"enabled": False}})
        assert result["anomaly"]["enabled"] is False
        # Threshold preserved at default
        assert result["anomaly"]["trigger_threshold"] == 0.5

    def test_unknown_keys_in_org_config_ignored(self) -> None:
        result = merged_config({"prompt_injection": "not-a-dict"})  # type: ignore[dict-item]
        assert result["prompt_injection"] == DEFAULT_DETECTOR_CONFIG["prompt_injection"]


class TestThresholdFor:
    def test_no_config_returns_default(self) -> None:
        assert threshold_for({}, "prompt_injection", 0.6) == 0.6

    def test_event_data_override(self) -> None:
        event = {"detector_config": {"prompt_injection": {"trigger_threshold": 0.3}}}
        assert threshold_for(event, "prompt_injection", 0.6) == 0.3

    def test_other_detector_not_affected(self) -> None:
        event = {"detector_config": {"jailbreak": {"trigger_threshold": 0.4}}}
        assert threshold_for(event, "prompt_injection", 0.6) == 0.6

    def test_invalid_threshold_falls_back_to_default(self) -> None:
        event = {"detector_config": {"prompt_injection": {"trigger_threshold": "high"}}}
        assert threshold_for(event, "prompt_injection", 0.6) == 0.6

    def test_int_threshold_coerced_to_float(self) -> None:
        event = {"detector_config": {"prompt_injection": {"trigger_threshold": 1}}}
        assert threshold_for(event, "prompt_injection", 0.6) == 1.0


class TestIsEnabled:
    def test_default_is_enabled(self) -> None:
        assert is_enabled({}, "prompt_injection") is True

    def test_explicit_enabled_true(self) -> None:
        event = {"detector_config": {"prompt_injection": {"enabled": True}}}
        assert is_enabled(event, "prompt_injection") is True

    def test_explicit_disabled(self) -> None:
        event = {"detector_config": {"prompt_injection": {"enabled": False}}}
        assert is_enabled(event, "prompt_injection") is False

    def test_partial_config_without_enabled_key_defaults_to_true(self) -> None:
        event = {"detector_config": {"prompt_injection": {"trigger_threshold": 0.4}}}
        assert is_enabled(event, "prompt_injection") is True


class TestValidateConfig:
    def test_empty_config_is_valid(self) -> None:
        assert validate_config({}) == {}

    def test_full_valid_config(self) -> None:
        config = {
            "prompt_injection": {"trigger_threshold": 0.5, "enabled": True},
            "jailbreak": {"trigger_threshold": 0.8, "enabled": False},
        }
        result = validate_config(config)
        assert result == config

    def test_partial_field_valid(self) -> None:
        result = validate_config({"prompt_injection": {"trigger_threshold": 0.5}})
        assert result == {"prompt_injection": {"trigger_threshold": 0.5}}

    def test_only_enabled_valid(self) -> None:
        result = validate_config({"jailbreak": {"enabled": False}})
        assert result == {"jailbreak": {"enabled": False}}

    def test_adversarial_suffix_is_configurable(self) -> None:
        """Regression: adversarial_suffix shipped without a registry entry,
        so validate_config rejected any attempt to tune or disable it."""
        config = {"adversarial_suffix": {"trigger_threshold": 0.3, "enabled": False}}
        assert validate_config(config) == config

    def test_adversarial_suffix_default_matches_detector_fallback(self) -> None:
        # The registry default must equal the value the detector falls
        # back to when no config is present (see the lockstep note on
        # DEFAULT_DETECTOR_CONFIG), and must stay above the detector's
        # confidence ceiling so it cannot self-trigger by default.
        from app.detection.detectors.adversarial_suffix import _MAX_CONFIDENCE

        default = DEFAULT_DETECTOR_CONFIG["adversarial_suffix"]
        assert default == {"trigger_threshold": 0.7, "enabled": True}
        assert default["trigger_threshold"] > _MAX_CONFIDENCE

    def test_unknown_detector_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown detector"):
            validate_config({"made_up_detector": {"trigger_threshold": 0.5}})

    def test_threshold_below_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="between"):
            validate_config({"prompt_injection": {"trigger_threshold": -0.1}})

    def test_threshold_above_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="between"):
            validate_config({"prompt_injection": {"trigger_threshold": 1.5}})

    def test_threshold_zero_and_one_accepted(self) -> None:
        validate_config({"prompt_injection": {"trigger_threshold": 0.0}})
        validate_config({"prompt_injection": {"trigger_threshold": 1.0}})

    def test_non_numeric_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="number"):
            validate_config({"prompt_injection": {"trigger_threshold": "high"}})

    def test_non_bool_enabled_rejected(self) -> None:
        with pytest.raises(ValueError, match="boolean"):
            validate_config({"prompt_injection": {"enabled": "yes"}})

    def test_non_dict_config_rejected(self) -> None:
        with pytest.raises(ValueError, match="object"):
            validate_config("not-a-dict")  # type: ignore[arg-type]

    def test_non_dict_detector_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be an object"):
            validate_config({"prompt_injection": "high"})  # type: ignore[dict-item]

    def test_empty_detector_entry_dropped(self) -> None:
        """If neither field is provided, the entry is dropped from the result."""
        result = validate_config({"prompt_injection": {}})
        assert result == {}
