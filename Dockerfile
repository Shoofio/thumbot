# Stage 1: Download static ffmpeg binaries
FROM python:3.11-slim AS ffmpeg-builder

RUN apt-get update && apt-get install -y --no-install-recommends wget xz-utils && \
    wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz && \
    tar xf ffmpeg-release-amd64-static.tar.xz && \
    mv ffmpeg-*-amd64-static/ffmpeg ffmpeg-*-amd64-static/ffprobe /usr/local/bin/ && \
    rm -rf ffmpeg-*

# Stage 2: Final image
FROM python:3.11-slim

WORKDIR /app

# Copy static ffmpeg from builder (159MB vs 448MB from apt)
COPY --from=ffmpeg-builder /usr/local/bin/ffmpeg /usr/local/bin/ffprobe /usr/local/bin/

# Install Python dependencies first (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create temp directory
RUN mkdir -p temp_videos

# Default environment
ENV LOG_LEVEL=INFO
ENV COBALT_URL=http://cobalt:9000
ENV METRICS_PORT=8002
ENV TEMP_DIR=./temp_videos
ENV PYTHONPATH=/app

# Expose metrics port
EXPOSE 8002

# Copy application code LAST (only this layer rebuilds on code changes)
COPY . ./thumbot/

# Move providers.yaml to app root
RUN mv ./thumbot/providers.yaml ./providers.yaml 2>/dev/null || true

# Run the bot
ENTRYPOINT ["python", "-m", "thumbot.main"]
