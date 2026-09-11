#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=========================================================="
echo "   TerraGuard Rover: Compiling & Flashing MCU Core"
echo "=========================================================="

echo "[1/2] Compiling & Uploading sketch to STM32 (Zephyr)..."
arduino-cli compile --fqbn arduino:zephyr:unoq "$DIR/sketch" --upload

echo "[2/2] Starting Python Rover Service..."
echo "=========================================================="
python3 "$DIR/python/main.py"
