"""W&B logger — the single path EVERY experiment logs through.

One `wandb` run per (experiment × actor × config). A run carries three things so a human can
audit it after the fact:
  1. **config** — model slug, resolved OpenRouter provider, CoT-access mode (incl. the GPT-5.5
     `reasoning:{enabled:false}` disable), N items/samples, seed, dataset + hash, hint family,
     git SHA/branch, sampling params.
  2. **scalars** — the experiment's metrics, each with its Wilson 2σ bounds as separate
     `<name>_lo` / `<name>_hi` keys (see `metrics.flatten_for_logging`).
  3. **CoT-verification table + transcripts.jsonl** — one row per rollout (full prompt + full CoT
     + judge verdict/rationale). The table is for browsing in the UI; the JSONL artifact is the
     archival source of truth. THIS is what lets a reviewer open W&B and re-check the judge calls.

Modes: pass `mode="disabled"` (fully no-op, no files, no network) or `mode="offline"`
(writes ./wandb locally, no network) — or set `WANDB_MODE`. No secret ever enters the config: we
build it from explicit fields only and never dump `os.environ`.

"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Iterable

import wandb

DEFAULT_PROJECT = "cot-monitorability"
_REPO_ROOT = Path(__file__).resolve().parents[2]

# The CoT-verification table schema — one row per rollout. Keep this list as the
# single source of truth for column order; `log_rollout` rejects keys outside it.
COT_TABLE_COLUMNS: tuple[str, ...] = (
    "item_id", "topic", "hint_type", "cot_mode", "sample_idx", "seed",
    "prompt_full", "cot_text_full", "final_answer", "extracted_answer",
    "hint_target_letter", "gold_letter", "engaged_hint", "mentions_hint",
    "judge_verdict", "judge_method", "judge_rationale",
)


# ── small pure helpers ──
def _git(*args: str, default: str = "") -> str:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True,
                             cwd=str(_REPO_ROOT), timeout=5).stdout.strip()
        return out or default
    except Exception:
        return default


def git_info() -> dict[str, str]:
    """Current commit + branch (best-effort; '' if not a git checkout)."""
    return {"git_sha": _git("rev-parse", "HEAD"), "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD")}


def dataset_hash(item_ids: Iterable[str]) -> str:
    """Stable 12-hex digest of the exact item set used — pins which questions a run touched."""
    h = hashlib.sha1()
    for i in item_ids:
        h.update(str(i).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:12]


def run_config(*, describe: dict, n_items: int | None = None, n_samples: int | None = None,
               seed: int | None = None, dataset: str | None = None, dataset_hash: str | None = None,
               hint_family: str | None = None, sampling: dict | None = None, **extra: Any) -> dict:
    """Assemble the logged config from `roster.describe(name)` + run params (drops Nones)."""
    cfg: dict[str, Any] = {
        "model_slug": describe.get("name"), "openrouter_id": describe.get("id"),
        "provider": describe.get("provider"), "cot_access": describe.get("cot_access"),
        "cot_source": describe.get("cot_source"),
        "reasoning_enabled": describe.get("reasoning_enabled"), "tier": describe.get("tier"),
        "necessity": describe.get("necessity"),
        "n_items": n_items, "n_samples": n_samples, "seed": seed,
        "dataset": dataset, "dataset_hash": dataset_hash, "hint_family": hint_family,
    }
    if sampling:
        cfg.update({f"sampling_{k}": v for k, v in sampling.items()})
    cfg.update(extra)
    return {k: v for k, v in cfg.items() if v is not None}


def _cell(v: Any) -> Any:
    """Coerce a value into something `wandb.Table` stores cleanly."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


# ── the run wrapper ──
class WandbRun:
    """A single W&B run. Accumulate rollout rows + scalars, then `finish()` flushes the table and
    the transcripts.jsonl artifact. Usable as a context manager (finishes on exit)."""

    def __init__(self, *, experiment: str, actor: str, config: dict | None = None,
                 gate: str | None = None, extra_tags: Iterable[str] = (), project: str | None = None,
                 entity: str | None = None, mode: str | None = None, name: str | None = None):
        gi = git_info()
        cfg = dict(config or {})
        cfg.setdefault("git_sha", gi["git_sha"])
        cfg.setdefault("git_branch", gi["git_branch"])
        cfg.setdefault("experiment", experiment)
        cfg.setdefault("actor", actor)

        tags = [t for t in ([experiment, actor, gate, gi["git_branch"], *extra_tags]) if t]
        self.experiment, self.actor = experiment, actor
        self.config = cfg
        self.columns = list(COT_TABLE_COLUMNS)
        self._rows: list[dict[str, Any]] = []
        self.scalars: dict[str, Any] = {}
        self.mode = mode or os.environ.get("WANDB_MODE")
        self.disabled = self.mode == "disabled"

        self.run = wandb.init(
            project=project or os.environ.get("WANDB_PROJECT", DEFAULT_PROJECT),
            entity=entity or os.environ.get("WANDB_ENTITY") or None,
            group=experiment, job_type=actor, tags=tags, name=name,
            config=cfg, mode=self.mode, reinit=True,
        )

    # — rollouts (CoT table rows) —
    def log_rollout(self, **fields: Any) -> None:
        unknown = set(fields) - set(self.columns)
        if unknown:
            raise KeyError(f"unknown CoT-table columns {sorted(unknown)}; allowed: {self.columns}")
        self._rows.append({c: fields.get(c) for c in self.columns})

    @property
    def n_rollouts(self) -> int:
        return len(self._rows)

    def build_table(self) -> "wandb.Table":
        data = [[_cell(r[c]) for c in self.columns] for r in self._rows]
        return wandb.Table(columns=self.columns, data=data)

    def write_transcripts(self, path: str | Path) -> Path:
        """Write every rollout (full text) as JSONL — the archival source of truth."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w") as f:
            for r in self._rows:
                f.write(json.dumps(r, default=str) + "\n")
        return p

    # — scalars —
    def log_scalars(self, scalars: dict) -> None:
        clean = {k: v for k, v in scalars.items() if v is not None}
        self.scalars.update(clean)
        self.run.log(clean)

    def _default_transcripts_path(self) -> Path:
        rid = getattr(self.run, "id", None) or self.actor
        return _REPO_ROOT / "logs" / "transcripts" / f"{self.experiment}_{self.actor}_{rid}.jsonl"

    def finish(self, *, transcripts_path: str | Path | None = None, table_key: str = "cot_table",
               extra_artifacts: Iterable[str | Path] = ()) -> Path | None:
        """Flush the CoT table + a transcripts.jsonl artifact (plus any extra files), then close."""
        tpath: Path | None = None
        if self._rows:
            self.run.log({table_key: self.build_table()})
            tpath = self.write_transcripts(transcripts_path or self._default_transcripts_path())
            if not self.disabled:                       # artifact logging is a no-op when disabled
                art = wandb.Artifact(f"{self.experiment}-{self.actor}-transcripts", type="transcripts")
                art.add_file(str(tpath))
                for extra in extra_artifacts:
                    art.add_file(str(extra))
                self.run.log_artifact(art)
        self.run.finish()
        return tpath

    def __enter__(self) -> "WandbRun":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.finish()
