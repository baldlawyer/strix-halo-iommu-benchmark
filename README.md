# `amd_iommu=off` on Strix Halo: +26% prefill, but not for the published reason

A controlled A/B/A/B measurement of the `amd_iommu=off` kernel parameter on
AMD Strix Halo (gfx1151), with raw data.

**The effect is real and larger than reported — in one specific corner — and
the power-budget mechanism offered for it does not hold on this machine.**

## TL;DR

| model / backend | prefill @2048 | `iommu=pt` → `amd_iommu=off` | control (tg128) |
|---|---|---|---|
| **dense Qwen3.8-27B Q8_0 / Vulkan** | 257.9 → 324.6 t/s | **+25.9%** | +0.4% |
| dense Qwen3.8-27B Q8_0 / ROCm | 336.6 → 357.8 t/s | **+6.3%** | −0.1% |
| MoE gemma-4-26B-A4B q4_0 / Vulkan | 1319.0 → 1391.3 t/s | +5.5% | +2.0% |
| MoE gemma-4-26B-A4B q4_0 / ROCm | 1326.7 → 1365.8 t/s | +3.0% | **+3.9%** |

Boot-to-boot noise floor: **0.0–0.5%**. The dense/Vulkan result is ~130× that.

Three takeaways:

1. **It is regime- and backend-dependent.** Worth +26% on a dense 27B through
   Vulkan; effectively nothing on a small-active MoE through ROCm, where the
   *control* gained more than prefill did. If you tested this on a small MoE and
   saw noise, that is consistent with this data — you tested the least
   sensitive case.
2. **The power-budget mechanism does not hold here.** Package power is pinned at
   99–100 W in *both* arms and shader clocks are **lower** with the IOMMU off.
   +26% throughput cannot come from −3.4% clocks.
3. **Decode is unaffected**, which is what makes this prefill-specific rather
   than a general lift.

## Why

Two sources report `amd_iommu=off` being worth 13–16% of prefill on this
silicon, one with an explicit mechanism: the IOMMU costs power budget, so the
SoC draws more watts at lower clocks, and compute-bound prefill suffers.

A first attempt to reproduce it returned an ambiguous ~6% from a badly
controlled test — one model, one backend, and a before/after where "before" had
three weeks of uptime and "after" was five minutes off a cold boot. This is the
redo.

## Method

**Hardware:** Ryzen AI Max+ 395 (Radeon 8060S, gfx1151), 128 GB unified memory,
Fedora Server 44, kernel 7.1.5.

**Constant in both arms:** `amdgpu.gttsize=126976 ttm.pages_limit=32505856`.
The only variable is `iommu=pt` ↔ `amd_iommu=off`.

**A/B/A/B across four boots**, two replicates per arm. Two replicates is the
point: it measures **boot-to-boot variance**, without which a 3% effect cannot
be distinguished from drift.

Identical protocol every arm:

```
boot → stop the inference server → settle 600 s idle → 30 s idle baseline
     → measure, sampling package power + shader clock at 1 Hz
```

**Two models, chosen to bracket the prefill regime** — the single most important
design decision, and what the first attempt got wrong:

| | model | prefill regime |
|---|---|---|
| MoE | gemma-4-26B-A4B q4_0 (4B active) | ~1,330 t/s |
| dense | Qwen3.8-27B Q8_0 | ~260–340 t/s |

Both on both backends. `llama-bench -p 2048,8192 -n 128 -r 3`, ROCm build
`llamacpp-rocm b1327`, Vulkan `b10679` (RADV, Mesa).

`tg128` is the **control**: bandwidth-bound, so a prefill-specific effect should
leave it alone.

## Noise floor

Same arm, different boots:

| combo | metric | A1 | A2 | spread |
|---|---|---|---|---|
| dense/vulkan | pp2048 | 258.2 | 257.6 | 0.2% |
| dense/vulkan | pp8192 | 247.0 | 247.0 | 0.0% |
| dense/rocm | pp2048 | 336.0 | 337.2 | 0.4% |
| moe/rocm | pp2048 | 1327.1 | 1326.2 | 0.1% |

Eleven of twelve metrics reproduced within 0.5%.

## Results

Mean of two boots per arm, tok/s:

