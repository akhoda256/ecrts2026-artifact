#!/bin/bash
set -euo pipefail

LOG=log.csv
LOOPS=10   # number of repetitions

# Ask sudo password once, keep it alive while running
sudo -v

# CSV header (NOTE: energy_uj is microjoules, not joules)
echo "t_s,loop,phase,freq_khz,temp_c,energy_uj,power_w,no_turbo" > "$LOG"

read_temp() {
  # Example line: "Package id 0:  +62.0°C  ..."
  sensors | awk '/Package id 0:/ {gsub(/[+°C]/,"",$4); print $4; exit}'
}

read_energy_uj() {
  sudo cat /sys/class/powercap/intel-rapl:0/energy_uj
}

read_no_turbo() {
  cat /sys/devices/system/cpu/intel_pstate/no_turbo
}

enable_turbo() {
  echo 0 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo >/dev/null
}

disable_turbo() {
  echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo >/dev/null
}

set_boost() {
  echo 100 | sudo tee /sys/devices/system/cpu/intel_pstate/max_perf_pct >/dev/null
  echo 100 | sudo tee /sys/devices/system/cpu/intel_pstate/min_perf_pct >/dev/null
}

set_nominal() {
  # With turbo disabled, this will be much closer to a stable "nominal" regime
  echo 100 | sudo tee /sys/devices/system/cpu/intel_pstate/max_perf_pct >/dev/null
  echo 100 | sudo tee /sys/devices/system/cpu/intel_pstate/min_perf_pct >/dev/null
}

set_idle() {
  echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/max_perf_pct >/dev/null
  echo 1  | sudo tee /sys/devices/system/cpu/intel_pstate/min_perf_pct >/dev/null
}

stress_core0() {
  taskset -c 0 stress-ng --cpu 1 --timeout "$1" --quiet
}

t0=$(date +%s)

# Initialize energy for power calculation
prev_e=$(read_energy_uj)

log_loop() {
  local phase=$1
  local duration=$2
  local loopid=$3

  for ((i=0;i<duration;i++)); do
    now=$(date +%s)
    ts=$((now - t0))

    freq=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)
    temp=$(read_temp)

    e=$(read_energy_uj)
    nt=$(read_no_turbo)

    # power_w ≈ (delta_energy_uj / 1e6) / 1s
    de=$((e - prev_e))
    if (( de < 0 )); then
      # handle RAPL counter wrap-around (rare, but possible)
      de=0
    fi
    power_w=$(awk -v de="$de" 'BEGIN { printf "%.3f", de/1000000.0 }')

    echo "$ts,$loopid,$phase,$freq,$temp,$e,$power_w,$nt" >> "$LOG"

    prev_e=$e
    sleep 1
  done
}

# Ensure a known starting state: turbo ON + max perf
enable_turbo
set_boost

for ((k=1;k<=LOOPS;k++)); do
  echo "Iteration $k / $LOOPS"

  # Phase 1: BOOST (5s) -> turbo enabled, max perf
  enable_turbo
  set_boost
  stress_core0 5 &
  log_loop BOOST 5 "$k"

  # Phase 2: NOMINAL (10s) -> turbo disabled to force "nominal" regime
  disable_turbo
  set_nominal
  stress_core0 10 &
  log_loop NOMINAL 10 "$k"

  # Phase 3: IDLE (50s) -> turbo disabled + low perf window
  disable_turbo
  set_idle
  log_loop IDLE 30 "$k"
done

echo "Done. Saved to $LOG"
