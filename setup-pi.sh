#!/bin/bash
# Run by deploy-to-pi.sh via ssh. Assumes these files are in /home/pat0222/:
#   door_controller.py, peripheral_controller.py, dog-door.service, peripheral-controller.service, firebase-key.json
set -ex

echo "==> Installing build tools..."
sudo apt-get update -q
sudo apt-get install -y python3-dev gcc fonts-dejavu-core

echo "==> Setting up dog-door directory..."
mkdir -p /home/pat0222/dog-door
[ -f /home/pat0222/door_controller.py ] && mv /home/pat0222/door_controller.py /home/pat0222/dog-door/
[ -f /home/pat0222/peripheral_controller.py ] && mv /home/pat0222/peripheral_controller.py /home/pat0222/dog-door/
[ -f /home/pat0222/firebase-key.json ] && mv /home/pat0222/firebase-key.json /home/pat0222/dog-door/

echo "==> Setting up Python venv..."
python3 -m venv /home/pat0222/dog-door/venv
/home/pat0222/dog-door/venv/bin/pip install -v RPi.GPIO luma.oled firebase-admin astral

echo "==> Installing systemd services..."
sudo mv /home/pat0222/dog-door.service /etc/systemd/system/
sudo mv /home/pat0222/peripheral-controller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable NetworkManager-wait-online.service
sudo systemctl enable peripheral-controller
sudo systemctl restart peripheral-controller
sudo systemctl enable dog-door
sudo systemctl restart dog-door

echo "==> Configuring passwordless sudo for reboot..."
echo 'pat0222 ALL=(ALL) NOPASSWD: /sbin/reboot' | sudo tee /etc/sudoers.d/dog-door-reboot
echo 'pat0222 ALL=(ALL) NOPASSWD: /sbin/shutdown' | sudo tee /etc/sudoers.d/dog-door-shutdown
echo 'pat0222 ALL=(ALL) NOPASSWD: /usr/bin/systemctl' | sudo tee /etc/sudoers.d/dog-door-systemctl

echo "==> Enabling I2C..."
sudo raspi-config nonint do_i2c 0

echo "==> Done! Run: journalctl -fu dog-door"
