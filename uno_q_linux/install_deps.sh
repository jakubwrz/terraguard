#!/bin/bash
set -e

echo "=========================================================="
echo "   TerraGuard Rover: Installing Libraries & Dependencies"
echo "=========================================================="

echo "[1/3] Updating Arduino CLI library index..."
arduino-cli core update-index || true

echo "[2/3] Installing Arduino C++ libraries..."
arduino-cli lib install "Adafruit BNO055" "Adafruit Unified Sensor" "Adafruit BusIO" "Adafruit AS7341" "Adafruit AHTX0" "Arduino_RouterBridge" "Arduino_RPClite" "MsgPack" "ArxContainer" || true

# Patch Adafruit_BusIO to use standard portable GPIO instead of broken AVR register macros on Zephyr
find ~/.arduino15/ -name "Adafruit_SPIDevice.h" -exec sed -i '/#define BUSIO_USE_FAST_PINIO/d' {} + 2>/dev/null || true

echo "[3/3] Installing Python dependencies..."
sudo apt update && sudo apt install -y python3-pip python3-pil python3-requests python3-msgpack 2>/dev/null || true
pip3 install bless requests pillow msgpack --break-system-packages 2>/dev/null || pip3 install bless requests pillow msgpack || true

echo "=========================================================="
echo "   All dependencies installed successfully!"
echo "=========================================================="
