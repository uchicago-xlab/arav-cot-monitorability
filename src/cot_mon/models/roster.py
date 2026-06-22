"""Model roster — SPEC §3.1.

Logical name -> OpenRouter model + provider pin + CoT-access mode, loaded from
`configs/models.yaml` (never hardcode IDs — CLAUDE.md). Encapsulates the
CoT-access mode so experiments can request "the actor's reasoning trace" and get
it regardless of how the provider exposes it.

CoT-access modes:
  native_raw       open weights via the `reasoning` field
  summary          closed models via summarized/encrypted `reasoning_details`
  body_channel     reasoning forced into the message body (all agentic runs +
                   closed/Gemini faithful-trace replication)
  native_disabled  Gemini 2.5 Pro thinking off (App. C.3)

Log version + resolved provider + mode per run.

TODO(SPEC §3.1): load configs/models.yaml; resolve logical name -> Inspect model
with provider pin + reasoning routing per CoT-access mode.
"""

from __future__ import annotations

# CoT-access modes (see module docstring).
NATIVE_RAW = "native_raw"
SUMMARY = "summary"
BODY_CHANNEL = "body_channel"
NATIVE_DISABLED = "native_disabled"
