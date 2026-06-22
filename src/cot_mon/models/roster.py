"""Model roster — SPEC §4.0.

Logical name -> OpenRouter model + provider pin + CoT-access mode + per-model necessity
status + uplift-set id, loaded from `configs/models.yaml` (never hardcode IDs — CLAUDE.md).
Encapsulates how each model exposes / disables its reasoning so experiments can request
"the actor's reasoning trace" and get it regardless of provider quirks.

`build_model(name)` returns an Inspect `Model` with two things wired from Phase-0:
  * provider pin  -> model arg `provider={"only":[tag], "allow_fallbacks": False}`
                     (exact endpoint/quant, or fail loudly — reproducibility, CLAUDE.md).
  * CoT-access    -> model arg `reasoning_enabled` (e.g. False = the GPT-5.5 / Gemini-flash
                     hidden-channel disable lock; the OpenRouter provider maps it to
                     extra_body.reasoning.enabled).

CoT-access modes (CLAUDE.md CORE PRINCIPLE: faithful actor needs channel-disable AND the task
CoT-necessary for *that* model — raw exposure ≠ necessity):
  native_raw    open weights, raw faithful trace via `reasoning`
  summary       closed models — reasoning field is a SUMMARY (not faithful)
  body_channel  reasoning routed into the message body (agentic / faithful-trace replication)
  disabled      hidden channel OFF (reasoning:{enabled:false}) -> body CoT we can judge

Log version + provider + mode + necessity per run (see `describe`).
"""

from __future__ import annotations

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

# ── tiers (SPEC §3) ──
FAITHFUL_HINTS_GRADIENT = "faithful_hints_gradient"
FAITHFUL_CONDITIONAL = "faithful_conditional"
FAITHFUL_AGENTIC = "faithful_agentic"
GENERALIZATION_ONLY = "generalization_only"
MONITOR = "monitor"

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = Path(os.environ.get("COT_MON_MODELS_CONFIG", _REPO_ROOT / "configs" / "models.yaml"))

_UNSET = object()  # sentinel so callers can override reasoning_enabled to None explicitly


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
    uplift_set: str | None
    experiments: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
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
        uplift_set=spec.get("uplift_set"),
        experiments=tuple(spec.get("experiments", ()) or ()),
        roles=tuple(spec.get("role", ()) or ()),
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
    """Actors whose config lists `experiment` (e.g. 'hints', 'gradient', 'oversight')."""
    return [e for e in load_roster(path).values()
            if e.kind == "actor" and experiment in e.experiments]


def by_tier(tier: str, *, path: Path | str = DEFAULT_CONFIG) -> list[RosterEntry]:
    return [e for e in load_roster(path).values() if e.tier == tier]


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
    margs: dict[str, Any] = {}
    if e.provider_pin is not None:
        margs["provider"] = e.provider_pin
    re_val = e.reasoning_enabled if reasoning_enabled is _UNSET else reasoning_enabled
    if re_val is not None:
        margs["reasoning_enabled"] = re_val
    margs.update(extra_model_args)
    return get_model(e.id, config=config or GenerateConfig(), **margs)


def describe(name: str, *, path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    """Per-run log record (CLAUDE.md: log provider + mode + necessity)."""
    e = get_entry(name, path=path)
    return {
        "name": e.name, "id": e.id, "provider": e.provider,
        "cot_access": e.cot_access, "reasoning_enabled": e.reasoning_enabled,
        "tier": e.tier, "necessity": e.necessity, "uplift_set": e.uplift_set,
    }
