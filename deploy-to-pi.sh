#!/bin/bash
set -e

FIREBASE_KEY=$(ls -t ~/Downloads/dog-door-*-firebase-adminsdk*.json 2>/dev/null | head -1)
if [ -z "$FIREBASE_KEY" ]; then
    echo "Error: No Firebase key found in ~/Downloads"
    exit 1
fi
echo "Using Firebase key: $FIREBASE_KEY"

scp "$FIREBASE_KEY" \
    "$(dirname "$0")/door_controller.py" \
    "$(dirname "$0")/dog-door.service" \
    "$(dirname "$0")/setup-pi.sh" \
    pat0222@dogdoorpi.local:/home/pat0222/

ssh pat0222@dogdoorpi.local "mv /home/pat0222/$(basename "$FIREBASE_KEY") /home/pat0222/firebase-key.json && chmod +x /home/pat0222/setup-pi.sh"

echo "Files copied. Run setup with:"
echo "  ssh pat0222@dogdoorpi.local './setup-pi.sh'"
