#!/usr/bin/env bash
set -e

SHARED_DIR="shared"
IMAGE_NAME="python:3.11-slim"

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
echo "=== Preparing shared folder ==="

mkdir -p "$SHARED_DIR"

if [ ! -f "plot.py" ]; then
    echo "Error: plot.py not found in the current folder."
    exit 1
fi

if [ ! -f "log.csv" ]; then
    echo "Error: log.csv not found in the current folder."
    exit 1
fi

cp plot.py "$SHARED_DIR/"
cp log.csv "$SHARED_DIR/"

echo "Copied plot.py and log.csv to $SHARED_DIR/"

echo
echo "=== Running plot.py inside Docker ==="

$DOCKER_CMD run --rm \
    -v "$PWD/$SHARED_DIR:/work" \
    -w /work \
    "$IMAGE_NAME" \
    bash -c "pip install pandas matplotlib && python plot.py"

echo
echo "=== Generated output files ==="

ls -lh "$SHARED_DIR"

echo
echo "Expected figures:"
echo "$SHARED_DIR/real-frequency.png"
echo "$SHARED_DIR/real-temperature.png"
echo "$SHARED_DIR/real-power.png"