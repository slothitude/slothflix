FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libtorrent-rasterbar-dev ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY slothflix/ slothflix/
COPY frontend/ frontend/
COPY static/ static/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Create data directories
RUN mkdir -p /app/data /downloads

EXPOSE 8180
CMD ["./entrypoint.sh"]
