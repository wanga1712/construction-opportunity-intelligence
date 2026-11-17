#!/bin/bash
# S13 kiosk session: disable screensaver/DPMS, then run Firefox fullscreen.
export DISPLAY=:0
xset s off 2>/dev/null || true
xset s noblank 2>/dev/null || true
xset dpms 0 0 0 2>/dev/null || true
xset -dpms 2>/dev/null || true
xset dpms force on 2>/dev/null || true
# Use the monitor's preferred mode only when this is a single-output kiosk.
CONNECTED_OUTPUTS=$(xrandr --query | awk '$2=="connected"{print $1}')
CONNECTED_COUNT=$(printf '%s\n' "$CONNECTED_OUTPUTS" | awk 'NF{n++} END{print n+0}')
if [ "$CONNECTED_COUNT" -eq 1 ]; then
  OUTPUT="$CONNECTED_OUTPUTS"
  xrandr --output "$OUTPUT" --auto --primary --pos 0x0 --rotate normal
fi
# keep display awake even if something re-enables blanking
( while true; do sleep 300; xset s off; xset s noblank; xset dpms 0 0 0; xset -dpms; xset dpms force on; done ) &
exec /usr/bin/firefox --kiosk --no-remote --new-instance \
  --profile /home/sergey/.mozilla/firefox/s13kiosk http://127.0.0.1:8897
