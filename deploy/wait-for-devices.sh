#!/bin/sh
set -eu

camera=$1
audio=$2

echo "Waiting for camera $camera, GPIO and ALSA device $audio."
while :; do
    if [ -c "$camera" ] && [ -r "$camera" ] && [ -w "$camera" ] &&
       [ -c /dev/gpiochip0 ] && [ -r /dev/gpiochip0 ] && [ -w /dev/gpiochip0 ] &&
       /usr/bin/timeout 3s /usr/bin/aplay -q -D "$audio" -t raw -f S16_LE -r 22050 -c 1 -d 1 /dev/zero; then
        echo "Camera and GPIO nodes are accessible and ALSA is ready."
        exit 0
    fi
    sleep 1
done
