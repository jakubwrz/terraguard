#!/bin/bash
# TerraGuard Rover - One-Click Auto-Start Uninstaller
# Stops and disables rover.service so the Arduino boots back to default App Lab UI.

echo "=========================================================="
echo " Disabling TerraGuard Auto-Start Service..."
echo "=========================================================="

sudo systemctl stop rover.service
sudo systemctl disable rover.service
sudo rm -f /etc/systemd/system/rover.service
sudo systemctl daemon-reload

echo ""
echo "SUCCESS! TerraGuard auto-start service removed."
echo "The Arduino will now boot back to its default App Lab desktop UI."
