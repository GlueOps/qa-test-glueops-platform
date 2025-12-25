#!/bin/bash
# Start Chrome for UI testing with proper cleanup

# Stop any running Chrome instances
killall "Google Chrome" 2>/dev/null
sleep 2

# Clean up old profile
rm -rf /tmp/chrome_debug_profile 2>/dev/null

# Start Chrome with debugging enabled
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="/tmp/chrome_debug_profile" \
  --window-size=1920,1080 \
  --no-first-run \
  --no-default-browser-check \
  --disable-background-networking \
  --disable-backgrounding-occluded-windows \
  --disable-breakpad \
  --disable-component-extensions-with-background-pages \
  --disable-dev-shm-usage \
  --disable-extensions \
  --disable-features=TranslateUI \
  --disable-ipc-flooding-protection \
  --disable-renderer-backgrounding \
  --enable-features=NetworkService,NetworkServiceInProcess \
  --force-color-profile=srgb \
  --metrics-recording-only \
  --no-sandbox \
  --disable-gpu
