#!/usr/bin/env bash
set -e

TASKSET_DIR="tasksets"
OUT_DIR="acceptance"
IMAGE_NAME="python:3.11-slim"

SB="1.5"
BOOST_UPS="0.05,0.10,0.20,0.30"

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
echo "=== Preparing acceptance output folder ==="

mkdir -p "$OUT_DIR"

echo
echo "=== Running acceptance-ratio experiments inside Docker ==="

$DOCKER_CMD run --rm \
    -v "$PWD:/src" \
    -v "$PWD/$TASKSET_DIR:/tasksets" \
    -v "$PWD/$OUT_DIR:/acceptance" \
    -w /acceptance \
    "$IMAGE_NAME" \
    bash -c "
        set -e

        echo 'Installing Python dependencies...'
        pip install numpy scipy matplotlib

        echo 'Running acceptance experiment for n = 3...'
        python /src/p21.py diff \
            --infile /tasksets/tasksets3.jsonl \
            --sb $SB \
            --boost-ups $BOOST_UPS \
            --out-png /acceptance/acceptance3.png

        echo 'Running acceptance experiment for n = 4...'
        python /src/p21.py diff \
            --infile /tasksets/tasksets4.jsonl \
            --sb $SB \
            --boost-ups $BOOST_UPS \
            --out-png /acceptance/acceptance4.png

        echo 'Running acceptance experiment for n = 5...'
        python /src/p21.py diff \
            --infile /tasksets/tasksets5.jsonl \
            --sb $SB \
            --boost-ups $BOOST_UPS \
            --out-png /acceptance/acceptance5.png

        echo 'Running acceptance experiment for n = 6...'
        python /src/p21.py diff \
            --infile /tasksets/tasksets6.jsonl \
            --sb $SB \
            --boost-ups $BOOST_UPS \
            --out-png /acceptance/acceptance6.png

        echo 'Running acceptance experiment for n = 7...'
        python /src/p21.py diff \
            --infile /tasksets/tasksets7.jsonl \
            --sb $SB \
            --boost-ups $BOOST_UPS \
            --out-png /acceptance/acceptance7.png

        echo 'Running acceptance experiment for n = 8...'
        python /src/p21.py diff \
            --infile /tasksets/tasksets8.jsonl \
            --sb $SB \
            --boost-ups $BOOST_UPS \
            --out-png /acceptance/acceptance8.png
    "

echo
echo "=== Generated acceptance figures ==="

ls -lh "$OUT_DIR"

echo
echo "=== Done ==="
echo "Acceptance-ratio figures are saved in: $OUT_DIR/"