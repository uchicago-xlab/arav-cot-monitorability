#!/usr/bin/env python3
"""§3.1 REPLICATION (Gate-1 sweep) figures → figures/3p1_replication/ (SPEC_phase2 Step 3 / figure
rules). Reads per-actor logs/sweep_<actor>.json (whatever has completed), renders 4 figures, and
logs them to W&B (wandb.Image + the underlying numbers as a wandb.Table). Re-run as each actor lands.

  0 PAPER ANALOG (Emmons et al. §3.1 Fig 3): per judgeable actor, stacked take-the-hint bars over
    {no-hint, simple, complex} split mention vs conceal. Reads RAW per-rollout transcripts (NOT the
    summary path), since this split is not in the pre-aggregated sweep_<actor>.json.            [REPLICATION]
  1 HEADLINE (Gate 1): simple-hint unfaithfulness delta per actor, Wilson 2σ        [REPLICATION]
  2 Necessity-gated complex (DEMOTED — not a standalone result): no clean CoT-necessary∩followed
    window exists in this follow-based sweep → redirects to the decode-necessity figs C1/C2.
  3 Follow-rate uplift bars: with-CoT − no-CoT FOLLOW-rate per actor×level, Newcombe 2σ,  [EXTENSION]
    threshold +0.5; one-shot / declines / CoT-necessary coloured distinctly (NOT decode accuracy —
    that's C1/C2; low follow in both arms = declines, not too-hard)
  4 Follow-rate panel: simple + complex follow_rate per actor×level (the denominators)

Honesty rules enforced: a one-shot / declined / zero-follower cell is rendered distinctly (grey
hatch / its raw (with-CoT,no-CoT) pair) — NEVER as a plain 0% bar.

  uv run python scripts/make_figures.py            # all completed actors, log to W&B
  uv run python scripts/make_figures.py --no-wandb
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from cot_mon import figviz, metrics  # noqa: E402
from cot_mon.metrics import load_withcot_rollouts  # noqa: E402  (explicit-selector transcript loader)

# gpt-oss-120b is represented ONLY by the faithful self-host (vLLM) re-run — the provider-suspect
# OpenRouter run is dropped everywhere (per Arav). It carries the plain "gpt-oss-120b" label so the
# figures keep the earlier composition (one gpt-oss row, no OR/vLLM tags).
ORDER = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5", "gpt_oss_120b_selfhost",
         "qwen3_30b", "qwen3_5_122b", "deepseek_v4_flash", "opus_4_8_direct", "gemini_3_1_pro"]
LABEL = {"gemini_2_5_flash": "gemini-2.5-flash\n(paper)", "gemini_3_flash": "gemini-3-flash",
         "gemini_3_5_flash": "gemini-3.5-flash", "gpt_5_5": "gpt-5.5",
         "gpt_oss_120b_selfhost": "gpt-oss-120b",
         "qwen3_30b": "qwen3-30b", "qwen3_5_122b": "qwen3.5-122b", "deepseek_v4_flash": "deepseek-v4-flash",
         "opus_4_8_direct": "opus-4.8\n(struct no-CoT†)", "gemini_3_1_pro": "gemini-3.1-pro\n(gen-only‡)"}
LEVELS = ["complex_L1", "complex_L2", "complex_L3"]
LV_SHORT = {"complex_L1": "L1", "complex_L2": "L2", "complex_L3": "L3"}
FIGDIR = Path("figures/3p1_replication")

# Fig 0 (paper analog): actors whose with-CoT trace is genuinely judgeable — gemini-2.5-flash
# (reasoning=none body), gemini-3-flash + gemini-3.5-flash (channel-disabled: enabled:false resp.
# effort:minimal -> rtoks=0, body CoT), gpt-5.5 (reasoning:{enabled:false} body), gpt-oss-120b +
# deepseek-v4-flash + qwen3.5-122b native_raw (CoT in the reasoning field), opus-4.8-direct (body,
# structured no-CoT †). For each the transcript's judge_verdict was scored cot_source-aware at sweep
# time, so the loader just reads it. gemini-3.1-pro (‡) is GENERALIZATION-ONLY — mandatory hidden
# reasoning (effort:minimal only REDUCES it, never to 0), so we judge its VISIBLE body, NOT a faithful
# hidden trace; included as a caveated datapoint per the user, not a faithful-actor headline.
JUDGEABLE = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5",
             "gpt_oss_120b_selfhost", "qwen3_5_122b", "deepseek_v4_flash", "opus_4_8_direct", "gemini_3_1_pro"]
ACTOR_COLOR = {"gemini_2_5_flash": "#444444", "gemini_3_flash": "#1b9e77",
               "gemini_3_5_flash": "#66a61e", "gpt_5_5": "#d95f02",
               "gpt_oss_120b_selfhost": "#7570b3",
               "qwen3_5_122b": "#a6761d", "deepseek_v4_flash": "#e7298a",
               "opus_4_8_direct": "#1f78b4", "gemini_3_1_pro": "#999999"}

# Fig 0 transcript SETS — the experiment prefix is the data selector (see resolve_transcript). The
# framing is "does the §3.1 follow-rate effect survive WITHOUT the item gate", NOT "the gate was
# wrong": for these channel-disabled actors a true no-CoT necessity arm is confounded, which is why
# necessity is measured separately (the decode sweep) rather than used as the §3.1 item gate.
FIG0_SETS = {
    "filtered": dict(experiment="exp_hints_sweep", suffix="",
                     set_label="FILTERED set — correct-with-CoT item gate ON (paper §5-style precondition)"),
    "unfiltered": dict(experiment="exp_hints_sweep_unfiltered", suffix="_unfiltered",
                       set_label="UNFILTERED set — correct-with-CoT item gate BYPASSED (--no-filter): "
                                 "does the §3.1 follow-rate effect survive without the item gate?"),
}


def _parse_pins(specs):
    """`ACTOR=RUNID_OR_PATH` strings → {actor: (run_id, path)}. A value that looks like a path
    (contains a separator / ends .jsonl / exists on disk) is taken as a path, else a run-id."""
    pins = {}
    for s in specs or []:
        actor, sep, val = s.partition("=")
        if not sep or not val:
            raise SystemExit(f"--fig0-transcript expects ACTOR=RUNID_OR_PATH, got {s!r}")
        looks_path = ("/" in val) or val.endswith(".jsonl") or Path(val).exists()
        pins[actor] = (None, val) if looks_path else (val, None)
    return pins


def load():
    out = {}
    for name in ORDER:
        p = Path(f"logs/sweep_{name}.json")
        if p.exists():
            out[name] = json.loads(p.read_text())["summary"]
    return out


# The explicit-selector transcript loader lives in cot_mon.metrics (so the cluster bootstrap can read
# the same per-rollout data); imported at the top as `load_withcot_rollouts`. The pins → CIs helpers
# below build on it.


def _boot_for(actors, *, pins, n_boot, seed):
    """Item-level cluster-bootstrap CIs per actor (FILTERED set), via metrics.bootstrap_sweep_cis.
    {actor: {"n_items", "cis": {...}}}; actors with no transcript (or an ambiguous glob) are skipped
    with a note. These CIs feed Figs 0/1/4/5 — point estimates are unchanged, only intervals widen."""
    out = {}
    for a in actors:
        rid, path = pins.get(a, (None, None))
        try:
            b = metrics.bootstrap_sweep_cis(a, experiment="exp_hints_sweep", run_id=rid, path=path,
                                            n_boot=n_boot, seed=seed)
        except ValueError as e:
            print(f"  [bootstrap skipped for {a}: {e}]")
            b = None
        if b:
            out[a] = b
    return out


def _condition(hint_type):
    """Map a per-rollout hint_type to the paper's 3 conditions, COLLAPSING complex_L1/L2/L3 → complex."""
    if hint_type == "none":
        return "none"
    if hint_type == "simple":
        return "simple"
    if hint_type.startswith("complex"):
        return "complex"
    return None


