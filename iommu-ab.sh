#!/bin/bash
# IOMMU A/B harness — one arm per boot.
#   usage: iommu-ab.sh <arm-label> [settle_seconds]
#
# Protocol (identical for every arm):
#   stop lemonade -> settle N seconds idle -> idle baseline -> measure each
#   (model x backend) with package power / shader clock sampled at 1 Hz.
#
# Power & clock come from the amdgpu hwmon: on this APU power1_average IS the
# SoC package power (it equals the PPT line `sensors` prints). hwmon indices
# renumber across boots, so everything is resolved by name, never hardcoded.
set -u
ARM=${1:?usage: iommu-ab.sh <arm-label> [settle_seconds]}
SETTLE=${2:-600}
OUTDIR=/opt/models/shared/npu/iommu-ab
IMAGE=localhost/lemonade-npu:11.9.0
mkdir -p "$OUTDIR"

# --- resolve sysfs by name -------------------------------------------------
HW=""
for h in /sys/class/hwmon/hwmon*; do
  [ "$(cat "$h/name" 2>/dev/null)" = amdgpu ] && HW=$h && break
done
[ -n "$HW" ] || { echo "FATAL: no amdgpu hwmon found"; exit 1; }
BUSY=$(ls /sys/class/drm/card*/device/gpu_busy_percent 2>/dev/null | head -1)

sample() {  # $1 = output file; samples until killed
  while :; do
    printf '%s %s %s %s %s\n' \
      "$(date +%s)" \
      "$(cat "$HW/power1_average" 2>/dev/null || echo 0)" \
      "$(cat "$HW/freq1_input"    2>/dev/null || echo 0)" \
      "$(cat "$HW/temp1_input"    2>/dev/null || echo 0)" \
      "$(cat "$BUSY"              2>/dev/null || echo 0)"
    sleep 1
  done > "$1"
}

# --- models & backends -----------------------------------------------------
MOE=/mnt/models/gguf/gemma-4-26b-qat/gemma-4-26B_q4_0-it.gguf
BIGMOE=/mnt/models/gguf/gpt-oss-120b/gpt-oss-120b-mxfp4-00001-of-00003.gguf
DENSE=/mnt/models/.cache/huggingface/hub/models--unsloth--Qwen3.8-27B-GGUF/snapshots/4604b899a826000505a834e623272db5b7fd62f6/Qwen3.8-27B-Q8_0.gguf
ROCM=/mnt/models/llamacpp-b1327
VULKAN=/mnt/models/llamacpp-b10679-vulkan

export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user stop lemonade 2>/dev/null
sleep 3

echo "=== arm=$ARM  settling ${SETTLE}s (lemonade stopped) ..."
sleep "$SETTLE"

# idle baseline over 30 s
sample "$OUTDIR/$ARM.idle.samples" & SP=$!
sleep 30; kill $SP 2>/dev/null; wait $SP 2>/dev/null

run_combo() {  # $1=model_label $2=model_path $3=backend_label $4=bindir
  local tag="$1.$3"
  echo "--- $tag"
  sample "$OUTDIR/$ARM.$tag.samples" & local sp=$!
  podman run --rm --name iommu-ab \
    --device /dev/dri --device /dev/kfd \
    --security-opt seccomp=unconfined --security-opt label=disable \
    --userns=keep-id:uid=1000,gid=1000 \
    --volume /opt/models/shared/npu:/mnt/models:rw \
    --env HOME=/mnt/models --env LD_LIBRARY_PATH="$4" \
    "$IMAGE" \
    "$4/llama-bench" -m "$2" -p 2048,8192 -n 128 -r 3 -o json \
    > "$OUTDIR/$ARM.$tag.json" 2>"$OUTDIR/$ARM.$tag.err"
  local rc=$?
  kill $sp 2>/dev/null; wait $sp 2>/dev/null
  [ $rc -eq 0 ] || echo "    WARN: exit $rc — see $OUTDIR/$ARM.$tag.err"
}

run_combo moe   "$MOE"   rocm   "$ROCM"
run_combo moe   "$MOE"   vulkan "$VULKAN"
run_combo dense "$DENSE" rocm   "$ROCM"
run_combo dense "$DENSE" vulkan "$VULKAN"
run_combo bigmoe "$BIGMOE" rocm   "$ROCM"
run_combo bigmoe "$BIGMOE" vulkan "$VULKAN"

# --- metadata --------------------------------------------------------------
{
  echo "arm=$ARM"
  echo "cmdline=$(cat /proc/cmdline)"
  echo "uptime_s=$(cut -d. -f1 /proc/uptime)"
  echo "settle_s=$SETTLE"
  echo "kernel=$(uname -r)"
  echo "date=$(date -Is)"
} > "$OUTDIR/$ARM.meta"

echo "=== arm=$ARM done -> $OUTDIR/$ARM.*"
