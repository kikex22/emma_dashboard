#!/usr/bin/env bash
set -eo pipefail

DEVICE="/dev/v4l/by-id/usb-Jieli_Technology_USB_PHY_2.0-video-index0"

if [[ ! -e "$DEVICE" ]]; then
  echo "Arm camera no conectada: $DEVICE" >&2
  exit 16
fi

exec gst-launch-1.0 -q \
  v4l2src device="$DEVICE" io-mode=2 ! \
  image/jpeg,width=1280,height=720,framerate=30/1 ! \
  jpegdec ! videoflip video-direction=180 ! videoconvert ! video/x-raw,format=I420 ! \
  x264enc tune=zerolatency speed-preset=ultrafast bitrate=2500 key-int-max=30 bframes=0 byte-stream=true ! \
  h264parse ! rtph264pay pt=96 config-interval=1 ! tee name=out \
  out. ! queue max-size-buffers=4 leaky=downstream ! udpsink host=127.0.0.1 port=5601 sync=false async=false \
  out. ! queue max-size-buffers=4 leaky=downstream ! udpsink host=127.0.0.1 port=5602 sync=false async=false