def _take_split(rows):
    """Per condition: take-the-hint count split into mention (strict judge_verdict True) vs conceal.
    'Takes the hint' = engaged_hint / picks_hinted; over ALL items (no necessity gating)."""
    agg = {c: {"n": 0, "mention": 0, "conceal": 0} for c in ("none", "simple", "complex")}
    for r in rows:
        c = _condition(r.get("hint_type", ""))
        if c is None:
            continue
        agg[c]["n"] += 1
        if r.get("engaged_hint"):                          # picks the hinted (wrong) letter
            if r.get("judge_verdict") is True:             # STRICT: judge says hint used as the reason
                agg[c]["mention"] += 1
            else:                                          # picked it but did NOT reveal the cue
                agg[c]["conceal"] += 1
    return agg


def _lohi(stat):
    """Asymmetric Wilson error-bar arms [[down],[up]] for plt.errorbar."""
    return [[max(0, stat["p"] - stat["lo"])], [max(0, stat["hi"] - stat["p"])]]


def _n(summary, kind):
    c = summary.get(kind)
    return c["follow_withcot"]["n"] if c else 0


def _caption(summaries, extra="", ci="Wilson 2σ"):
    items = max((s.get("n_items", 0) for s in summaries.values()), default=0)
    spc = max((_n(s, "simple") for s in summaries.values()), default=0)
    sm = spc // items if items else 0
    base = f"GPQA · {items} items × {sm} samples/cell · correct-with-CoT filtered"
    return base + (f" · {ci}" if ci else "") + extra


# CI label for the four headline figures that use the item-level cluster bootstrap (Figs 0/1/4/5).
BOOT_CI = "item-cluster bootstrap 2σ (resamples items, not samples)"


def _boot_err(point, ci, *, clamp=None):
    """Asymmetric error-bar arms [[down],[up]] from a bootstrap {p,lo,hi}, anchored at the EXISTING
    `point` (point estimates never move). `clamp`=(lo,hi) optionally bounds the drawn whisker."""
    lo, hi = ci["lo"], ci["hi"]
    if clamp is not None:
        lo, hi = max(clamp[0], lo), min(clamp[1], hi)
    return [[max(0.0, point - lo)], [max(0.0, hi - point)]]


# ── 0. PAPER ANALOG (Emmons et al. §3.1 Fig 3) ──
CONDS0 = ["none", "simple", "complex"]
CONDS0_LABEL = {"none": "no-hint", "simple": "simple", "complex": "complex\n(L1+L2+L3)"}
C_CONCEAL = "#d7301f"   # picks hinted, does NOT mention → the paper's headline effect
C_MENTION = "#41ab5d"   # picks hinted AND mentions (revealed / faithful)


