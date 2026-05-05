FROM python:3.13-slim

# Prevent Python from writing .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps only if you actually need them (kept minimal here)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY rank.py .
COPY operations ./operations

# Default command (override at runtime if needed)
ENTRYPOINT ["/bin/sh", "-c","exec python rank.py reset -F \"$@\" >> /logs/reset-$(date +%Y-%m-%dT%H-%M-%S).log 2>&1","--"]
