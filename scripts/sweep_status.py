#!/usr/bin/env python3
"""Progress snapshot for the Figure-3 family sweeps. Handles the share-baseline per-ACTOR logs
(logs/sweep_sb_<actor>.log, one process runs all 4 families) and the older per-family logs."""
import re, glob, os, time

BASE = "/Users/aravdhoot/second-look/arav-cot-monitorability"
FAMILIES = ["bignum", "iterated", "deductive", "indirection"]
N_ITEMS = 60

def or_balance():
    """OpenRouter key remaining ($). Returns float or None."""
    try:
        import json, urllib.request
        env = os.path.join(BASE, ".env")
        key = next(l.split("=", 1)[1].strip().strip('"').strip("'")
                   for l in open(env) if l.startswith("OPENROUTER_API_KEY"))
        req = urllib.request.Request("https://openrouter.ai/api/v1/auth/key",
                                     headers={"Authorization": f"Bearer {key}"})
        return json.load(urllib.request.urlopen(req, timeout=15))["data"].get("limit_remaining")
    except Exception:
        return None

def main():
    print(f"=== FAMILY SWEEP STATUS ===  ({time.strftime('%H:%M:%S')})")
    bal = or_balance()
    if bal is not None:
        print(f"  OpenRouter limit_remaining: ${bal:.2f}" + ("   ⚠️ LOW — pause runs!" if bal < 10 else ""))
    sb = sorted(glob.glob(f"{BASE}/logs/sweep_sb_*.log"))
    all_done = bool(sb)
    for lg in sb:
        actor = re.search(r"sweep_sb_(.+)\.log$", lg).group(1)
        txt = open(lg, errors="ignore").read()
        swept = re.findall(r"\.\.\. (\d+)/\d+ items swept", txt)
        filt = re.search(r"filter: kept (\d+)/", txt)
        fams_done = sum(1 for f in FAMILIES if f"exp_hints_sweep_{f}-{actor}-transcripts" in txt)
        failed = re.search(r"\] FAILED", txt)
        errs = re.findall(r"(usage limits|Key limit exceeded|429|RateLimit)", txt)
        mt = os.path.getmtime(lg)
        if failed or errs:
            state = "✗FAIL " + (errs[0] if errs else "")
        elif fams_done == len(FAMILIES):
            state = "✓done (4/4 families logged)"
        elif filt:
            state = f"{int(swept[-1]) if swept else 0}/{N_ITEMS} items · {fams_done}/4 families logged"
        else:
            state = "filter…"
        if "✓done" not in state:
            all_done = False
        idle = f"  (idle {(time.time()-mt)/60:.0f}m)" if time.time()-mt > 1200 else ""
        print(f"  {actor:18s} : {state}{idle}")
    if not sb:
        print("  (no share-baseline logs yet)")
    print("ALL_DONE" if all_done else "RUNNING")

if __name__ == "__main__":
    main()