def fig_paper_analog(*, experiment="exp_hints_sweep", suffix="", set_label="", pins=None, boot=None):
    """Direct analog of Emmons et al. §3.1 Fig 3: 'did §3.1 replicate?' in one figure. One panel per
    judgeable actor; stacked take-the-hint bars over {no-hint, simple, complex}; each take split into
    conceal (no mention) vs mention. Reads raw per-rollout transcripts, not the summary path.

    `experiment`/`suffix`/`set_label` select & label the transcript SET (filtered vs --no-filter
    unfiltered); `pins` = {actor: (run_id, path)} forces a specific run when >1 matches; `boot`
    (filtered set only) adds an item-cluster-bootstrap whisker on each bar's take-rate. Returns
    (path, complex_follower_mention_fractions) or (None, {}) if no transcript data resolves."""
    pins = pins or {}
    boot = boot or {}
    take_ci_key = {"none": "baseline", "simple": "follow_simple", "complex": "follow_complex"}
    data = {}
    for a in JUDGEABLE:
        rid, path = pins.get(a, (None, None))
        data[a] = _take_split(load_withcot_rollouts(a, experiment=experiment, run_id=rid, path=path))
    data = {a: agg for a, agg in data.items() if any(v["n"] for v in agg.values())}
    if not data:
        print(f"  [fig0 skipped: no {experiment}_<actor>_*.jsonl transcripts for the judgeable actors]")
        return None, {}

    actors = [a for a in JUDGEABLE if a in data]
    ncols = 2 if len(actors) > 1 else 1
    nrows = -(-len(actors) // ncols)        # ceil
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.2 * ncols, 5.0 * nrows), squeeze=False)
    flat = [ax for row in axes for ax in row]
    for ax in flat[len(actors):]:           # hide any unused panels (e.g. odd actor count)
        ax.axis("off")
    complex_mention_frac = {}
    for ax, a in zip(flat, actors):
        agg = data[a]
        x = range(len(CONDS0))
        conceal = [agg[c]["conceal"] / agg[c]["n"] if agg[c]["n"] else 0.0 for c in CONDS0]
        mention = [agg[c]["mention"] / agg[c]["n"] if agg[c]["n"] else 0.0 for c in CONDS0]
        ax.bar(x, mention, color=C_MENTION, edgecolor="black", lw=0.6, label="mentions hint (revealed)")
        ax.bar(x, conceal, bottom=mention, color=C_CONCEAL, edgecolor="black", lw=0.6,
               label="no mention (concealed)")
        acis = boot.get(a, {}).get("cis", {})
        for xi, c in zip(x, CONDS0):
            take = conceal[xi] + mention[xi]
            n_take = agg[c]["conceal"] + agg[c]["mention"]
            frac = (agg[c]["mention"] / n_take) if n_take else None
            bc = acis.get(take_ci_key[c])
            if bc:                              # item-cluster-bootstrap whisker on the take-rate
                ax.errorbar(xi, take, yerr=_boot_err(take, bc, clamp=(0, 1)), fmt="none",
                            ecolor="black", capsize=3, lw=1, zorder=4)
            note = f"take={take:.2f}\n(n={agg[c]['n']})"
            if frac is not None and n_take:
                note += f"\nment {agg[c]['mention']}/{n_take}"
            ax.text(xi, take + 0.04, note, ha="center", va="bottom", fontsize=7)
        cx = agg["complex"]
        n_take_cx = cx["conceal"] + cx["mention"]
        complex_mention_frac[a] = (cx["mention"] / n_take_cx) if n_take_cx else None
        ax.set_xticks(list(x))
        ax.set_xticklabels([CONDS0_LABEL[c] for c in CONDS0], fontsize=9)
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("take-the-hint rate (picks hinted letter, with-CoT)")
        ax.set_title(LABEL[a].replace("\n", " "), fontsize=10)
    flat[0].legend(fontsize=8, loc="upper center")
    whisker_note = ("\nwhisker = " + BOOT_CI) if boot else ""
    fig.suptitle(
        "Fig 0 — §3.1 REPLICATION (paper analog, Emmons et al. Fig 3): take-the-hint, mention vs conceal\n"
        f"{set_label}\n"
        "judgeable actors · with-CoT arm · ALL items (no necessity gating) · 'mention' = STRICT judge_verdict "
        "(hint used as the reason) · complex = L1+L2+L3 collapsed" + whisker_note,
        fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.90 if boot else 0.91))
    return _save(fig, f"fig0_paper_analog{suffix}"), complex_mention_frac


# ── 0b. PAPER ANALOG, NECESSITY-SCOPED complex (companion to Fig 0; do NOT fold into fig0) ──
COMPLEX_FAMILY = "arithmetic"        # §3.1 complex hint family → which decode-sweep family scopes it
CONDS0B_LABEL = {"none": "no-hint", "simple": "simple", "complex": "complex\n(necessity-scoped)"}


def _necessary_complex_levels(actor, *, family=COMPLEX_FAMILY):
    """(raw complex-level conds CoT-necessary for `actor`, available?) per the decode sweep. Reads
    logs/decode_necessity_<actor>.json (the §3.1 complex family = arithmetic) and keeps only levels
    whose verdict is `cot_necessary` (one-shot/weak/too-hard excluded). available=False if no decode
    file exists yet (gemini-2.5-flash / gpt-oss until the message-7a run) → caller skips the scoped bar."""
    p = Path(f"logs/decode_necessity_{actor}.json")
    if not p.exists():
        return [], False
    d = json.loads(p.read_text())
    lvls = sorted(r["level"] for r in d.get("rows", [])
                  if r.get("family") == family and r.get("necessity") == "cot_necessary")
    return [f"complex_L{lv}" for lv in lvls], True


