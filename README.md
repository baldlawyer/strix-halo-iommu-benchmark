# `amd_iommu=off` on Strix Halo: most of the "ROCm beats Vulkan at prefill" gap is the IOMMU

A controlled measurement of the `amd_iommu=off` kernel parameter on AMD Strix
Halo (gfx1151) — ten boots, five models, both backends, with raw data.

## TL;DR

**Turning the IOMMU off recovers up to +32% of Vulkan prefill, and largely
closes the prefill gap between Vulkan and ROCm.** Measured over ten boots.
Worst boot-to-boot spread on any prefill metric: 2.0%.

| model | active | GB/fwd | Vulkan/ROCm @ `iommu=pt` | @ `amd_iommu=off` |
|---|---|---|---|---|
| gemma-4-26B-A4B q4_0 | 4B | 2.0 | 0.99 | 1.02 |
| gpt-oss-120b mxfp4 | ~5B | 2.6 | 0.99 | 1.05 |
| gemma-4-26B-A4B **Q8_0** | 4B | 4.0 | 0.86 | 1.00 |
| muse-glimmer-30B Q4_K_M *(dense)* | 27.9B | 14.0 | **0.71** | **0.91** |
| Qwen3.8-27B Q8_0 *(dense)* | 27B | 27.0 | 0.76 | 0.91 |

With the IOMMU enabled, Vulkan runs up to **29% behind** ROCm on prompt
processing. With it off, the two are within about 10% at worst and at parity on
the MoEs. **"ROCm wins prefill on Strix Halo" is, at least in part, an IOMMU
artifact rather than a backend property.**

The prefill gains themselves, by model and backend:

| model | GB/fwd | Vulkan | ROCm | boots/arm |
|---|---|---|---|---|
| gemma-4-26B-A4B q4_0 | 2.0 | +5.4% | +2.6% | 5 |
| gpt-oss-120b mxfp4 | 2.6 | +8.0% | +1.8% | 3 |
| gemma-4-26B-A4B Q8_0 | 4.0 | **+20.0%** | +3.2% | 2 |
| muse-glimmer-30B Q4_K_M | 14.0 | **+31.6%** | +3.7% | 2 |
| Qwen3.8-27B Q8_0 | 27.0 | +26.2% | +6.0% | 5 |

**Decode is unaffected** — within ±1% on nine of ten combos.

**It is not a power or clock effect.** Package power is pinned at 99–100 W in
both arms and shader clocks are *lower* with the IOMMU off.

**It is not an architecture effect.** The same MoE at Q8 gains +20.0% where it
gains +5.4% at q4 — same model family, same 4B active parameters, only
bytes-per-weight differs. On ROCm the effect rises monotonically with
active-parameter traffic (1.8 → 2.6 → 3.2 → 3.7 → 6.0%); on Vulkan it rises
too but peaks at the 14 GB model rather than the 27 GB one.

## Should you do this?

Mostly this is not a performance question at all — it is a capability question,
and the answer is usually settled before performance enters it:

1. **Do you use the XDNA2 NPU (FastFlowLM) or VM device passthrough?**
   Then `amd_iommu=off` is not available to you. It disables both. Stop here.
2. **Otherwise, turn it off** — but how much you gain depends enormously on what
   you run. On a build with no Vulkan backend, expect **+1.8% to +6.0%**, which
   is unlikely to change any decision. On the Vulkan path with a dense model or
   a higher-precision quant, it is **+20% to +32%**.

