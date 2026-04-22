#!/bin/bash
# Install FFmpeg if not present
if ! command -v ffmpeg &> /dev/null; then
    apt-get update && apt-get install -y ffmpeg
fi

# Run the server
cd /app
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port $PORT