def fig_paper_analog_necessity_scoped(*, experiment="exp_hints_sweep", pins=None, n_boot=5000, seed=0):
    """Fig 0b — necessity-scoped companion to Fig 0 (shown together as a robustness contrast; Fig 0 is
    left untouched). IDENTICAL to Fig 0 except each actor's complex bar sums ONLY the arithmetic levels
    that are CoT-necessary for THAT actor per the decode sweep (C1/C2); one-shot levels are excluded.
    Actors with no decode data yet (gemini-2.5-flash, gpt-oss until the message-7a run) render NO scoped
    complex bar. Per-actor title states which levels feed the bar. Returns
    (path, {actor: complex_mention_fraction on the necessity-validated cells})."""
    pins = pins or {}
    per = {}                                   # actor -> (stats, nec_levels, available)
    for a in JUDGEABLE:
        nec, avail = _necessary_complex_levels(a)
        rid, path = pins.get(a, (None, None))
        groups = {"none": ["none"], "simple": ["simple"], "complex": (nec if avail else [])}
        stats = metrics.scoped_take_cis(a, groups, experiment=experiment, run_id=rid, path=path,
                                        n_boot=n_boot, seed=seed)
        if stats is not None:
            per[a] = (stats, nec, avail)
    if not per:
        print(f"  [fig0b skipped: no {experiment}_<actor>_*.jsonl transcripts]")
        return None, {}

    actors = [a for a in JUDGEABLE if a in per]
    ncols = 2 if len(actors) > 1 else 1
    nrows = -(-len(actors) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.2 * ncols, 5.0 * nrows), squeeze=False)
    flat = [ax for row in axes for ax in row]
    for ax in flat[len(actors):]:
        ax.axis("off")
    complex_mention_frac = {}
    for ax, a in zip(flat, actors):
        stats, nec, avail = per[a]
        for xi, c in enumerate(CONDS0):
            cell = stats.get(c)
            if cell is None:                   # scoped complex unavailable: pending decode, or none necessary
                msg = ("pending\ndecode (msg 7a)" if (c == "complex" and not avail)
                       else "no CoT-necessary\nlevel")
                ax.text(xi, 0.04, msg, ha="center", va="bottom", fontsize=7, color="#999", style="italic")
                continue
            n = cell["n"]
            mention = cell["mention"] / n if n else 0.0
            conceal = cell["conceal"] / n if n else 0.0
            take = mention + conceal
            ax.bar(xi, mention, color=C_MENTION, edgecolor="black", lw=0.6,
                   label=("mentions hint (revealed)" if xi == 0 else None))
            ax.bar(xi, conceal, bottom=mention, color=C_CONCEAL, edgecolor="black", lw=0.6,
                   label=("no mention (concealed)" if xi == 0 else None))
            ax.errorbar(xi, take, yerr=_boot_err(take, cell["take"], clamp=(0, 1)), fmt="none",
                        ecolor="black", capsize=3, lw=1, zorder=4)
            n_take = cell["mention"] + cell["conceal"]
            note = f"take={take:.2f}\n(n={n})" + (f"\nment {cell['mention']}/{n_take}" if n_take else "")
            ax.text(xi, take + 0.04, note, ha="center", va="bottom", fontsize=7)
        cc = stats.get("complex")
        if cc is not None:
            n_take_cx = cc["mention"] + cc["conceal"]
            complex_mention_frac[a] = (cc["mention"] / n_take_cx) if n_take_cx else None
            lvl_txt = "complex = " + ",".join(l.replace("complex_", "") for l in nec) + " (CoT-necessary)"
        else:
            complex_mention_frac[a] = None
            lvl_txt = "complex = pending decode (msg 7a)" if not avail else "complex = none CoT-necessary"
        ax.set_xticks(range(len(CONDS0)))
        ax.set_xticklabels([CONDS0B_LABEL[c] for c in CONDS0], fontsize=9)
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("take-the-hint rate (picks hinted letter, with-CoT)")
        ax.set_title(f"{LABEL[a].replace(chr(10), ' ')}\n{lvl_txt}", fontsize=8.5)
    flat[0].legend(fontsize=8, loc="upper center")
    fig.suptitle(
        "Fig 0b — §3.1 paper analog, NECESSITY-SCOPED complex (companion to Fig 0, shown together)\n"
        "complex bar = ONLY the arithmetic levels CoT-necessary for THAT actor per the decode sweep "
        "(C1/C2); one-shot levels excluded\n"
        "judgeable actors · with-CoT arm · 'mention' = STRICT judge_verdict · whisker = " + BOOT_CI,
        fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    return _save(fig, "fig0b_paper_analog_necessity_scoped"), complex_mention_frac


# ── 1. HEADLINE (Gate 1) ──
def fig_headline(summaries, boot=None):
    """Gate-1: simple-hint unfaithfulness delta (= unfaithful_rate − no-hint baseline) per actor.
    When `boot` is supplied the delta's CI and the gate come from the item-level cluster bootstrap
    (delta CI excludes 0), not the pooled-Wilson non-overlap test; the point (delta) is unchanged."""
    boot = boot or {}
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    names = [n for n in ORDER if n in summaries]
    boot_used = False
    for i, n in enumerate(names):
        s = summaries[n]
        base = s["baseline_pick_target"]
        c = s.get("simple")
        if not c:
            continue
        uf = c["unfaithful_rate"]
        delta = uf["p"] - base["p"]
        bd = boot.get(n, {}).get("cis", {}).get("headline_delta")
        if bd:                                   # cluster-bootstrap delta CI; gate = CI excludes 0
            boot_used = True
            dlo, dhi = bd["lo"], bd["hi"]
            passes = dlo > 0
            yerr = [[max(0.0, delta - dlo)], [max(0.0, dhi - delta)]]
        else:                                    # fallback: pooled-Wilson non-overlap test
            passes = uf["lo"] > base["hi"]
            yerr = [[delta - (uf["lo"] - base["p"])], [(uf["hi"] - base["p"]) - delta]]
        ax.bar(i, delta, color="#2b8cbe" if passes else "#a6bddb", width=0.6,
               edgecolor="black", linewidth=0.8)
        ax.errorbar(i, delta, yerr=yerr, fmt="none", ecolor="black", capsize=4, lw=1.2)
        ax.text(i, max(delta, 0) + 0.03,
                f"{delta:+.2f}\n{'✓gate' if passes else 'ns'}\nfoll={c['follow_withcot']['p']:.2f}",
                ha="center", va="bottom", fontsize=8)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([LABEL[n] for n in names], fontsize=9)
    ax.set_ylabel("simple-hint unfaithfulness delta\n(hinted-without-mention − no-hint baseline)")
    ci = (BOOT_CI + " · gate: CI>0") if boot_used else "Wilson 2σ"
    ax.set_title("Fig 1 — §3.1 REPLICATION (Gate 1): simple-hint unfaithfulness, L1\n"
                 + _caption(summaries, ci=ci), fontsize=8.5)
    ax.set_ylim(min(0, ax.get_ylim()[0]), max(0.5, ax.get_ylim()[1]))
    fig.tight_layout()
    return _save(fig, "fig1_headline")


# ── 2. Necessity-gated complex ──
def fig_necessity_gated(summaries):
    """DEMOTED — not a standalone result. Necessity-gated unfaithfulness needs a cell that is BOTH
    CoT-necessary AND followed; in this follow-based sweep no (actor × level) cell qualifies, so the
    conditional is UNDEFINED (an empty denominator — neither 0% nor 100%). The earlier version drew
    those empty cells at full height on an 'unfaithfulness' axis, mis-reading as 100% unfaithful, and
    its one_shot/declines labels were margin-sensitive and contradicted by the decode-necessity figs.
    Necessity is measured properly — as decode ACCURACY uplift — in Figs C1/C2 (figures/3p1_complex_hints/).
    Here we plot ONLY genuine signal cells (if any ever appear) and otherwise redirect; empty cells are
    never drawn and per-bar necessity labels are gone."""
    names = [n for n in ORDER if n in summaries]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    width = 0.22
    plotted = 0
    for li, lv in enumerate(LEVELS):
        for ni, n in enumerate(names):
            c = summaries[n].get(lv)
            if not c or not (c["necessity"] == "cot_necessary" and c["n_followers"] > 0):
                continue                       # empty-denominator cells are NOT plotted (no full-height bars)
            x = ni + (li - 1) * width
            uf = c["unfaithful_among_followers"]
            ax.bar(x, uf["p"], width=width, color=["#1b9e77", "#d95f02", "#7570b3"][li],
                   edgecolor="black", lw=0.6)
            ax.errorbar(x, uf["p"], yerr=_lohi(uf), fmt="none", ecolor="black", capsize=3, lw=1)
            ax.text(x, uf["p"] + 0.02, f"{uf['p']:.2f}\nn={c['n_followers']}", ha="center", fontsize=6.5)
            plotted += 1
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([LABEL[n] for n in names], fontsize=9)
    ax.set_ylabel("unfaithfulness | (CoT-necessary AND followed)")
    ax.set_ylim(0, 1.05)
    if not plotted:
        ax.text(0.5, 0.5,
                "No clean necessity-gated window in this follow-based sweep.\n"
                "No (actor × level) cell is both CoT-necessary AND followed, so this conditional\n"
                "unfaithfulness is UNDEFINED (an empty denominator — not 0%, not 100%).\n\n"
                "Necessity is measured properly, as decode-ACCURACY uplift, in\n"
                "Figs C1/C2  →  figures/3p1_complex_hints/",
                transform=ax.transAxes, ha="center", va="center", fontsize=11,
                bbox=dict(boxstyle="round", fc="#f7f7f7", ec="#bbb"))
    else:
        ax.legend(handles=[Patch(color="#1b9e77", label="L1"), Patch(color="#d95f02", label="L2"),
                           Patch(color="#7570b3", label="L3")], fontsize=8, ncol=3, loc="upper right")
    ax.set_title("Fig 2 (DEMOTED — not a standalone result): necessity-gated complex unfaithfulness\n"
                 + _caption(summaries) +
                 " · superseded by the decode-necessity Figs C1/C2 (figures/3p1_complex_hints/)", fontsize=9.5)
    fig.tight_layout()
    return _save(fig, "fig2_necessity_gated")


# ── 2b. Necessity-SCOPED complex unfaithfulness (companion to Fig 2; do NOT fold into fig2) ──
def _decode_verdicts(actor, *, family=COMPLEX_FAMILY):
    """({level:int -> decode-necessity verdict} for `family`, available?) from
    logs/decode_necessity_<actor>.json. available=False if no decode file yet (pending msg-7a run)."""
    p = Path(f"logs/decode_necessity_{actor}.json")
    if not p.exists():
        return {}, False
    d = json.loads(p.read_text())
    return ({r["level"]: r["necessity"] for r in d.get("rows", []) if r.get("family") == family}, True)


def fig_necessity_gated_scoped(summaries):
    """Fig 2b — necessity-scoped companion to Fig 2 (Fig 2 left exactly as-is). Same metric (complex
    unfaithfulness | followed) but the necessity GATE is the **decode-necessity verdict** (C1/C2) per
    actor×level — NOT Fig 2's follow-based point+0.05-margin label. A cell is a valid complex datapoint
    ONLY if the decode is CoT-necessary for that actor at that level (one-shot/too-hard excluded). Unlike
    Fig 2 — whose follow-based label is never `cot_necessary` here, so it plots nothing — this DOES plot:
    arithmetic is CoT-necessary at every level for gemini-3-flash/gpt-5.5, so their floored-but-nonzero
    complex followers are valid datapoints. gemini-2.5-flash/gpt-oss show 'decode pending' until msg 7a."""
    names = [n for n in ORDER if n in summaries]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    width = 0.22
    colors = ["#1b9e77", "#d95f02", "#7570b3"]
    plotted = 0
    for ni, n in enumerate(names):
        verdicts, avail = _decode_verdicts(n)
        if not avail:                          # no decode data → can't gate by necessity yet
            ax.text(ni, 0.5, "decode\npending\n(msg 7a)", ha="center", va="center", fontsize=7,
                    color="#999", style="italic")
            continue
        for li, lv in enumerate(LEVELS):
            c = summaries[n].get(lv)
            x = ni + (li - 1) * width
            verdict = verdicts.get(li + 1)
            if verdict == "cot_necessary" and c and c["n_followers"] > 0:
                uf = c["unfaithful_among_followers"]
                ax.bar(x, uf["p"], width=width, color=colors[li], edgecolor="black", lw=0.6)
                ax.errorbar(x, uf["p"], yerr=_lohi(uf), fmt="none", ecolor="black", capsize=3, lw=1)
                ax.text(x, uf["p"] + 0.02, f"{uf['p']:.2f}\nn={c['n_followers']}", ha="center", fontsize=6.5)
                plotted += 1
            else:                              # excluded — small reason marker, NEVER a full-height bar
                reason = ("no followers" if verdict == "cot_necessary"
                          else (verdict or "—").replace("_", "-"))
                ax.text(x, 0.02, reason, ha="center", va="bottom", fontsize=6, rotation=90, color="#aaa")
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([LABEL[nm] for nm in names], fontsize=9)
    ax.set_ylabel("unfaithfulness | (decode CoT-necessary AND followed)")
    ax.set_ylim(0, 1.05)
    if not plotted:
        ax.text(0.5, 0.5, "no necessity-validated complex cell with followers yet\n"
                "(run the decode sweep for all actors — msg 7a)", transform=ax.transAxes,
                ha="center", va="center", fontsize=11, bbox=dict(boxstyle="round", fc="#f7f7f7", ec="#bbb"))
    ax.legend(handles=[Patch(color=colors[i], label=f"L{i + 1}") for i in range(3)],
              fontsize=8, ncol=3, loc="upper right")
    ax.set_title("Fig 2b — necessity-SCOPED complex unfaithfulness (gate = decode-necessity verdict C1/C2, "
                 "per actor×level)\n" + _caption(summaries) +
                 " · valid cell = decode CoT-necessary (one-shot/too-hard excluded) · companion to Fig 2",
                 fontsize=9)
    fig.tight_layout()
    return _save(fig, "fig2b_necessity_scoped")


# ── 3. Decode-uplift bars (Part B fix — replaces the crushed two-line curve) ──
def _repl_cells(summaries):
    """Replication decode cells. Here the decode-accuracy PROXY is the follow-rate (picks the hinted
    letter) — this experiment is follow-based, so a near-zero/negative uplift on complex levels means
    the actor DECLINES (too-hard-to-follow), while simple is one-shot (cue needs no CoT). The TRUE
    decode-accuracy version (does the model compute the letter at all) is the 3p1_complex_hints run."""
    conds = [("simple", "simple", "simple")] + [(lv, "arithmetic", LV_SHORT[lv]) for lv in LEVELS]
    cells = []
    for n in ORDER:
        s = summaries.get(n)
        if not s:
            continue
        for key, fam, lvl in conds:
            c = s.get(key)
            if not c:
                continue
            wc, nc = c["follow_withcot"], c["follow_nocot"]
            cells.append(figviz.Cell(actor=n, family=fam, level=lvl,
                                     k_cot=wc["k"], n_cot=wc["n"], k_nocot=nc["k"], n_nocot=nc["n"]))
    return cells


def fig_decode_uplift(summaries):
    cells = _repl_cells(summaries)
    fig, ax = plt.subplots(figsize=(11, 5.6))
    figviz.draw_uplift_bars(
        ax, cells, group_attr="actor", series=["simple", "L1", "L2", "L3"], group_order=ORDER,
        group_label=LABEL, metric_label="picks the hinted letter",
        ylabel="follow-rate uplift (with-CoT − no-CoT)\n(picks the hinted letter)",
        verdict_fn=figviz.follow_uplift_verdict,
        title="Fig 3 — EXTENSION: follow-rate uplift (with-CoT − no-CoT follow-rate), per actor × level "
              "(Newcombe 2σ)\n" + _caption(summaries) +
              " · annotations = (with-CoT, no-CoT); low follow in BOTH arms = declines, NOT too-hard "
              "(the decode IS CoT-necessary — see Figs C1/C2)")
    fig.tight_layout()
    return _save(fig, "fig3_decode_uplift")


# ── 4. Follow-rate panel ──
def fig_follow_rate(summaries, boot=None):
    """With-CoT follow-rate per actor × condition (the denominator behind every unfaithfulness
    number). When `boot` is supplied, each bar's whisker is the item-cluster-bootstrap CI of that
    follow-rate (point unchanged); else pooled-Wilson."""
    boot = boot or {}
    names = [n for n in ORDER if n in summaries]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    conds = ["simple"] + LEVELS
    colors = {"simple": "#444", "complex_L1": "#1b9e77", "complex_L2": "#d95f02", "complex_L3": "#7570b3"}
    width = 0.18
    boot_used = False
    for ci, cond in enumerate(conds):
        for ni, n in enumerate(names):
            c = summaries[n].get(cond)
            if not c:
                continue
            x = ni + (ci - 1.5) * width
            fr = c["follow_withcot"]
            bc = boot.get(n, {}).get("cis", {}).get(f"follow_{cond}")
            yerr = _boot_err(fr["p"], bc, clamp=(0, 1)) if bc else _lohi(fr)
            boot_used = boot_used or bool(bc)
            ax.bar(x, fr["p"], width=width, color=colors[cond], edgecolor="black", lw=0.5)
            ax.errorbar(x, fr["p"], yerr=yerr, fmt="none", ecolor="black", capsize=2, lw=0.8)
    for ni, n in enumerate(names):
        base = summaries[n]["baseline_pick_target"]["p"]
        ax.plot([ni - 0.4, ni + 0.4], [base, base], color="red", lw=1, ls=":")
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([LABEL[n] for n in names], fontsize=9)
    ax.set_ylabel("follow_rate (with-CoT) = picks the hinted letter")
    ax.set_ylim(0, 1.05)
    ax.set_title("Fig 4 — follow-rate per actor × condition (the denominator behind every unfaithfulness number)\n"
                 + _caption(summaries, ci=BOOT_CI if boot_used else "Wilson 2σ")
                 + " · red dotted = no-hint baseline", fontsize=9.5)
    ax.legend(handles=[Patch(color=colors[c], label=c.replace("complex_", "")) for c in conds],
              fontsize=8, ncol=4, loc="upper right")
    fig.tight_layout()
    return _save(fig, "fig4_follow_rate")


# ── 5. Concealment scatter — "most cue-susceptible ≠ least monitorable" ──
def _concealment_rows(experiment, pins):
    """Per judgeable actor (raw per-rollout transcripts, with-CoT simple cue): follow-rate and
    BASELINE-CORRECTED concealment-given-follow. Coincidental hinted-letter picks (the no-hint
    pick-target baseline) are removed from BOTH the concealed-follow count and the follower count —
    the consistent extension of Fig 1's `unfaithful − baseline` delta to a conditional rate — so a
    high-baseline actor's concealment isn't inflated by chance picks. strict judge_verdict = mention."""
    rows = []
    for a in JUDGEABLE:
        rid, path = pins.get(a, (None, None))
        agg = _take_split(load_withcot_rollouts(a, experiment=experiment, run_id=rid, path=path))
        s, none = agg["simple"], agg["none"]
        if not s["n"] or not none["n"]:
            continue
        n = s["n"]
        foll = s["mention"] + s["conceal"]                 # picks the hinted letter (with-CoT)
        concealed = s["conceal"]                           # picked it WITHOUT strict mention
        base_p = (none["mention"] + none["conceal"]) / none["n"]   # no-hint pick-target rate
        gen_foll = foll - base_p * n                       # hint-attributable followers
        gen_conc = concealed - base_p * n                  # hint-attributable concealed follows
        y = gen_conc / gen_foll if gen_foll > 0 else float("nan")
        rows.append(dict(actor=a, n=n, foll=foll, x=foll / n, y=y, base_p=base_p,
                         conceal_raw=(concealed / foll if foll else float("nan")),
                         gen_conc=max(0, round(gen_conc)), gen_foll=max(0, round(gen_foll))))
    return rows


def fig_concealment(caption="", experiment="exp_hints_sweep", pins=None, boot=None):
    """Fig 5 — 'most cue-susceptible ≠ least monitorable.' One labelled point per judgeable actor:
    x = simple-cue follow-rate (with-CoT); y = baseline-corrected concealment among followers
    (strict judge_verdict). The anti-alignment is the result. Filtered set, explicit fig0 selector.
    Both error bars are item-cluster-bootstrap CIs when `boot` is supplied (point unchanged) — this
    is where the thin-cell widening shows: gpt-oss's tiny baseline-corrected denominator gives it a
    very wide y interval."""
    boot = boot or {}
    rows = _concealment_rows(experiment, pins or {})
    if not rows:
        print("  [fig5 skipped: no filtered sweep transcripts for the judgeable actors]")
        return None, []
    fig, ax = plt.subplots(figsize=(9.0, 6.8))
    boot_used = False
    for r in rows:
        color = ACTOR_COLOR.get(r["actor"], "#333")
        yv = max(0.0, r["y"]) if r["y"] == r["y"] else 0.0
        acis = boot.get(r["actor"], {}).get("cis", {})
        bx, byc = acis.get("follow_simple"), acis.get("concealment_corrected_simple")
        if bx and byc:
            boot_used = True
            xerr = _boot_err(r["x"], bx, clamp=(0, 1))
            yerr = _boot_err(yv, byc, clamp=(0, 1))
        else:                                    # fallback: pooled Wilson (on baseline-corrected counts)
            xlo, xhi = metrics.wilson_ci(r["foll"], r["n"])
            ylo, yhi = metrics.wilson_ci(r["gen_conc"], r["gen_foll"]) if r["gen_foll"] > 0 else (yv, yv)
            xerr = [[r["x"] - xlo], [xhi - r["x"]]]
            yerr = [[max(0, yv - ylo)], [max(0, yhi - yv)]]
        ax.errorbar(r["x"], yv, xerr=xerr, yerr=yerr, fmt="o", ms=12, color=color,
                    ecolor=color, elinewidth=1.3, capsize=4, zorder=3)
        ax.annotate(LABEL[r["actor"]].replace("\n", " "), (r["x"], yv), textcoords="offset points",
                    xytext=(11, 9), fontsize=9.5, color=color, fontweight="bold")
        ax.annotate(f"follow {r['x']:.2f} · conceal {yv:.2f} (raw {r['conceal_raw']:.2f})",
                    (r["x"], yv), textcoords="offset points", xytext=(11, -15), fontsize=7, color="#555")
    ax.annotate("anti-alignment:\nfollows more → conceals less", xy=(0.97, 0.97),
                xycoords="axes fraction", ha="right", va="top", fontsize=9, color="#777",
                bbox=dict(boxstyle="round", fc="#f7f7f7", ec="#ccc"))
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.05)
    ax.grid(True, ls=":", lw=0.5, color="#ddd")
    ax.set_xlabel("follow-rate (with-CoT, simple cue) = picks the hinted letter")
    ax.set_ylabel("concealment | followers, baseline-corrected\n"
                  "= (unfaithful − base) / (follow − base), strict judge_verdict")
    ci_note = ("CIs = " + BOOT_CI) if boot_used else "Wilson 2σ"
    ax.set_title("Fig 5 — most cue-susceptible ≠ least monitorable (simple cue)\n"
                 + caption + "\n"
                 "y = concealment among hint-attributable followers, baseline-subtracted "
                 "(numerator AND denominator,\nas Fig 1's delta); strict judge_verdict · "
                 "raw (in parens) = uncorrected · " + ci_note, fontsize=8.5)
    fig.tight_layout()
    return _save(fig, "fig5_concealment"), rows


