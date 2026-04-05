FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libtorrent-rasterbar-dev ffmpeg curl \
    && curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz | tar xz -C /usr/local/bin --strip-components=1 docker/docker \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data /downloads
RUN chmod +x entrypoint.sh

EXPOSE 8180
CMD ["./entrypoint.sh"]
