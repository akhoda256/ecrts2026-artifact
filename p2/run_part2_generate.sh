#!/usr/bin/env bash
set -e

OUT_DIR="tasksets"
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
echo "=== Checking input files ==="

if [ ! -f "p21.py" ]; then
    echo "Error: p21.py not found in the current folder."
    exit 1
fi

echo
echo "=== Preparing output folder ==="

mkdir -p "$OUT_DIR"

echo
echo "=== Generating task sets inside Docker ==="

$DOCKER_CMD run --rm \
    -v "$PWD:/src" \
    -v "$PWD/$OUT_DIR:/work" \
    -w /work \
    "$IMAGE_NAME" \
    bash -c "
        set -e

        echo 'Installing Python dependencies...'
        pip install numpy scipy matplotlib

        echo 'Generating task sets for n = 3...'
        python /src/p21.py generate --out tasksets3.jsonl --n 3 --m 200 --umin 70

        echo 'Generating task sets for n = 4...'
        python /src/p21.py generate --out tasksets4.jsonl --n 4 --m 200 --umin 70

        echo 'Generating task sets for n = 5...'
        python /src/p21.py generate --out tasksets5.jsonl --n 5 --m 200 --umin 70

        echo 'Generating task sets for n = 6...'
        python /src/p21.py generate --out tasksets6.jsonl --n 6 --m 200 --umin 70

        echo 'Generating task sets for n = 7...'
        python /src/p21.py generate --out tasksets7.jsonl --n 7 --m 200 --umin 70

        echo 'Generating task sets for n = 8...'
        python /src/p21.py generate --out tasksets8.jsonl --n 8 --m 200 --umin 70
    "

echo
echo "=== Generated files ==="

ls -lh "$OUT_DIR"

echo
echo "=== Done ==="
echo "Task sets are saved in: $OUT_DIR/"