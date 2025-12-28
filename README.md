# ThumbBot Mono

A Discord bot that automatically downloads and re-uploads videos from social media links, bypassing platform embeds that don't play natively in Discord.

Uses [Cobalt](https://github.com/imputnet/cobalt) under the hood for video extraction.

## Features

- **Automatic Detection** - Monitors messages for supported video links
- **Quality Fallback** - Starts at max quality, steps down if file exceeds Discord's limit
- **FFmpeg Compression** - Last-resort compression when all quality levels are too large
- **Rich Embeds** - Shows who posted, original link, and any accompanying text
- **Webhook Impersonation** - Optional mode that posts as the original user via webhooks
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
   - Bot Permissions: see below
6. Invite the bot to your server using the generated URL

#### Required Bot Permissions

| Permission | Purpose |
|------------|---------|
| Send Messages | Post videos and embeds |
| Attach Files | Upload downloaded videos |
| Read Message History | Access messages with links |
| Manage Messages | Delete original user messages |
| Embed Links | Rich embed support |
| Manage Webhooks | *Optional* - Required for webhook impersonation mode |

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
| `WEBHOOK_IMPERSONATION` | `false` | Send as user via webhook (requires Manage Webhooks permission) |
| `WEBHOOK_SUFFIX` | ` (ThumbBot)` | Suffix appended to username when using webhooks |
| `SUPPRESS_LINK_EMBEDS` | `true` | Wrap URLs in `<>` to prevent Discord auto-embeds (webhook mode only) |

## Webhook Impersonation Mode

When `WEBHOOK_IMPERSONATION=true`, the bot sends messages via Discord webhooks, making them appear as if they came from the original user (with a suffix like `(ThumbBot)`).

**Behavior differences:**
- No rich embed - sends the original message exactly as typed
- User's avatar and name displayed
- URLs wrapped in `<>` to suppress Discord's link previews
- Falls back to normal bot mode in threads (webhooks don't work there)

**Example:**
```
# User posts:
check this out https://reddit.com/r/funny/comments/abc123

# Bot deletes original, reposts as "Username (ThumbBot)":
check this out <https://reddit.com/r/funny/comments/abc123>
[video attachment]
```

## Deployment

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
    image: shoofio/thumbot-mono:1.2.0
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