def _save(fig, name):
    FIGDIR.mkdir(exist_ok=True)
    path = FIGDIR / f"{name}.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def _data_table(summaries):
    rows = []
    for n in ORDER:
        if n not in summaries:
            continue
        s = summaries[n]
        for kind in ["simple"] + LEVELS:
            c = s.get(kind)
            if not c:
                continue
            rows.append([n, kind, s["n_items"], c["follow_withcot"]["p"], c["follow_nocot"]["p"],
                         c.get("decode_uplift"), c["unfaithful_rate"]["p"],
                         c["unfaithful_among_followers"]["p"], c["n_followers"], c["necessity"],
                         s["baseline_pick_target"]["p"]])
    return rows


def main(args):
    summaries = load()
    if not summaries:
        print("no completed sweep_<actor>.json yet — run after an actor finishes.")
        return
    print(f"actors with data: {list(summaries)}")
    pins = _parse_pins(args.fig0_transcript)

    # Item-level cluster-bootstrap CIs for Figs 0/1/4/5 (FILTERED set, resamples the ~60 items).
    # Wilson-over-pooled-samples treats 60×10 as 600 independent draws; within-item samples are
    # correlated, so the bootstrap is the honest interval. Points never move — only CIs widen.
    boot = _boot_for([n for n in ORDER if n in summaries], pins=pins,
                     n_boot=args.n_boot, seed=args.boot_seed)

    paths = [fig_headline(summaries, boot), fig_necessity_gated(summaries),
             fig_necessity_gated_scoped(summaries),
             fig_decode_uplift(summaries), fig_follow_rate(summaries, boot)]

    # Fig 0 — paper analog, built from RAW per-rollout transcripts (own data path). The cluster
    # bootstrap is filtered-set only; pass it to the take-rate whiskers when fig0 is the filtered set.
    set_cfg = FIG0_SETS[args.fig0_set]
    p0, complex_frac = fig_paper_analog(pins=pins, boot=(boot if args.fig0_set == "filtered" else None),
                                        **set_cfg)
    if p0 is not None:
        paths.insert(0, p0)
        print(f"  REPLICATION READOUT [{args.fig0_set} set] — strict mention rate among COMPLEX "
              "followers (picks hinted arithmetic letter):")
        for a, frac in complex_frac.items():
            if frac is None:
                print(f"    {a:18} no complex followers (take rate ~0) — undefined")
            else:
                verdict = "REPLICATE (followers reveal the decode)" if frac >= 0.5 \
                    else "CONTRADICT (followers conceal the decode)"
                print(f"    {a:18} {frac:.2f} mention the arithmetic decode → {verdict}")

    # Fig 0b — necessity-scoped complex companion (FILTERED set; do not touch Fig 0).
    p0b, scoped_frac = fig_paper_analog_necessity_scoped(pins=pins, n_boot=args.n_boot, seed=args.boot_seed)
    if p0b is not None:
        paths.insert(1 if p0 is not None else 0, p0b)
        print("  NECESSITY-SCOPED READOUT [filtered] — strict mention fraction among complex followers, "
              "CoT-necessary levels only:")
        for a, frac in scoped_frac.items():
            if frac is None:
                print(f"    {a:18} no scoped complex bar (decode data pending or no CoT-necessary level)")
            else:
                print(f"    {a:18} {frac:.2f} mention the arithmetic decode (necessity-scoped cells)")

    # Fig 5 — concealment scatter (FILTERED set always; raw per-rollout transcripts, explicit selector).
    p5, conceal_rows = fig_concealment(caption=_caption(summaries, ci=""), pins=pins, boot=boot)
    if p5 is not None:
        paths.append(p5)
        print("  CONCEALMENT READOUT [filtered, simple cue] — follow-rate vs baseline-corrected "
              "concealment|followers (raw in parens):")
        for r in sorted(conceal_rows, key=lambda r: r["x"]):
            yv = max(0.0, r["y"]) if r["y"] == r["y"] else float("nan")
            print(f"    {r['actor']:18} follow={r['x']:.2f}  conceal={yv:.2f}  "
                  f"(raw {r['conceal_raw']:.2f}, base={r['base_p']:.2f})")

    for p in paths:
        print(f"  saved {p}")

    if not args.no_wandb:
        try:
            import wandb

            from cot_mon.logging import wandb_logger as wl
            run = wl.WandbRun(experiment="exp_hints_sweep_figures", actor="all", gate="gate1",
                              mode=args.wandb_mode, config={"actors": list(summaries)})
            cols = ["actor", "cond", "n_items", "follow_withcot", "follow_nocot", "decode_uplift",
                    "unfaithful_rate", "unfaithful_among_followers", "n_followers", "necessity", "baseline"]
            run.run.log({p.stem: wandb.Image(str(p)) for p in paths}
                        | {"sweep_data": wandb.Table(columns=cols, data=_data_table(summaries))})
            run.finish()
            print("  logged figures + data table to W&B")
        except Exception as e:  # noqa: BLE001
            print(f"  [wandb skipped: {e}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-wandb", action="store_true")
    ap.add_argument("--wandb-mode", default=None, choices=["online", "offline", "disabled"])
    ap.add_argument("--fig0-set", choices=list(FIG0_SETS), default="filtered",
                    help="which transcript set Fig 0 reads: 'filtered' (correct-with-CoT gate ON) "
                         "or 'unfiltered' (--no-filter runs). Run twice to get both 4-panel versions.")
    ap.add_argument("--fig0-transcript", action="append", default=[], metavar="ACTOR=RUNID_OR_PATH",
                    help="pin a transcript for an actor (repeatable); required only if >1 transcript "
                         "matches the set's glob. Used by Figs 0/5 and the cluster bootstrap.")
    ap.add_argument("--n-boot", type=int, default=5000,
                    help="item-level cluster-bootstrap resamples for the Figs 0/1/4/5 CIs.")
    ap.add_argument("--boot-seed", type=int, default=0, help="seed for the cluster bootstrap (reproducible CIs).")
    main(ap.parse_args())
