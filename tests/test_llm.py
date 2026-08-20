"""Effort-to-provider mapping, model construction, and usage accumulation."""

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from any_to_bench import llm
from any_to_bench.llm import ModelConfigError, UsageTracker, build_agent, resolve_model_settings
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

    @pytest.mark.parametrize(
        ("effort", "level"),
        [(Effort.low, "LOW"), (Effort.xhigh, "HIGH")],
    )
    def test_vertex_maps_like_the_gemini_api(self, effort, level):
        """Same models, different front door: the effort dial must reach both."""
        assert resolve_model_settings("google-cloud:gemini-3.7-flash", effort) == {
            "google_thinking_config": {"thinking_level": level}
        }

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


class Provider:
    """Stands in for GoogleCloudProvider, whose construction resolves ADC."""

    def __init__(self, project: str, location: str) -> None:
        self.project = project
        self.location = location


class TestVertexModel:
    """`google-cloud:` is the Vertex AI route: same Google models, Google Cloud
    credentials (a service account) instead of an API key."""

    @pytest.fixture(autouse=True)
    def _seam(self, monkeypatch):
        self.calls: list[tuple[str, str]] = []

        def provider(project: str, location: str):
            self.calls.append((project, location))
            return Provider(project, location)

        monkeypatch.setattr(llm, "_google_cloud_provider", provider)
        for name in (
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_CLOUD_LOCATION",
        ):
            monkeypatch.delenv(name, raising=False)

    @property
    def projects(self) -> list[str]:
        return [project for project, _ in self.calls]

    def _key_file(self, tmp_path, **extra):
        path = tmp_path / "sa.json"
        path.write_text(json.dumps({"type": "service_account", **extra}))
        return str(path)

    def test_other_providers_pass_through_untouched(self):
        assert llm.resolve_model("google:gemini-3.7-flash") == "google:gemini-3.7-flash"
        assert llm.resolve_model("openai:gpt-5.6-sol") == "openai:gpt-5.6-sol"
        assert self.calls == []

    def test_project_comes_from_the_key_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "GOOGLE_APPLICATION_CREDENTIALS", self._key_file(tmp_path, project_id="from-key")
        )
        model = llm.resolve_model("google-cloud:gemini-3.7-flash")
        assert self.projects == ["from-key"]
        assert model.model_name == "gemini-3.7-flash"

    def test_location_defaults_to_global_and_the_env_overrides(self, tmp_path, monkeypatch):
        """`global` is where new Gemini models land; pydantic-ai's own default,
        us-central1, 404s for every current one on a real project."""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
        llm.resolve_model("google-cloud:gemini-3.7-flash")
        assert self.calls == [("p", "global")]

        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-east5")
        llm.resolve_model("google-cloud:gemini-3.7-flash")
        assert self.calls[-1] == ("p", "us-east5")

    def test_explicit_project_wins_over_the_key_file(self, tmp_path, monkeypatch):
        """The key's project is the default, not the only choice: quota can be
        billed to a different project than the one the key belongs to."""
        monkeypatch.setenv(
            "GOOGLE_APPLICATION_CREDENTIALS", self._key_file(tmp_path, project_id="from-key")
        )
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "explicit")
        llm.resolve_model("google-cloud:gemini-3.7-flash")
        assert self.projects == ["explicit"]

    def test_refuses_before_touching_credentials(self):
        """An API key must never stand in for Google Cloud credentials.

        pydantic-ai's own provider inference falls back to Vertex AI Express
        Mode when GOOGLE_API_KEY is set and nothing else is — a different
        product, silently, under the model string that asked for a service
        account. Passing an explicit project is what shuts that path off, so
        with no project there is nothing safe to build.
        """
        with pytest.raises(ModelConfigError) as caught:
            llm.resolve_model("google-cloud:gemini-3.7-flash")
        assert self.calls == []
        message = str(caught.value)
        assert "GOOGLE_APPLICATION_CREDENTIALS" in message
        assert "GOOGLE_CLOUD_PROJECT" in message

    @pytest.mark.parametrize("contents", ["not json at all", '{"type": "service_account"}', "[]"])
    def test_unusable_key_file_is_not_a_project(self, tmp_path, monkeypatch, contents):
        path = tmp_path / "sa.json"
        path.write_text(contents)
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(path))
        with pytest.raises(ModelConfigError):
            llm.resolve_model("google-cloud:gemini-3.7-flash")
        assert self.calls == []

    def test_missing_key_file_is_not_a_project(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "nope.json"))
        with pytest.raises(ModelConfigError):
            llm.resolve_model("google-cloud:gemini-3.7-flash")
        assert self.calls == []

    def test_build_agent_routes_through_the_provider(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "GOOGLE_APPLICATION_CREDENTIALS", self._key_file(tmp_path, project_id="p")
        )

        class Out(BaseModel):
            value: str

        agent = build_agent(
            "google-cloud:gemini-3.7-flash", Out, "instructions", effort=Effort.high
        )
        assert self.projects == ["p"]
        assert agent.model.model_name == "gemini-3.7-flash"


class TestVertexAuthPath:
    """The seam is stubbed above; this pins the real provider's behaviour.

    Constructing GoogleCloudProvider is offline — google-genai resolves
    credentials lazily at request time — so the auth route it picked is
    readable without a network call.
    """

    def test_an_api_key_cannot_stand_in_for_a_service_account(self, tmp_path, monkeypatch):
        key = tmp_path / "sa.json"
        key.write_text(json.dumps({"type": "service_account", "project_id": "real-project"}))
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key))
        monkeypatch.setenv("GOOGLE_API_KEY", "an-api-key-for-the-gemini-api")
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)

        model = llm.resolve_model("google-cloud:gemini-3.7-flash")

        # The project is what shuts the API-key path off, so both halves matter.
        # Note the endpoint cannot be the discriminator: Vertex's `global`
        # location and Express Mode share aiplatform.googleapis.com.
        client = model.client._api_client
        assert client.project == "real-project"
        assert client.location == "global"
        assert client.api_key is None
        assert llm.GOOGLE_CLOUD in model.system
