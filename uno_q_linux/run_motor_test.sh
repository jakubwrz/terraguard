#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=========================================================="
echo "   TerraGuard: Safe Motor & Driver Diagnostic Tool"
echo "=========================================================="
echo "Stopping background rover service..."
sudo systemctl stop rover.service 2>/dev/null || true

echo "[1/2] Compiling and uploading low-power test firmware to STM32..."
arduino-cli compile --fqbn arduino:zephyr:unoq "$DIR/motor_test" --upload

echo ""
echo "=========================================================="
echo "   FIRMWARE UPLOADED!"
echo "   The 4-step gentle low-power test is running now."
echo "   Watch your wheels spin one by one."
echo "=========================================================="
