#!/usr/bin/env python3
"""Lightweight live status for the self-hosted qwen3.5 §3.1 runs (heartbeat + milestone source).

Reads the INCREMENTAL per-item jsonls (so partial cells show up), the decode/sweep summary jsons,
the vLLM /metrics endpoint (in-flight + throughput), and nvidia-smi (GPU util). Prints a compact
block; does NO inference. `sweep_status.py` is bypassed (its BASE path is hardcoded to a Mac and it
scrapes .log files) — this reads the jsonls directly.

  uv run python scripts/qwen_status.py            # one snapshot (heartbeat calls this every 15 min)
"""
import glob, json, os, time, urllib.request, subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
TR = "logs/transcripts"


def _rows(path):
    try:
        return [json.loads(l) for l in open(path) if l.strip()]
    except Exception:
        return []


def gate0():
    p = f"{TR}/gate0_qwen3_5_122b_selfhost.jsonl"
    r = _rows(p)
    if not r:
        return None
    n = len(r)
    ce = sum(1 for x in r if x.get("cot_emitted")) / n
    nr0 = sum(1 for x in r if x.get("no_rtok0")) / n
    ca = sum(1 for x in r if x.get("cot_correct")) / n
    na = sum(1 for x in r if x.get("no_correct")) / n
    return f"GATE0: {n} rollouts | cot_emit={ce:.2f} no_rtok0={nr0:.2f} | cot_acc={ca:.2f} no_acc={na:.2f}"


def family():
    out = []
    globs = (glob.glob(f"{TR}/exp_hints_sweep_*_qwen3_5_122b*_*.jsonl")
             + glob.glob("logs/transcripts_incr/exp_hints_sweep_*_qwen3_5_122b*.jsonl"))
    for f in sorted(set(globs)):
        r = _rows(f)
        if not r:
            continue
        fam = os.path.basename(f).split("exp_hints_sweep_")[1].split("_qwen")[0]
        wc = [d for d in r if d.get("cot_mode") == "with_cot"]
        wc_cplx = [d for d in wc if str(d.get("hint_type", "")).startswith("complex")]
        emit = sum(1 for d in wc if d.get("extracted_answer")) / max(len(wc), 1)
        foll = sum(1 for d in wc_cplx if str(d.get("engaged_hint")) == "True") / max(len(wc_cplx), 1)
        out.append(f"  fam[{fam:11}]: {len(r):4d} rows | wc_emit={emit:.2f} complex_follow={foll:.2f}")
    return "FAMILY SWEEP:\n" + "\n".join(out) if out else None


def decode():
    for p in glob.glob("logs/decode_necessity_qwen3_5_122b*.json"):
        try:
            d = json.load(open(p))
            m = d["meta"]
            done = len(d["rows"])
            return (f"DECODE: {done} cells | emit_cot={m.get('emission_with_cot')} "
                    f"emit_nocot={m.get('emission_no_cot')} | {os.path.basename(p)}")
        except Exception:
            pass
    return None


def vllm_metrics():
    base = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1").rsplit("/v1", 1)[0]
    key = os.environ.get("VLLM_API_KEY", "")

    def scrape():
        try:
            req = urllib.request.Request(base + "/metrics", headers={"Authorization": f"Bearer {key}"})
            txt = urllib.request.urlopen(req, timeout=8).read().decode()
        except Exception as e:
            return None, f"metrics unreachable ({type(e).__name__})"
        d = {}
        for line in txt.splitlines():
            if line.startswith("#") or " " not in line:
                continue
            k, _, v = line.rpartition(" ")
            for name in ("vllm:num_requests_running", "vllm:num_requests_waiting",
                         "vllm:generation_tokens_total", "vllm:gpu_cache_usage_perc"):
                if k.startswith(name):
                    try:
                        d[name] = d.get(name, 0.0) + float(v)
                    except ValueError:
                        pass
        return d, None

    d0, err = scrape()
    if err:
        return err
    t0 = time.time()
    time.sleep(3)
    d1, _ = scrape()
    gen = (d1.get("vllm:generation_tokens_total", 0) - d0.get("vllm:generation_tokens_total", 0)) / max(time.time() - t0, 1e-6)
    return (f"vLLM: running={int(d1.get('vllm:num_requests_running', 0))} "
            f"waiting={int(d1.get('vllm:num_requests_waiting', 0))} "
            f"gen={gen:.0f} tok/s cache={d1.get('vllm:gpu_cache_usage_perc', 0)*100:.0f}%")


def gpu():
    try:
        o = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader"],
            timeout=8).decode().strip()
        return f"GPU: {o}"
    except Exception:
        return "GPU: n/a"


if __name__ == "__main__":
    print(f"===== qwen3.5 self-host status @ {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())} =====")
    for fn in (gate0, decode, family):
        s = fn()
        if s:
            print(s)
    print(vllm_metrics())
    print(gpu())
    print("=" * 58)
