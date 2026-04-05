FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libtorrent-rasterbar-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data /downloads

EXPOSE 8180
CMD ["python", "run.py"]
