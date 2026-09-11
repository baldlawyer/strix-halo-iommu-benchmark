# `amd_iommu=off` on Strix Halo: +26% prefill, but not for the published reason

A controlled A/B/A/B measurement of the `amd_iommu=off` kernel parameter on
AMD Strix Halo (gfx1151), with raw data.

**The effect is real and larger than reported — in one specific corner — and
the power-budget mechanism offered for it does not hold on this machine.**

## TL;DR

| model / backend | active | prefill @2048 | delta | control (tg128) |
|---|---|---|---|---|
| **dense Qwen3.8-27B Q8_0 / Vulkan** | 27B | 258.3 → 324.9 t/s | **+25.8%** | +0.5% |
| dense Qwen3.8-27B Q8_0 / ROCm | 27B | 337.3 → 357.9 t/s | **+6.1%** | −0.1% |
| MoE gpt-oss-120b mxfp4 / Vulkan † | ~5B | 626.0 → 675.1 t/s | +7.8% | +0.4% |
| MoE gpt-oss-120b mxfp4 / ROCm † | ~5B | 628.3 → 644.0 t/s | +2.5% | +0.7% |
| MoE gemma-4-26B-A4B q4_0 / Vulkan | 4B | 1319.8 → 1391.1 t/s | +5.4% | +2.3% |
| MoE gemma-4-26B-A4B q4_0 / ROCm | 4B | 1327.3 → 1363.3 t/s | +2.7% | **+3.9%** |

Three boots per arm on the first two models and the last two; † gpt-oss-120b is
a **supplementary single boot per arm**, added later — see *Limits*.

Boot-to-boot spread over three replicates: **≤0.8% on every prefill metric**
(worst 0.8% on dense/ROCm), with one control metric at 2.0%. dense/Vulkan's own
spread is 0.6%, so its effect is ~43× it.

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

### What it does scale with — and what it doesn't

My first hypothesis was that it is a data-path cost (DMA translation during
prefill) scaling with memory traffic, using **total footprint** as the proxy.
**gpt-oss-120b was added specifically to test that, and it refutes it:** at
59 GiB it shows *less* effect (+7.8% Vulkan) than the 28 GiB dense model
(+25.8%).

Footprint is the wrong proxy, because an MoE does not read its whole footprint.
**Active parameters determine per-forward traffic**, and against that the
ordering is monotonic on both backends:

| model | ~bytes read per forward | Vulkan | ROCm |
|---|---|---|---|
| dense Qwen3.8-27B Q8_0 | ~27 GB (all weights active) | **+25.8%** | +6.1% |
| gpt-oss-120b mxfp4 (59 GiB on disk) | ~2.6 GB (~5B active) | +7.8% | +2.5% |
| gemma-4-26B-A4B q4_0 (13 GiB on disk) | ~2.0 GB (4B active) | +5.4% | +2.7% |

So the traffic idea survives only once traffic is measured as *active*
parameters rather than model size. **State that as a hypothesis, not a
mechanism.** It rests on three model points, and active traffic is confounded
with density — every dense model reads all its weights by definition, so
"dense vs MoE" fits this data exactly as well as "traffic" does. Separating
them needs a dense model and an MoE at matched active-parameter counts, which
I have not run.

**The measurements I am confident about; the interpretation is my best reading
of them.** One hypothesis has already died here — corrections welcome.

## A note on backend comparisons

At `iommu=pt`, dense prefill on Vulkan (258 t/s) trails ROCm (337 t/s). With the
IOMMU off, Vulkan (325) nearly closes on ROCm (358).

**The IOMMU penalty falls disproportionately on the Vulkan path** — +25.9% vs
+6.3% on the same model. That *delta* comparison is clean: each backend was
measured against itself with its build held constant across both arms.

**The absolute levels are not clean, and I want to be explicit about it.** The
two backends ran different llama.cpp builds — ROCm `52d4268` (llamacpp-rocm
b1327) and Vulkan `50f068fff` (b10679) — so "Vulkan 258 vs ROCm 337" conflates
backend with build version and should not be read as a backend comparison.
What survives that confound is the *size of the IOMMU effect within each
backend*, because the build is constant inside each A/B.

So: if you have benchmarked ROCm vs Vulkan prefill on this hardware, it is
worth re-checking with `amd_iommu=off`, because the two backends do not lose
the same amount to it. Whether the residual gap is the backend, the build, or
both, this data cannot say.

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
- **The two backends ran different llama.cpp builds**, so absolute
  cross-backend levels are confounded. Within-backend A/B is not — see the
  backend note above.
- **`-r 3`**, not llama-bench's default of 5.
- **gpt-oss-120b has one boot per arm, not three.** It was added after the main
  four-boot design had already pinned boot-to-boot spread at ≤0.8%, and it is
  reported as a supplement resting on that. Its two numbers should be read as
  weaker evidence than the rest.
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
