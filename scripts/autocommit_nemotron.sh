#!/usr/bin/env bash
# Autonomous STATUS update + commit + push for the Nemotron §3.1 run. Called as the pipeline's final
# stage so the whole cycle is hands-off (commits even if no session is watching). Idempotent-ish:
# safe to re-run (STATUS insert guarded on the session marker). Pushes to feat/qwen35-selfhost-vllm.
set -uo pipefail
cd /workspace/arav-cot-monitorability
set -a; . ./.env 2>/dev/null; set +a
SHORT=nemotron3_120b
ACTOR=nemotron3_120b_selfhost

# 1) Insert a STATUS Session #12 block (only if not already present), with numbers pulled from results.
python3 - <<'PY'
import json, re, os
def load(p, d=None):
    try: return json.load(open(p))
    except Exception: return d
g = load(f"logs/gate0_nemotron3_120b_selfhost.json", {})
dec = load("results/decode_necessity/decode_necessity_nemotron3_120b.json", {"rows":[]})
fd = load("results/family_figure_data.json", {})
FAMS=["bignum","iterated","deductive","indirection"]
def mean(xs): xs=[x for x in xs if x is not None]; return round(sum(xs)/len(xs),3) if xs else None
byf={}
for r in dec.get("rows",[]): byf.setdefault(r["family"],[]).append(r["uplift"])
decstr = " ".join(f"{f} {round(sum(v)/len(v),2):+.2f}" for f,v in byf.items())
nm = fd.get(SHORT if (SHORT:="nemotron3_120b") else "", {})
unf = mean([nm[f].get("unfaithful") for f in FAMS if f in nm]) if nm else None
fol = mean([nm[f].get("follow") for f in FAMS if f in nm]) if nm else None
nec = mean([nm[f].get("necessity") for f in FAMS if f in nm]) if nm else None
g0 = f"rtoks0={g.get('no_cot_rtoks0_frac','?')} emit={g.get('with_cot_emission','?')} uplift={g.get('preview_uplift','?')}"
block = ("**This session (2026-07-03, Session #12) — NVIDIA-Nemotron-3-Super-120B-A12B (FP8) self-host §3.1; COMMITTING:**\n"
  f"1. **★ Nemotron-3-Super-120B-A12B added as the 11th §3.1 actor** (self-host vLLM, `nemotron3_120b_selfhost` / figure key `nemotron3_120b`; NVIDIA FP8 checkpoint, 120B-total/**12B-active** hybrid LatentMoE = Mamba-2+MoE+Attention — adds an **independent NVIDIA lab family**; 12B-active = fast despite 120B). Full §3.1 pipeline chained autonomously (`scripts/run_nemotron_pipeline.sh`): Gate0→necessity→decode(figC1/C2)→family concealment→arithmetic Gate-1→re-judge→pull-others→regen ALL figures→auto-commit.\n"
  f"2. **★ No-CoT arm reuses qwen `vllm_structured`** — Nemotron-3 has a NATIVE `enable_thinking` toggle in its chat template (single-letter schema + chat_template_kwargs={{enable_thinking:false}}). Served `--reasoning-parser nemotron_v3`, modelopt FP8 (hybrid Mamba served on vLLM 0.24). Removed prior model weights (qwen32b/122b/olmo) to fit the disk quota.\n"
  f"3. **★ Gate-0: {g0}.** Decode-necessity by family: {decstr}. §3.1 (LLM-judged): follow {fol}, concealment {unf}, necessity(family) {nec}. In every §3.1 figure as the full 11-actor set.\n")
st = open("STATUS.md").read()
if "Session #12) — NVIDIA-Nemotron" not in st:
    st = st.replace("**Date:** 2026-07-03 · **Session #11** (Phase 2)",
                    "**Date:** 2026-07-03 · **Session #12** (Phase 2)")
    # insert the block right before the Session #11 line
    st = st.replace("**This session (2026-07-03, Session #11) — Olmo",
                    block + "**This session (2026-07-03, Session #11) — Olmo", 1)
    open("STATUS.md","w").write(st)
    print("STATUS: inserted Session #12 block")
else:
    print("STATUS: Session #12 already present, skipping insert")
PY

# 2) stage: modified tracked files (excludes untracked strays) + new nemotron files
git add -u
git add results/decode_necessity/decode_necessity_${SHORT}.json \
        scripts/run_nemotron_pipeline.sh scripts/autocommit_nemotron.sh 2>/dev/null || true
# any new selfhost probe artifacts for nemotron
git add selfhost_vllm/*nemotron* 2>/dev/null || true

# 3) commit (skip if nothing staged)
if git diff --cached --quiet; then echo "autocommit: nothing to commit"; exit 0; fi
git commit -q -F - <<'MSG'
Session #12: NVIDIA-Nemotron-3-Super-120B-A12B (FP8) §3.1 via self-host vLLM — 11th actor, all figures

Adds nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8 as the 11th §3.1 actor
(independent NVIDIA lab family; 120B total / 12B active hybrid Mamba-2+MoE).
Full §3.1 pipeline chained autonomously (run_nemotron_pipeline.sh) with auto-commit.

No-CoT arm reuses the qwen `vllm_structured` mechanism — Nemotron-3 has a native
enable_thinking toggle. Served --reasoning-parser nemotron_v3, modelopt FP8.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
MSG
echo "autocommit: committed $(git rev-parse --short HEAD)"

# 4) push via GH_TOKEN (token kept out of stored config)
REMOTE_URL=$(git remote get-url origin)
if [ -n "${GH_TOKEN:-}" ]; then
  PUSH_URL=$(echo "$REMOTE_URL" | sed -E "s#https://([^@]*@)?#https://x-access-token:${GH_TOKEN}@#")
  git push "$PUSH_URL" feat/qwen35-selfhost-vllm 2>&1 | sed -E "s/${GH_TOKEN}/***/g"
else
  git push origin feat/qwen35-selfhost-vllm
fi
echo "autocommit: push rc=$?"
