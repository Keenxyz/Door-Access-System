#!/bin/sh
set -eu

camera=$1
audio=$2
shift 2

case "$camera" in
    ''|*[!0-9]*) ;;
    *)
        while [ "$camera" != 0 ] && [ "${camera#0}" != "$camera" ]; do
            camera=${camera#0}
        done
        camera=/dev/video$camera
        ;;
esac

require_audio=false
for flag do
    if [ "$flag" = --enable-unlock ]; then
        require_audio=true
    fi
done

echo "Waiting for camera $camera and GPIO."
if "$require_audio"; then
    echo "Automatic unlock also requires ALSA device $audio for liveness prompts."
fi

while :; do
    if [ -c "$camera" ] && [ -r "$camera" ] && [ -w "$camera" ] &&
       [ -c /dev/gpiochip0 ] && [ -r /dev/gpiochip0 ] && [ -w /dev/gpiochip0 ]; then
        if ! "$require_audio" ||
           /usr/bin/timeout 3s /usr/bin/aplay -q -D "$audio" -t raw -f S16_LE -r 22050 -c 1 -d 1 /dev/zero; then
            echo "Required hardware is ready."
            exit 0
        fi
    fi
    sleep 1
done
