#!/bin/bash

# ---------------- CONFIGURATION ----------------
# Replace these with your details or pass them as environment variables
FILE_PATH="$1"
# -----------------------------------------------

if [ -z "$FILE_PATH" ]; then
  echo "Usage: $0 <path_to_file>"
  exit 1
fi

if [ ! -f "$FILE_PATH" ]; then
  echo "Error: File '$FILE_PATH' not found."
  exit 1
fi

FILENAME=$(basename "$FILE_PATH")
FILE_SIZE=$(wc -c < "$FILE_PATH" | tr -d ' ')

echo "Uploading $FILENAME ($FILE_SIZE bytes) to channel $CHANNEL_ID..."

# STEP 1: Get the Upload URL
# We ask Slack for a special URL where we can upload our data.
RESPONSE=$(curl -s -X POST "https://slack.com/api/files.getUploadURLExternal" \
  -H "Authorization: Bearer $SLACK_TOKEN" \
  -d "filename=$FILENAME" \
  -d "length=$FILE_SIZE")

# Check for errors in Step 1
if echo "$RESPONSE" | grep -q '"ok":false'; then
  echo "Error in Step 1: $(echo "$RESPONSE" | jq -r '.error')"
  exit 1
fi

UPLOAD_URL=$(echo "$RESPONSE" | jq -r '.upload_url')
FILE_ID=$(echo "$RESPONSE" | jq -r '.file_id')

echo "Got upload URL. Uploading data..."

# STEP 2: Upload the File
# We send the binary data to the URL Slack gave us.
# Note: --data-binary is crucial here to preserve file integrity.
curl -s -X POST "$UPLOAD_URL" --data-binary "@$FILE_PATH"

echo -e "\nFinalizing upload..."

# STEP 3: Complete the Upload
# We tell Slack the upload is done and where to display it.
JSON_PAYLOAD=$(jq -n \
                  --arg fid "$FILE_ID" \
                  --arg cid "$CHANNEL_ID" \
                  --arg fname "$FILENAME" \
                  '{files: [{id: $fid, title: $fname}], channel_id: $cid}')

FINAL_RESPONSE=$(curl -s -X POST "https://slack.com/api/files.completeUploadExternal" \
  -H "Authorization: Bearer $SLACK_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d "$JSON_PAYLOAD")

if echo "$FINAL_RESPONSE" | grep -q '"ok":true'; then
  echo "Success! File uploaded."
else
  echo "Error in Step 3: $(echo "$FINAL_RESPONSE" | jq -r '.error')"
  exit 1
fi