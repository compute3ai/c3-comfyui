#!/bin/bash
set -e

echo "ComfyUI Container Starting..."
echo "=============================="

# Handle empty HF_TOKEN
if [ -z "${HF_TOKEN:-}" ]; then
    unset HF_TOKEN
fi

# Download models from workflow or templates
if [ -n "${COMFYUI_WORKFLOW_B64}" ] || [ -n "${COMFYUI_TEMPLATES}" ]; then
    echo "Running model downloader..."
    source /app/venv/bin/activate && python3 /app/download.py
fi

# Start ComfyUI
echo ""
echo "Starting ComfyUI..."
echo "=============================="

exec /bin/bash -c "source /app/venv/bin/activate && comfy --workspace /app/ComfyUI launch -- --listen 0.0.0.0 --enable-cors-header --highvram"