That framing is [randomfoo2's](https://www.reddit.com/r/StrixHalo/), from the
thread this repo came out of, and it is the right way round. What this data adds
is the second half: the magnitude is not a constant, and picking a model without
checking which column applies to you will mislead you by an order of magnitude.

## Why

**The two published measurements of this setting disagree with each other**,
and that turns out to be the interesting part.

- **halogen-flash-server** reports **13–16%** of prefill, with an explicit
  mechanism: the IOMMU costs power budget, so the SoC draws more watts at lower
  clocks and compute-bound prefill suffers. Their figure is "prefill fell from
  460 to 385 tok/s at 2,048 tokens." They do not state which model that was
  measured on.
- **Nathanw1014/strix-halo-llamacpp** measured it independently — 10 arms, same
  build — and got **+1.0% to +7.3% prefill**, "larger on the 35B MoE than on
  Coder-30B," with decode within noise at −2.4% to +3.9%. Their models are
  MoE/small-dense benched at pp512 in the 1,125–1,350 t/s range.

A ten-point spread between two careful groups. This measurement suggests both
are right, within their own regime.

A first attempt to reproduce it returned an ambiguous ~6% from a badly
controlled test — one model, one backend, and a before/after where "before" had
three weeks of uptime and "after" was five minutes off a cold boot. This is the
redo.

## Method

**Hardware:** Ryzen AI Max+ 395 (Radeon 8060S, gfx1151), 128 GB unified memory,
Fedora Server 44, kernel 7.1.5.

**Constant in both arms:** `amdgpu.gttsize=126976 ttm.pages_limit=32505856`.
The only variable is `iommu=pt` ↔ `amd_iommu=off`.

**A/B/A/B across ten boots**, interleaved, with up to five replicates per arm.
Replicates are the point: they measure **boot-to-boot variance**, without which
a 3% effect cannot be distinguished from drift. It came out at **≤2.0%** on
every prefill metric.

**The noise estimate got worse as replicates accumulated** — 0.2% at two boots
per arm, 0.8% at three, 2.0% at five. That is the ordinary behaviour of a range
statistic on small samples, and it is a reason to distrust any noise floor
quoted from two runs, including the earlier revisions of this document.

Identical protocol every arm:

```
boot → stop the inference server → settle 600 s idle → 30 s idle baseline
     → measure, sampling package power + shader clock at 1 Hz
```

**Five models, chosen to separate the competing explanations** — this is what
the first attempt got wrong by testing one:

| model | arch | active | GB/fwd | prefill @pt |
|---|---|---|---|---|
| gemma-4-26B-A4B q4_0 | MoE | 4B | 2.0 | ~1,330 t/s |
| gpt-oss-120b mxfp4 | MoE | ~5B | 2.6 | ~630 t/s |
| gemma-4-26B-A4B Q8_0 | MoE | 4B | 4.0 | ~1,070–1,240 t/s |
| muse-glimmer-30B Q4_K_M | dense | 27.9B | 14.0 | ~275–390 t/s |
| Qwen3.8-27B Q8_0 | dense | 27B | 27.0 | ~260–340 t/s |

The two gemmas are the key pair: same architecture and active count, different
quantization, so they separate *traffic* from *architecture*. All on both
backends. `llama-bench -p 2048,8192 -n 128 -r 3`, ROCm build
`llamacpp-rocm b1327`, Vulkan `b10679` (RADV, Mesa).

`tg128` is the **control**: bandwidth-bound, so a prefill-specific effect should
leave it alone.

**Arms were interleaved A→B→A→B**, not blocked, so monotonic drift over the
session cannot masquerade as an effect. Each arm's recorded `/proc/cmdline` is
in its `.meta`, and the harness refuses to measure if the running cmdline does
not match the arm it was told to run.

**The two models differ in more than density.** The dense model is Q8_0 and the
MoE is q4_0, so "regime" here bundles density, quantization and active
parameter count. They are endpoints chosen to bracket prefill throughput, not a
controlled model comparison, and I would not attribute the difference to any
single one of those properties.

**Other services were running** (an image-processing daemon at ~12 GB RSS, two
transcription servers) but identically in every arm, so they cancel in the A/B.
Only the inference server was stopped, because it holds GPU memory.

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
where the GPU is >50% busy.

These come from the `amdgpu` hwmon, and the driver labels them itself — no
inference required, and you can check it in one command:

```
$ cat /sys/class/hwmon/hwmon*/power1_label   # -> PPT   (package power tracking)
$ cat /sys/class/hwmon/hwmon*/freq1_label    # -> sclk  (shader clock)
```

| combo | pkg W (pt) | pkg W (off) | MHz (pt) | MHz (off) |
|---|---|---|---|---|
| dense/vulkan | 99.1 | 99.1 | 2767 | **2673** |
| dense/rocm | 99.1 | 99.1 | 2587 | **2538** |
| moe/vulkan | 100.0 | 99.5 | 2717 | **2663** |
| moe/rocm | 100.0 | 100.0 | 2620 | **2609** |

Power is pinned at 99–100 W in **both** arms — this machine hits a sustained
power cap either way — and with the IOMMU **off** the shader clock is *lower*
in all four combos, by up to 3.4%.

You cannot get +26% throughput from −3.4% clocks. Whatever this is, it is not
the SoC being handed back power budget.

### What predicts it, and what doesn't

Three hypotheses were on the table. Two are dead.

**Total footprint — dead.** gpt-oss-120b at 59 GiB shows +8.0% (Vulkan) where
the 28 GiB dense model shows +26.2%. An MoE does not read its whole footprint.

**Architecture — dead.** The decisive pair is the two gemmas: identical
architecture, identical 4B active parameters, differing only in quantization.
At q4 it gains **+5.4%**; at Q8 it gains **+20.0%**. Architecture cannot
explain a 3.7× difference between two builds of the same model.

**Active-parameter traffic — survives, cleanly on ROCm.** Bytes actually read
per forward pass orders the ROCm results monotonically:

| GB/fwd | 2.0 | 2.6 | 4.0 | 14.0 | 27.0 |
|---|---|---|---|---|---|
| ROCm | +2.6% | +1.8% | +3.2% | +3.7% | **+6.0%** |
| Vulkan | +5.4% | +8.0% | +20.0% | **+31.6%** | +26.2% |

Vulkan rises with traffic too, but peaks at 14 GB rather than 27 GB, so the
relationship there is not simply monotonic. I do not have an explanation for
that turn and am not going to invent one.

**Stated as a hypothesis, not a mechanism.** Five model points is enough to
rule two explanations out; it is not enough to establish the third.

## The backend result

This is the part with the widest consequences.

| model | Vulkan/ROCm @ `pt` | @ `off` |
|---|---|---|
| gemma-4-26B-A4B q4_0 | 0.99 | 1.02 |
| gpt-oss-120b mxfp4 | 0.99 | 1.05 |
| gemma-4-26B-A4B Q8_0 | 0.86 | 1.00 |
| muse-glimmer-30B Q4_K_M | **0.71** | **0.91** |
| Qwen3.8-27B Q8_0 | 0.76 | 0.91 |

With the IOMMU enabled, Vulkan gives up as much as 29% of ROCm's prefill. With
it off, that collapses to about 10% at worst and parity on the MoEs. The size
of Vulkan's gain tracks precisely how far behind it was.

**"ROCm wins prompt processing on Strix Halo" is a widely repeated claim, and
this suggests a large part of it is an IOMMU artifact** rather than a property
of either backend. If you have published such a comparison, it is worth
re-running with `amd_iommu=off`.

**The confound, stated plainly.** My two backends ran different llama.cpp
builds — ROCm `52d4268` (llamacpp-rocm b1327) and Vulkan `50f068fff` (b10679) —
so the *absolute* ratio is not a clean backend comparison. What is clean is the
*change* in that ratio between arms, because each backend's build is held
constant across both. So **"the IOMMU narrows the gap" stands; "the backends
are equal" does not** — the residual 0.90–0.91 on the dense models could be
build differences, backend differences, or both.

I could not eliminate this: the b1327 ROCm build ships no Vulkan backend, and
the one build that has both has a known-corrupt ROCm path on gfx1151.

## A caveat on durability

llama.cpp regressions on gfx1151 are frequent and can sit unresolved for weeks
on both the HIP and Vulkan paths, because the project does not specifically
target this arch. **Treat every number here as point-in-time**, tied to the two
builds named above, and re-measure rather than assuming it still holds on a
newer build. (Raised by randomfoo2 in the r/StrixHalo thread; it matches what
this repo's own history shows — one of the two builds used here was chosen
specifically because an earlier one silently produced wrong output on gfx1151.)

## Limits

- **One machine.** n=1 on hardware, however many boots.
- **Five models, two backends, one machine.** Enough to rule out footprint and
  architecture; not enough to establish the traffic hypothesis.
- **`iommu=pt` vs `amd_iommu=off` only.** Translated mode untested.
- **`llama-bench`, not a served endpoint** — no chat template, tokenizer or HTTP
  in the path.
- **`amd_iommu=off` disables the NPU** and turns off DMA translation
  machine-wide. Reasonable on a dedicated inference box; think about it on a
  workstation.
- I did not investigate why clocks drop slightly with the IOMMU off.
- **The two backends ran different llama.cpp builds**, so absolute
  cross-backend levels are confounded. Within-backend A/B is not — see the
  backend note above.
- **`-r 3`**, not llama-bench's default of 5.
- **Replicate counts differ by model.** The first two models have five boots
  per arm; gpt-oss-120b has three; gemma-Q8 and muse-glimmer have two each,
  since they were added later. The later models rest on the boot-to-boot spread the
  earlier design established (≤2.0%). Read them as progressively weaker
  evidence, and the two-gemma comparison — the one that kills the architecture
  hypothesis — as resting on a two boots per arm for the Q8 half.
- **One arm (A4) ran at 3992 s uptime** against ~1100–1400 s for the others. It
  reproduces the earlier arms within 0.2–0.9% on every shared combo, which is
  the built-in check that the difference did not matter.
- **"Active parameters" above are nominal**, taken from each model's
  architecture rather than measured from memory counters. The ordering is what
  matters, not the absolute byte figures.
- **Power/clock medians for the MoE rest on ~40 busy samples** (its runs are
  short); the dense combos have 176–215. The MoE power figures are the
  thinnest numbers here.
- The `.meta` files show B2 ran at a longer post-boot uptime than the other
  three (1466 s vs ~1120–1160). Settle was a fixed 600 s in all four, so this
  only means more idle before the harness attached. B1 and B2 agree to
  **0.06%** regardless, which is itself evidence that pre-measurement idle time
  does not matter at this scale.

**Before you try: if you use the NPU or VM passthrough, you can't run this**,
because `amd_iommu=off` disables both — see *Limits*. On Strix Halo that rules
out a fair number of people, and it is the main reason not to bother.

**If that doesn't apply to you and you do run it, please open an issue or reply
with your numbers.** Note also that the ROCm and Vulkan columns are very
different results: if your llama.cpp build has no Vulkan backend, the rows that
apply to you are the ROCm ones (+1.8% to +6.0%), which are unlikely to change
any decision. The large numbers are all on the Vulkan path.
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
