# Define build arguments
ARG COMFYUI_VERSION=v0.7.0
ARG MAX_JOBS=8
ARG EXT_PARALLEL=2

# Base image with CUDA runtime
FROM nvidia/cuda:12.9.1-cudnn-devel-ubuntu24.04

# Re-declare ARGs after FROM so build args apply to all build steps
ARG COMFYUI_VERSION
ARG MAX_JOBS
ARG EXT_PARALLEL

# Set CUDA architectures for building without GPUs
# 8.0=A100, 8.6=RTX30xx, 8.9=RTX40xx/L40S, 9.0=H100, 12.0=Blackwell
ENV TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0;12.0"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    MAX_JOBS=${MAX_JOBS} \
    EXT_PARALLEL=${EXT_PARALLEL} \
    CMAKE_BUILD_PARALLEL_LEVEL=${MAX_JOBS}

# Install Python and required packages
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set up workspace directory
WORKDIR /app

# Create virtual environment
RUN python3 -m venv /app/venv

# Use shell form for commands that need to source the activation script
SHELL ["/bin/bash", "-c"]

# Install torch first (stable layer - cached separately)
# cu128 is backward compatible with CUDA 12.9 runtime (cu129 wheels currently broken)
RUN source /app/venv/bin/activate && \
    pip install torch==2.9.1+cu128 torchvision==0.24.1+cu128 torchaudio==2.9.1+cu128 --index-url https://download.pytorch.org/whl/cu128

# Install flash-attn (separate layer - long compile time, matches c3-vibevoice-gradio)
RUN source /app/venv/bin/activate && \
    pip install packaging ninja wheel psutil && \
    pip install flash-attn --no-build-isolation

# === ComfyUI-specific layers below ===

# Install additional system packages for ComfyUI
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libgthread-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install triton and comfy-cli
RUN source /app/venv/bin/activate && \
    pip install triton comfy-cli

# Build and install SageAttention2 from source (c3 fork fixes SM90 build for multi-arch)
# EXT_PARALLEL: extensions built concurrently, MAX_JOBS: ninja jobs per extension
RUN source /app/venv/bin/activate && \
    git clone https://github.com/compute3ai/SageAttention.git /tmp/SageAttention && \
    cd /tmp/SageAttention && \
    EXT_PARALLEL=${EXT_PARALLEL} MAX_JOBS=${MAX_JOBS} pip install . --no-build-isolation && \
    cd / && \
    rm -rf /tmp/SageAttention

# Install ComfyUI
RUN source /app/venv/bin/activate && comfy --skip-prompt --workspace /app/ComfyUI install --version $COMFYUI_VERSION --cuda-version 12.9 --nvidia

# Install additional dependencies for model downloading
RUN source /app/venv/bin/activate && \
    pip install huggingface_hub

# Expose port (default ComfyUI port is 8188)
EXPOSE 8188

# Copy download script and entrypoint (last to enable fast rebuilds)
COPY download.py /app/download.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/download.py /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