| combo | metric | `iommu=pt` | `amd_iommu=off` | delta |
|---|---|---|---|---|
| **dense/vulkan** | pp2048 | 257.9 | 324.6 | **+25.9%** |
| | pp8192 | 247.0 | 306.8 | **+24.2%** |
| | *tg128 (control)* | 7.8 | 7.8 | *+0.4%* |
| **dense/rocm** | pp2048 | 336.6 | 357.8 | **+6.3%** |
| | pp8192 | 319.8 | 336.7 | +5.3% |
| | *tg128 (control)* | 7.8 | 7.7 | *−0.1%* |
| **moe/vulkan** | pp2048 | 1319.0 | 1391.3 | +5.5% |
| | pp8192 | 1203.2 | 1261.3 | +4.8% |
| | *tg128 (control)* | 70.2 | 71.6 | *+2.0%* |
| **moe/rocm** | pp2048 | 1326.7 | 1365.8 | +3.0% |
| | pp8192 | 1158.1 | 1188.8 | +2.6% |
| | *tg128 (control)* | 62.8 | 65.2 | *+3.9%* |

Note the last row: the control gained **more** than prefill did. That is a
general few-percent lift, not a prefill effect. Reported as such.

## The mechanism does not hold up

Package power and median shader clock, sampled at 1 Hz, filtered to samples
where the GPU is >50% busy:

| combo | pkg W (pt) | pkg W (off) | MHz (pt) | MHz (off) |
|---|---|---|---|---|
| dense/vulkan | 99.1 | 99.1 | 2767 | **2673** |
| dense/rocm | 99.1 | 99.1 | 2587 | **2538** |
| moe/vulkan | 100.0 | 99.5 | 2717 | **2663** |
| moe/rocm | 100.0 | 100.0 | 2620 | **2609** |

Power is pinned at 99–100 W in **both** arms — this machine hits a sustained
power cap either way — and with the IOMMU **off** the shader clock is *lower*
in all four combos, by up to 3.4%.

You cannot get +26% throughput from −3.4% clocks. This reads as a data-path
cost — DMA translation overhead on the memory path during prefill — rather than
a thermal or power-budget one. That would also explain why the size of the win
tracks how much memory traffic prefill generates, and why decode, with a very
different access pattern, is untouched.

**The measurements I am confident about; the interpretation is my best reading
of them.** Corrections welcome.

## A note on backend comparisons

At `iommu=pt`, dense prefill on Vulkan (258 t/s) trails ROCm (337 t/s). With the
IOMMU off, Vulkan (325) nearly closes on ROCm (358).

**The IOMMU penalty falls disproportionately on RADV's prefill path.** If you
have benchmarked ROCm vs Vulkan prefill on this hardware, it is worth
re-checking with `amd_iommu=off` — some of that gap may be the IOMMU rather than
the backend.

## Limits

- **One machine.** n=1 on hardware, however many boots.
- **Two models, two backends.** The regime dependence is strong enough that I
  would not extrapolate to an untested model shape.
- **`iommu=pt` vs `amd_iommu=off` only.** Translated mode untested.
- **`llama-bench`, not a served endpoint** — no chat template, tokenizer or HTTP
  in the path.
- **`amd_iommu=off` disables the NPU** and turns off DMA translation
  machine-wide. Reasonable on a dedicated inference box; think about it on a
  workstation.
- I did not investigate why clocks drop slightly with the IOMMU off.

**If you run this on your box, please open an issue or reply with your numbers.**
n=1 is the main weakness here and replication is the only fix.

## Reproducing

```bash
./iommu-ab.sh <arm-label> 600      # once per boot, per arm
./iommu-summarize.py A1 A2 B1 B2   # compare
```

The harness resolves hwmon paths by name (indices renumber across boots),
verifies `/proc/cmdline` before measuring so an arm cannot be silently
mislabelled, and writes a `.meta` sentinel on completion. About two hours wall
clock, nearly all of it settle timers.

## Data layout

`data/` holds, per arm (`A1`, `A2` = `iommu=pt`; `B1`, `B2` = `amd_iommu=off`):

| file | contents |
|---|---|
| `<arm>.<model>.<backend>.json` | raw `llama-bench` JSON |
| `<arm>.<model>.<backend>.samples` | `epoch power_uW freq_Hz temp_mC busy%` at 1 Hz |
| `<arm>.<model>.<backend>.err` | backend/device enumeration |
| `<arm>.idle.samples` | 30 s idle baseline after settle |
| `<arm>.meta` | `/proc/cmdline`, uptime at run, settle, kernel, timestamp |

LUKS UUIDs are redacted from the cmdline in `.meta`; nothing else is altered.

## Credit

The 13–16% figure and the power-budget mechanism come from the
**halogen-flash-server** documentation, which publishes its full kernel command
line and measurement conditions — the only reason a controlled comparison was
possible at all. **Nathanw1014/strix-halo-llamacpp** independently reports
needing `amd_iommu=off` for its figures.

This work revises the *magnitude* (regime-dependent, 3–26% rather than a flat
13–16%) and disputes the *mechanism*, on one machine. It does not dispute that
the parameter matters — it plainly does.

## License

Data (`data/`): [CC0 1.0](LICENSE-DATA). Scripts: [MIT](LICENSE).
