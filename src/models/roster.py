"""Model roster.

Logical name -> OpenRouter model + provider pin + CoT-access mode + per-model necessity
status, loaded from `configs/models.yaml` (never hardcode IDs).
Encapsulates how each model exposes / disables its reasoning so experiments can request
"the actor's reasoning trace" and get it regardless of provider quirks.

`build_model(name)` returns an Inspect `Model` with two things wired from Phase-0:
  * provider pin  -> model arg `provider={"only":[tag], "allow_fallbacks": False}`
                     (exact endpoint/quant, or fail loudly — reproducibility).
  * CoT-access    -> model arg `reasoning_enabled` (e.g. False = the GPT-5.5 / Gemini-flash
                     hidden-channel disable lock; the OpenRouter provider maps it to
                     extra_body.reasoning.enabled).

CoT-access modes (CORE PRINCIPLE: faithful actor needs channel-disable AND the task
CoT-necessary for *that* model — raw exposure ≠ necessity):
  native_raw    open weights, raw faithful trace via `reasoning`
  summary       closed models — reasoning field is a SUMMARY (not faithful)
  body_channel  reasoning routed into the message body (agentic / faithful-trace replication)
  disabled      hidden channel OFF (reasoning:{enabled:false}) -> body CoT we can judge

Log version + provider + mode + necessity per run (see `describe`).
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from inspect_ai.model import GenerateConfig, Model, get_model

# ── CoT-access modes ──
NATIVE_RAW = "native_raw"
SUMMARY = "summary"
BODY_CHANNEL = "body_channel"
DISABLED = "disabled"

# ── tiers ──
FAITHFUL_HINTS = "faithful_hints"
MONITOR = "monitor"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(os.environ.get("COT_MON_MODELS_CONFIG", _REPO_ROOT / "configs" / "models.yaml"))

_UNSET = object()  # sentinel so callers can override reasoning_enabled to None explicitly


@functools.lru_cache(maxsize=4)
def _served_context() -> int:
    """The self-host vLLM endpoint's max_model_len (for the max_tokens cap). One cached GET to
    /v1/models; falls back to $VLLM_MAX_MODEL_LEN or 8192 if the endpoint is unreachable at build."""
    import json
    import urllib.request
    try:
        base = os.environ.get("VLLM_BASE_URL", "").rstrip("/")
        key = os.environ.get("VLLM_API_KEY", "") or "x"
        req = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {key}"})
        d = json.load(urllib.request.urlopen(req, timeout=10))
        return int(d["data"][0].get("max_model_len") or 8192)
    except Exception:
        return int(os.environ.get("VLLM_MAX_MODEL_LEN", "8192"))


@dataclass(frozen=True)
class RosterEntry:
    """One model's resolved roster spec (pure data; no network)."""

    name: str
    kind: str  # "actor" | "monitor"
    id: str  # openrouter/<provider>/<model>
    provider: str | None  # pinned endpoint tag
    cot_access: str | None
    reasoning_enabled: bool | None
    tier: str | None
    necessity: str | None
    experiments: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    no_cot_mechanism: str = "prefill"  # "prefill" | "structured_output" | "vllm_structured"
    #   (prefill-rejecting actors: Opus 4.8 -> structured_output; self-host vLLM qwen3.5 ->
    #   vllm_structured = single-letter schema + chat_template_kwargs enable_thinking:false)
    reasoning_effort: str | None = None  # OpenRouter reasoning.effort (minimal/low/...); the ONLY
    #   hidden-channel disable for mandatory-reasoning Flash models (e.g. gemini-3.5-flash:
    #   effort=minimal -> rtoks=0, reasons in body; enabled:false/max_tokens:0 both 400).
    notes: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def provider_pin(self) -> dict[str, Any] | None:
        """OpenRouter `provider` routing arg pinning this exact endpoint."""
        if not self.provider:
            return None
        return {"only": [self.provider], "allow_fallbacks": False}


def _coerce(name: str, kind: str, spec: dict[str, Any]) -> RosterEntry:
    if "id" not in spec:
        raise ValueError(f"roster entry {name!r} is missing required field 'id'")
    return RosterEntry(
        name=name,
        kind=kind,
        id=spec["id"],
        provider=spec.get("provider"),
        cot_access=spec.get("cot_access"),
        reasoning_enabled=spec.get("reasoning_enabled"),
        tier=spec.get("tier"),
        necessity=spec.get("necessity"),
        experiments=tuple(spec.get("experiments", ()) or ()),
        roles=tuple(spec.get("role", ()) or ()),
        no_cot_mechanism=spec.get("no_cot_mechanism", "prefill"),
        reasoning_effort=spec.get("reasoning_effort"),
        notes=spec.get("notes"),
        raw=spec,
    )


_CACHE: dict[str, dict[str, RosterEntry]] = {}


def load_roster(path: Path | str = DEFAULT_CONFIG, *, refresh: bool = False) -> dict[str, RosterEntry]:
    """Parse models.yaml into {logical_name: RosterEntry}. Pure + cached."""
    key = str(Path(path))
    if refresh or key not in _CACHE:
        cfg = yaml.safe_load(Path(path).read_text()) or {}
        entries: dict[str, RosterEntry] = {}
        for kind in ("actors", "monitors"):
            for name, spec in (cfg.get(kind) or {}).items():
                singular = "actor" if kind == "actors" else "monitor"
                entries[name] = _coerce(name, singular, spec or {})
        _CACHE[key] = entries
    return _CACHE[key]


