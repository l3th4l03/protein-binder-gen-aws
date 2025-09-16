# Multi-stage Dockerfile for Protein Binder Generation Pipeline
# Combines RFDiffusion, ProteinMPNN, and ColabFold in a single container

FROM nvidia/cuda:12.2-devel-ubuntu20.04

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    wget \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic link for python
RUN ln -s /usr/bin/python3 /usr/bin/python

# Upgrade pip
RUN pip install --upgrade pip

# Install AWS and common Python dependencies
RUN pip install \
    boto3 \
    botocore \
    numpy \
    torch \
    torchvision \
    torchaudio \
    --index-url https://download.pytorch.org/whl/cu121

# Create work directories
RUN mkdir -p /work/input /work/output /work/rfdiffusion /work/proteinmpnn /work/colabfold

# ============================================================================
# Install RFDiffusion
# ============================================================================
WORKDIR /work/rfdiffusion
RUN git clone https://github.com/RosettaCommons/RFdiffusion.git . && \
    pip install -e . && \
    pip install \
        hydra-core \
        omegaconf \
        icecream \
        pandas

# Download RFDiffusion models
RUN mkdir -p models && \
    wget -O models/Base_ckpt.pt https://files.ipd.uw.edu/pub/RFdiffusion/6f5902ac237024bdd0c176cb93063dc4/Base_ckpt.pt && \
    wget -O models/Complex_base_ckpt.pt https://files.ipd.uw.edu/pub/RFdiffusion/e29311f6f1bf1af907f9ef9f44b8328b/Complex_base_ckpt.pt

# ============================================================================
# Install ProteinMPNN
# ============================================================================
WORKDIR /work/proteinmpnn
RUN git clone https://github.com/dauparas/ProteinMPNN.git . && \
    pip install \
        biopython \
        matplotlib \
        argparse

# Download ProteinMPNN models
RUN mkdir -p vanilla_model_weights && \
    wget -O vanilla_model_weights/v_48_020.pt https://files.ipd.uw.edu/pub/ProteinMPNN/model_weights/v_48_020.pt

# ============================================================================
# Install ColabFold
# ============================================================================
WORKDIR /work/colabfold
RUN pip install \
    colabfold[alphafold] \
    "colabfold[alphafold] @ git+https://github.com/deepmind/alphafold" \
    jax[cuda12_pip] \
    -f https://storage.googleapis.com/jax-releases/jax_cuda_releases.html

# Download ColabFold databases (lightweight version for demo)
RUN python -m colabfold.download_databases /work/colabfold/databases

# ============================================================================
# Setup unified pipeline
# ============================================================================
WORKDIR /work

# Copy our pipeline entrypoint
COPY entrypoint.py /work/entrypoint.py

# Create convenience scripts for each tool
RUN echo '#!/bin/bash\ncd /work/rfdiffusion && python scripts/run_inference.py "$@"' > /usr/local/bin/rfdiffusion && \
    chmod +x /usr/local/bin/rfdiffusion

RUN echo '#!/bin/bash\ncd /work/proteinmpnn && python protein_mpnn_run.py "$@"' > /usr/local/bin/proteinmpnn && \
    chmod +x /usr/local/bin/proteinmpnn

RUN echo '#!/bin/bash\ncd /work/colabfold && colabfold_batch "$@"' > /usr/local/bin/colabfold && \
    chmod +x /usr/local/bin/colabfold

# Set environment variables for model paths
ENV RFDIFFUSION_MODEL_PATH="/work/rfdiffusion/models"
ENV PROTEINMPNN_MODEL_PATH="/work/proteinmpnn/vanilla_model_weights"
ENV COLABFOLD_DB_PATH="/work/colabfold/databases"

# Final setup
RUN chmod +x /work/entrypoint.py

CMD ["python", "/work/entrypoint.py"]