"""Effort-to-provider mapping and usage accumulation."""

from types import SimpleNamespace

import pytest

from any_to_bench.llm import UsageTracker, resolve_model_settings
from any_to_bench.schemas.usage import Effort


class TestResolveModelSettings:
    def test_none_effort_keeps_provider_defaults(self):
        assert resolve_model_settings("openai:gpt-5.6-sol", None) is None

    @pytest.mark.parametrize("effort", list(Effort))
    def test_openai_passthrough(self, effort):
        settings = resolve_model_settings("openai:gpt-5.6-terra", effort)
        assert settings == {"openai_reasoning_effort": effort.value}

    @pytest.mark.parametrize(
        ("effort", "level"),
        [
            (Effort.minimal, "MINIMAL"),
            (Effort.low, "LOW"),
            (Effort.medium, "MEDIUM"),
            (Effort.high, "HIGH"),
            (Effort.xhigh, "HIGH"),
            (Effort.max, "HIGH"),
        ],
    )
    def test_google_mapping(self, effort, level):
        settings = resolve_model_settings("google:gemini-3.7-flash", effort)
        assert settings == {"google_thinking_config": {"thinking_level": level}}

    def test_accepts_plain_strings(self):
        settings = resolve_model_settings("openai:gpt-5.6-sol", "low")
        assert settings == {"openai_reasoning_effort": "low"}

    def test_unknown_provider_ignored(self):
        assert resolve_model_settings("test", Effort.high) is None


class TestUsageTracker:
    def _usage(self, **overrides):
        base = {
            "requests": 1,
            "input_tokens": 100,
            "output_tokens": 10,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "details": {},
        }
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_empty_tracker_summarizes_to_none(self):
        assert UsageTracker().summary() is None

    def test_accumulates_per_phase_and_total(self):
        tracker = UsageTracker()
        tracker.add("extract", self._usage(details={"reasoning_tokens": 5}))
        tracker.add("extract", self._usage(input_tokens=200))
        tracker.add("answers", self._usage(details={"thoughts_tokens": 3}))
        summary = tracker.summary()
        assert summary is not None
        assert summary.phases["extract"].requests == 2
        assert summary.phases["extract"].input_tokens == 300
        assert summary.phases["extract"].reasoning_tokens == 5
        assert summary.phases["answers"].reasoning_tokens == 3  # Google's field name
        assert summary.total.requests == 3
        assert summary.total.input_tokens == 400
        assert summary.total.reasoning_tokens == 8

    def test_format_line(self):
        tracker = UsageTracker()
        tracker.add("solve", self._usage(input_tokens=12345, details={"reasoning_tokens": 42}))
        line = tracker.summary().format_line()
        assert "12,345 in" in line
        assert "10 out" in line
        assert "reasoning 42" in line
        assert "1 request(s)" in line
