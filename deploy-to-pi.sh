#!/bin/bash
set -e

PI=pat0222@dogdoorpi.local
DIR="$(dirname "$0")"

FIREBASE_KEY=$(ls -t ~/Downloads/dog-door-*-firebase-adminsdk*.json 2>/dev/null | head -1)
if [ -z "$FIREBASE_KEY" ]; then
    echo "Error: No Firebase key found in ~/Downloads"
    exit 1
fi
echo "Using Firebase key: $FIREBASE_KEY"

echo "==> Setting up passwordless SSH..."
ssh-copy-id "$PI"

echo "==> Copying files to Pi..."
scp "$FIREBASE_KEY" \
    "$DIR/door_controller.py" \
    "$DIR/peripheral_controller.py" \
    "$DIR/dog-door.service" \
    "$DIR/peripheral-controller.service" \
    "$DIR/setup-pi.sh" \
    "$PI:/home/pat0222/"
ssh "$PI" "mv /home/pat0222/$(basename "$FIREBASE_KEY") /home/pat0222/firebase-key.json && chmod +x /home/pat0222/setup-pi.sh"

echo "==> Running setup on Pi (you may be prompted for sudo password)..."
ssh -t "$PI" "bash /home/pat0222/setup-pi.sh"

echo "==> Done!"
