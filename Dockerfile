FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libtorrent-rasterbar-dev ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r slothflix && useradd -r -g slothflix -d /app slothflix

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY slothflix/ slothflix/
COPY frontend/ frontend/
COPY static/ static/
COPY entrypoint.sh .

# Create data directories
RUN mkdir -p /app/data /downloads && chown -R slothflix:slothflix /app /downloads

USER slothflix

EXPOSE 8180
CMD ["./entrypoint.sh"]
