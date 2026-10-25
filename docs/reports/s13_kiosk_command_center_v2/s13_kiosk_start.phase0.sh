#!/bin/bash
# S13 kiosk session: disable screensaver/DPMS, then run Firefox fullscreen.
export DISPLAY=:0
xset s off 2>/dev/null || true
xset s noblank 2>/dev/null || true
xset dpms 0 0 0 2>/dev/null || true
xset -dpms 2>/dev/null || true
xset dpms force on 2>/dev/null || true
# keep display awake even if something re-enables blanking
( while true; do sleep 300; xset s off; xset s noblank; xset dpms 0 0 0; xset -dpms; xset dpms force on; done ) &
exec /usr/bin/firefox --kiosk --no-remote --new-instance --width 1920 --height 1080 \
  --profile /home/sergey/.mozilla/firefox/s13kiosk http://127.0.0.1:8897
