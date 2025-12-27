# ThumbBot Mono

A Discord bot that automatically downloads and re-uploads videos from social media links, bypassing platform embeds that don't play natively in Discord.

## Features

- **Automatic Detection** - Monitors messages for supported video links
- **Quality Fallback** - Starts at max quality, steps down if file exceeds Discord's limit
- **FFmpeg Compression** - Last-resort compression when all quality levels are too large
- **Rich Embeds** - Shows who posted, original link, and any accompanying text
- **Async Processing** - Concurrent downloads with configurable worker pool
- **Silent Operation** - No user-facing errors, failures go to logs only
- **Prometheus Metrics** - Track downloads, uploads, and Cobalt API performance
- **OpenTelemetry Tracing** - Optional distributed tracing support

## Supported Providers

| Platform | URL Patterns |
|----------|-------------|
| Reddit | `reddit.com` |
| Instagram | `instagram.com/reel`, `instagram.com/p` |
| Facebook | `facebook.com/watch`, `facebook.com/reel`, `facebook.com/share/v`, `facebook.com/share/r`, `fb.watch` |
| Twitter/X | `twitter.com`, `x.com` |

Providers are configured in `providers.yaml`.

## Quick Start

### 1. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to **Bot** → **Reset Token** → Copy the token
4. Enable **Message Content Intent** under Privileged Gateway Intents
5. Go to **OAuth2** → **URL Generator**:
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Attach Files`, `Read Message History`
6. Invite the bot to your server using the generated URL

### 2. Deploy with Docker Compose

```bash
# Clone and enter directory
cd thumbot

# Create environment file
cp env.example .env

# Edit .env and add your DISCORD_TOKEN
nano .env

# Start services
docker compose up -d
```

### 3. Verify

```bash
# Check logs
docker compose logs -f thumbot

# Should see:
# SUCCESS | Prometheus metrics server started on port 8002
# INFO    | Loaded 10 providers
# INFO    | Connected to 1 guild(s)
# INFO    | Started 10 download worker(s)
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_TOKEN` | *required* | Discord bot token |
| `COBALT_URL` | `http://cobalt:9000` | Cobalt API endpoint |
| `PREFERRED_QUALITY` | `max` | Starting quality (`max`, `4k`, `1440p`, `1080p`, `720p`, `480p`, `360p`, `240p`, `144p`) |
| `MAX_FILE_SIZE_MB` | `8` | Max file size before quality fallback (Discord free: 8MB, Nitro: 25/50MB) |
| `MAX_CONCURRENT_DOWNLOADS` | `10` | Worker pool size |
| `DOWNLOAD_TIMEOUT` | `120` | Timeout per download in seconds |
| `PICKER_BEHAVIOR` | `all` | Multi-file handling (`first`, `last`, `all`) |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `OTEL_ENDPOINT` | *empty* | OpenTelemetry collector (e.g., `http://jaeger:4317`) |
| `OTEL_ENABLED` | `true` | Enable tracing (requires `OTEL_ENDPOINT`) |

## Deployment

### Docker Compose (Recommended for Single Server)

```yaml
services:
  cobalt:
    image: ghcr.io/imputnet/cobalt:10
    restart: unless-stopped
    environment:
      - API_PORT=9000
      - DURATION_LIMIT=10800
    networks:
      - thumbot-network

  thumbot:
    image: shoofio/thumbot-mono:1.0.0
    restart: unless-stopped
    environment:
      - DISCORD_TOKEN=${DISCORD_TOKEN}
      - COBALT_URL=http://cobalt:9000
      - MAX_FILE_SIZE_MB=8
    volumes:
      - ./temp_videos:/app/temp_videos
    networks:
      - thumbot-network
    depends_on:
      - cobalt

networks:
  thumbot-network:
    driver: bridge
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: thumbot
spec:
  replicas: 1
  selector:
    matchLabels:
      app: thumbot
  template:
    metadata:
      labels:
        app: thumbot
    spec:
      containers:
        - name: thumbot
          image: shoofio/thumbot-mono:1.0.0
          env:
            - name: DISCORD_TOKEN
              valueFrom:
                secretKeyRef:
                  name: thumbot-secrets
                  key: discord-token
            - name: COBALT_URL
              value: "http://cobalt:9000"
            - name: MAX_FILE_SIZE_MB
              value: "8"
          volumeMounts:
            - name: temp
              mountPath: /app/temp_videos
      volumes:
        - name: temp
          emptyDir: {}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cobalt
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cobalt
  template:
    metadata:
      labels:
        app: cobalt
    spec:
      containers:
        - name: cobalt
          image: ghcr.io/imputnet/cobalt:10
          env:
            - name: API_PORT
              value: "9000"
            - name: DURATION_LIMIT
              value: "10800"
          ports:
            - containerPort: 9000
---
apiVersion: v1
kind: Service
metadata:
  name: cobalt
spec:
  selector:
    app: cobalt
  ports:
    - port: 9000
      targetPort: 9000
```

Create the secret:
```bash
kubectl create secret generic thumbot-secrets \
  --from-literal=discord-token=YOUR_TOKEN_HERE
```

## Local Development

```bash
# With tracing (Jaeger UI at http://localhost:16686)
docker compose --profile tracing up -d

# Rebuild after code changes
docker compose build thumbot
docker compose up -d thumbot

# View logs
docker compose logs -f thumbot
```

## Metrics

Prometheus metrics available at `:8002/metrics`:

- `thumbot_downloads_total` - Download attempts by status
- `thumbot_uploads_total` - Discord uploads by status  
- `thumbot_cobalt_requests_total` - Cobalt API calls by status
- `thumbot_cobalt_request_duration_seconds` - Cobalt response times
- `thumbot_file_size_bytes` - Downloaded file sizes
- `thumbot_compression_total` - FFmpeg compressions by status

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│  Discord API    │◄────│    ThumbBot     │
└─────────────────┘     │                 │
                        │  - Bot Client   │
                        │  - Task Queue   │
                        │  - Workers (10) │
                        │  - Downloader   │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │     Cobalt      │
                        │  (Video API)    │
                        └─────────────────┘
```

## License

MIT

