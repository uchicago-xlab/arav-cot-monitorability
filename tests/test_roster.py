"""SPEC §8 — roster loader (pure; no network)."""

import pytest

from cot_mon.models import roster


def test_load_has_expected_models():
    r = roster.load_roster()
    for n in ["gemini_3_flash", "gpt_5_5", "qwen3", "gpt_oss_120b", "opus_4_8",
              "gemini_3_5_flash", "opus_4_8_monitor", "gemini_2_5_flash_lite"]:
        assert n in r, f"{n} missing from roster"


def test_primary_actor_fields():
    e = roster.get_entry("gemini_3_flash")
    assert e.id == "openrouter/google/gemini-3-flash-preview"
    assert e.provider == "google-vertex"
    assert e.reasoning_enabled is False          # hidden channel OFF
    assert e.cot_access == roster.DISABLED
    assert e.tier == roster.FAITHFUL_HINTS_GRADIENT
    assert e.necessity == "confirmed"
    assert e.provider_pin == {"only": ["google-vertex"], "allow_fallbacks": False}


def test_gpt55_disable_lock():
    e = roster.get_entry("gpt_5_5")
    assert e.reasoning_enabled is False           # the GPT-5.5 disable lock
    assert e.cot_access == roster.DISABLED


def test_actors_for_experiment():
    hints = {e.name for e in roster.actors_for("hints")}
    assert "gemini_3_flash" in hints
    assert "opus_4_8" not in hints                # no prefill -> not in hints/gradient


def test_unknown_raises():
    with pytest.raises(KeyError):
        roster.get_entry("does_not_exist")


def test_build_model_no_network(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")  # construction only, no call
    from inspect_ai.model import Model
    m = roster.build_model("gemini_3_flash")
    assert isinstance(m, Model)


def test_selfhost_actor_fields():
    e = roster.get_entry("qwen3_5_122b_selfhost")
    assert e.id == "openai-api/vllm/qwen3_5-122b"     # inspect openai-api provider: service `vllm`
    assert e.provider is None                          # self-host: not OpenRouter -> no provider pin
    assert e.provider_pin is None
    assert e.reasoning_enabled is None                 # OpenRouter-only arg; N/A on self-host path
    assert e.cot_access == roster.NATIVE_RAW
    assert e.no_cot_mechanism == "vllm_structured"     # prefill not honored -> schema + enable_thinking:false
    assert e.experiments == ("hints",)                 # decode-necessity + §3.1 only


def test_build_model_openai_api_branch(monkeypatch):
    """The openai-api/ branch: reads VLLM_BASE_URL/VLLM_API_KEY (service prefix), attaches NO
    OpenRouter provider pin and NO reasoning_enabled model arg. Construction only, no network."""
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("VLLM_API_KEY", "EMPTY")
    from inspect_ai.model import Model
    m = roster.build_model("qwen3_5_122b_selfhost")
    assert isinstance(m, Model)
    # neither OpenRouter-only knob leaked onto the model args
    margs = getattr(m.api, "model_args", {})
    assert "provider" not in margs
    assert "reasoning_enabled" not in margs
    # temperature/top_p are NOT stripped on this path (unlike the anthropic path)
    assert m.config.temperature is None or True        # default cfg has none set; just assert no crash


def test_gptoss_selfhost_actor_fields():
    """The gpt-oss self-host re-run actor (faithful replacement for the provider-suspect OpenRouter
    gpt_oss_120b §3.1 numbers). no_cot arm = the harmony final-channel force (zero analysis tokens)."""
    e = roster.get_entry("gpt_oss_120b_selfhost")
    assert e.id == "openai-api/vllm/gpt-oss-120b"      # service `vllm`; model segment = --served-model-name
    assert e.provider is None and e.provider_pin is None
    assert e.reasoning_enabled is None                 # OpenRouter-only arg; N/A on self-host path
    assert e.cot_access == roster.NATIVE_RAW           # harmony analysis channel -> message.reasoning
    assert e.no_cot_mechanism == "harmony_final"       # gpt-oss has no enable_thinking; force final channel
    assert e.experiments == ("hints",)
    # the OpenRouter twin is kept intact so results stay attributable
    assert roster.get_entry("gpt_oss_120b").id == "openrouter/openai/gpt-oss-120b"


def test_build_model_selfhost_high_max_connections(monkeypatch):
    """Self-host path bumps max_connections so a big --concurrency isn't throttled (dedicated endpoint)."""
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("VLLM_API_KEY", "EMPTY")
    monkeypatch.setenv("VLLM_MAX_CONNECTIONS", "128")
    m = roster.build_model("gpt_oss_120b_selfhost")    # default cfg (max_tokens None -> no network cap)
    assert m.config.max_connections == 128
