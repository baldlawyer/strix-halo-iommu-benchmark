#!/usr/bin/env python3
"""Summarize IOMMU A/B arms. usage: iommu-summarize.py <arm> [<arm> ...]

Reads <arm>.<model>.<backend>.json (llama-bench) and .samples (1 Hz sysfs)
from /opt/models/shared/npu/iommu-ab and prints per-arm results plus an
A-vs-B comparison that reports BOOT-TO-BOOT spread, which is the real noise
floor and the thing the first uncontrolled attempt could not estimate.
"""
import json, os, statistics as st, sys

D = "/opt/models/shared/npu/iommu-ab"
COMBOS = [("moe", "rocm"), ("moe", "vulkan"), ("dense", "rocm"), ("dense", "vulkan"),
          ("bigmoe", "rocm"), ("bigmoe", "vulkan")]

def bench(arm, model, backend):
    p = f"{D}/{arm}.{model}.{backend}.json"
    if not os.path.exists(p): return {}
    # The container entrypoint writes an NPU warning to stdout ahead of
    # llama-bench's JSON, so parse from the first "[" rather than the top.
    raw = open(p).read()
    i = raw.find("[")
    if i < 0: return {}
    try: rows = json.loads(raw[i:])
    except Exception: return {}
    out = {}
    for r in rows:
        npr, ngen = int(r.get("n_prompt", 0)), int(r.get("n_gen", 0))
        key = f"pp{npr}" if npr and not ngen else (f"tg{ngen}" if ngen else None)
        if key: out[key] = (float(r.get("avg_ts", 0)), float(r.get("stddev_ts", 0)))
    return out

def power(arm, model, backend, busy_min=50):
    """Package power (W) and shader clock (MHz) while the GPU is actually busy."""
    p = f"{D}/{arm}.{model}.{backend}.samples"
    if not os.path.exists(p): return None
    w, f, t = [], [], []
    for line in open(p):
        parts = line.split()
        if len(parts) != 5: continue
        try: _, uw, hz, mc, busy = (int(x) for x in parts)
        except ValueError: continue
        if busy < busy_min: continue
        w.append(uw / 1e6); f.append(hz / 1e6); t.append(mc / 1e3)
    if not w: return None
    return dict(n=len(w), w=st.median(w), w_max=max(w),
                mhz=st.median(f), mhz_max=max(f), temp=st.median(t))

def meta(arm):
    p = f"{D}/{arm}.meta"
    if not os.path.exists(p): return {}
    return dict(l.rstrip("\n").split("=", 1) for l in open(p) if "=" in l)

arms = sys.argv[1:]
for arm in arms:
    m = meta(arm)
    cl = m.get("cmdline", "")
    mode = "amd_iommu=off" if "amd_iommu=off" in cl else ("iommu=pt" if "iommu=pt" in cl else "?")
    print(f"\n{'='*74}\nARM {arm}   [{mode}]   uptime@run={m.get('uptime_s','?')}s  settle={m.get('settle_s','?')}s")
    print(f"{'combo':<16}{'pp2048':>13}{'pp8192':>13}{'tg128':>12}{'pkg W':>9}{'MHz':>7}{'°C':>6}")
    for model, backend in COMBOS:
        b, pw = bench(arm, model, backend), power(arm, model, backend)
        if not b: print(f"{model+'/'+backend:<16}{'(missing)':>13}"); continue
        def c(k): return f"{b[k][0]:.1f}" if k in b else "-"
        ps = (f"{pw['w']:>9.1f}{pw['mhz']:>7.0f}{pw['temp']:>6.0f}") if pw else f"{'-':>9}{'-':>7}{'-':>6}"
        print(f"{model+'/'+backend:<16}{c('pp2048'):>13}{c('pp8192'):>13}{c('tg128'):>12}{ps}")

# --- A vs B, with boot-to-boot spread --------------------------------------
A = [a for a in arms if "iommu=pt" in meta(a).get("cmdline", "")]
B = [a for a in arms if "amd_iommu=off" in meta(a).get("cmdline", "")]
if A and B:
    print(f"\n{'='*74}\nA (iommu=pt) = {A}\nB (amd_iommu=off) = {B}")
    print("\n%-16s%-9s%12s%12s%9s%10s" % ("combo", "metric", "A mean", "B mean", "delta", "A spread"))
    print("-" * 74)
    for model, backend in COMBOS:
        for k in ("pp2048", "pp8192", "tg128"):
            av = [bench(a, model, backend).get(k, (None,))[0] for a in A]
            bv = [bench(b, model, backend).get(k, (None,))[0] for b in B]
            av = [x for x in av if x]; bv = [x for x in bv if x]
            if not av or not bv: continue
            am, bm = sum(av)/len(av), sum(bv)/len(bv)
            spread = (max(av)-min(av))/am*100 if len(av) > 1 else float("nan")
            flag = ""
            if len(av) > 1 and abs(bm-am)/am*100 <= (max(av)-min(av))/am*100:
                flag = "  <- within A's own boot-to-boot spread"
            print("%-16s%-9s%12.1f%12.1f%8.1f%%%9.1f%%%s" %
                  (model+"/"+backend, k, am, bm, (bm-am)/am*100, spread, flag))
        for lbl, key in (("pkg W", "w"), ("MHz", "mhz")):
            av = [power(a, model, backend) for a in A]; bv = [power(b, model, backend) for b in B]
            av = [x[key] for x in av if x]; bv = [x[key] for x in bv if x]
            if not av or not bv: continue
            am, bm = sum(av)/len(av), sum(bv)/len(bv)
            print("%-16s%-9s%12.1f%12.1f%8.1f%%%9s" %
                  (model+"/"+backend, lbl, am, bm, (bm-am)/am*100, ""))
    print("""
Read tg128 first: it is the control. halogen's claim is that prefill moves
while bandwidth-bound work "held exactly". If tg128 moves with prefill, the
cause is a general power/clock shift, not a prefill-specific IOMMU effect.
Any delta inside A's own boot-to-boot spread is not a result.""")
