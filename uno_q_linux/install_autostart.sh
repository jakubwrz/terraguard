#!/bin/bash
# TerraGuard Rover - One-Click Headless Auto-Start Installer
# Installs systemd service so main.py runs automatically on boot in IDLE mode.

echo "=========================================================="
echo " Setting up TerraGuard Headless Auto-Start Service..."
echo "=========================================================="

# Ensure bless is installed
pip3 install bless

# Create systemd service file
cat << 'EOF' | sudo tee /etc/systemd/system/rover.service > /dev/null
[Unit]
Description=TerraGuard Autonomous Rover Headless Service
After=network.target bluetooth.target systemd-bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/arduino/terraguard/python/main.py
WorkingDirectory=/home/arduino/terraguard/python/
Restart=always
RestartSec=3
User=arduino
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd, enable, and start service
sudo systemctl daemon-reload
sudo systemctl enable rover.service
sudo systemctl restart rover.service

echo ""
echo "SUCCESS! TerraGuard Rover service installed and activated."
echo "Status check:"
sudo systemctl status rover.service --no-pager
echo ""
echo "When you power on the rover in the field, it will boot into IDLE mode automatically."
echo "No laptop or SSH required!"