def get_entry(name: str, *, path: Path | str = DEFAULT_CONFIG) -> RosterEntry:
    roster = load_roster(path)
    if name not in roster:
        raise KeyError(f"unknown model {name!r}; known: {sorted(roster)}")
    return roster[name]


def actors_for(experiment: str, *, path: Path | str = DEFAULT_CONFIG) -> list[RosterEntry]:
    """Actors whose config lists `experiment` (e.g. 'hints')."""
    return [e for e in load_roster(path).values()
            if e.kind == "actor" and experiment in e.experiments]


def build_model(
    name: str,
    *,
    config: GenerateConfig | None = None,
    reasoning_enabled: Any = _UNSET,
    path: Path | str = DEFAULT_CONFIG,
    **extra_model_args: Any,
) -> Model:
    """Construct the Inspect `Model` for `name` with its provider pin + reasoning setting.

    `reasoning_enabled` defaults to the config value; pass an explicit bool/None to override
    per call (e.g. run an otherwise channel-disabled actor with reasoning ON for a contrast).
    No network happens here — only at generate time.
    """
    e = get_entry(name, path=path)
    cfg = config or GenerateConfig()
    if e.id.startswith("openai-api/"):
        # Self-hosted vLLM (OpenAI-compatible endpoint) via inspect's `openai-api` provider: it reads
        # <PREFIX>_BASE_URL / <PREFIX>_API_KEY from env off the id's service segment (id
        # openai-api/vllm/<model> -> service `vllm` -> VLLM_BASE_URL + VLLM_API_KEY). The OpenRouter-only
        # knobs do NOT apply here: no `provider` routing pin and no `reasoning_enabled` model arg (both
        # are OpenRouter extra_body maps). Keep temperature/top_p as-is (not the anthropic strip path).
        # The vLLM thinking toggle / structured no-CoT arm rides on GenerateConfig.extra_body at generate
        # time (see src/exp_hints/solver.py NO_COT_VLLM_STRUCTURED), not on a model arg here.
        margs: dict[str, Any] = dict(extra_model_args)
        # Dedicated endpoint -> push concurrency: inspect defaults max_connections to 10, which would
        # throttle the with-CoT arm below a big --concurrency. Let many requests be in flight (the
        # script's semaphore is the real bound). Override via VLLM_MAX_CONNECTIONS.
        if cfg.max_connections is None:
            cfg = cfg.model_copy(update={"max_connections": int(os.environ.get("VLLM_MAX_CONNECTIONS", "256"))})
        # Cap max_tokens to the served context window so prompt+max_tokens never 400s. gpt-oss
        # over-reasons and the reasoning-floor (8000) would exceed an 8192 ctx. Auto-widens when the
        # human raises --max-model-len. Reserve room for the prompt (VLLM_TOKENS_RESERVE).
        if cfg.max_tokens:
            cap = max(256, _served_context() - int(os.environ.get("VLLM_TOKENS_RESERVE", "2048")))
            if cfg.max_tokens > cap:
                cfg = cfg.model_copy(update={"max_tokens": cap})
        return get_model(e.id, config=cfg, **margs)
    if e.id.startswith("anthropic/"):
        # Opus 4.8 (and the 4.6+/Fable family) REJECT temperature/top_p/top_k with a 400 — strip
        # them on the native anthropic path (the sweep sets temperature=0.7). reasoning_enabled is an
        # OpenRouter arg and is not forwarded here either (thinking-off = omit the thinking config).
        cfg = cfg.model_copy(update={"temperature": None, "top_p": None, "top_k": None})
    # reasoning.effort (OpenRouter): for mandatory-reasoning Flash models this is the channel-disable
    # knob (gemini-3.5-flash: effort=minimal -> rtoks=0). Forwarded only on the OpenRouter path.
    if e.reasoning_effort is not None and not e.id.startswith("anthropic/"):
        cfg = cfg.model_copy(update={"reasoning_effort": e.reasoning_effort})
    margs: dict[str, Any] = {}
    if e.provider_pin is not None:
        margs["provider"] = e.provider_pin
    re_val = e.reasoning_enabled if reasoning_enabled is _UNSET else reasoning_enabled
    if re_val is not None and not e.id.startswith("anthropic/"):
        margs["reasoning_enabled"] = re_val
    margs.update(extra_model_args)
    return get_model(e.id, config=cfg, **margs)


def judged_cot_source(cot_access: str | None) -> str:
    """Which part of a `generate()` output holds this actor's REAL reasoning trace — the field the
    hint judge must read (channel-aware capture):

      native_raw            -> "reasoning"  open weights: raw CoT in the `reasoning` field
                                            (Inspect surfaces it as a ContentReasoning block,
                                            separate from `.completion`)
      body_channel/disabled -> "body"       Gemini thinking-disabled / GPT-5.5 channel-off: the CoT
                                            IS the message body (`.completion`)
      summary / None        -> "none"       mandatory hidden channel / summary-only — NOT judgeable
                                            (judging it would measure the summary's faithfulness)
    """
    if cot_access == NATIVE_RAW:
        return "reasoning"
    if cot_access in (BODY_CHANNEL, DISABLED):
        return "body"
    return "none"


def describe(name: str, *, path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    """Per-run log record: provider + CoT-access mode + necessity status."""
    e = get_entry(name, path=path)
    return {
        "name": e.name, "id": e.id, "provider": e.provider,
        "cot_access": e.cot_access, "cot_source": judged_cot_source(e.cot_access),
        "reasoning_enabled": e.reasoning_enabled,
        "tier": e.tier, "necessity": e.necessity,
        "no_cot_mechanism": e.no_cot_mechanism,
    }
