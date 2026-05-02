#!/usr/bin/env bash
set -e

TASKSET_DIR="tasksets"
OUT_DIR="dynamic_results"
IMAGE_NAME="python:3.11-slim"

SB="1.5"
L_RUNS="10"
SEED="1"

echo "=== Checking Docker installation ==="

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is not installed. Installing docker.io..."
    sudo apt update
    sudo apt install -y docker.io
else
    echo "Docker is already installed."
fi

echo
echo "=== Checking Docker permission ==="

DOCKER_CMD="docker"

if ! docker ps >/dev/null 2>&1; then
    echo "Current user cannot access Docker directly."
    echo "The script will use sudo for Docker commands."
    DOCKER_CMD="sudo docker"
else
    echo "Docker can be used without sudo."
fi

echo
echo "=== Checking input files ==="

if [ ! -f "p21.py" ]; then
    echo "Error: p21.py not found in the current folder."
    exit 1
fi

for n in 3 4 5 6 7 8; do
    if [ ! -f "$TASKSET_DIR/tasksets${n}.jsonl" ]; then
        echo "Error: $TASKSET_DIR/tasksets${n}.jsonl not found."
        echo "Please run: bash run_part2_generate.sh"
        exit 1
    fi
done

echo
echo "=== Preparing dynamic-results output folder ==="

mkdir -p "$OUT_DIR"

echo
echo "=== Running dynamic boost-cancellation experiments inside Docker ==="

$DOCKER_CMD run --rm \
    -v "$PWD:/src" \
    -v "$PWD/$TASKSET_DIR:/tasksets" \
    -v "$PWD/$OUT_DIR:/results" \
    -w /results \
    "$IMAGE_NAME" \
    bash -c "
        set -e

        echo 'Installing Python dependencies...'
        pip install numpy scipy matplotlib

        for n in 3 4 5 6 7 8; do
            echo \"Running dynamic experiment for n = \${n}...\"

            python /src/p21.py run \
                --infile /tasksets/tasksets\${n}.jsonl \
                --sb $SB \
                --L $L_RUNS \
                --seed $SEED \
                --out-png-time-box /results/dynamic_n\${n}_boost_time.png \
                --out-png-ub-box /results/dynamic_n\${n}_boost_utilization.png \
                --out-png-comp-box /results/dynamic_n\${n}_compensation_ratio.png \
                --out-png-net-box /results/dynamic_n\${n}_net_energy.png \
                --out-png-global-freq-box /results/dynamic_n\${n}_global_freq_improvement.png \
                --out-json /results/dynamic_n\${n}_data.json
        done
    "

echo
echo "=== Generated dynamic experiment outputs ==="

ls -lh "$OUT_DIR"

echo
echo "=== Done ==="
echo "Dynamic boost-cancellation results are saved in: $OUT_DIR/"