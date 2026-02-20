# VOICEcheck Dockerfile
# Multi-stage build for optimized image size

# Stage 1: Builder
FROM python:3.11-slim AS builder

# Set working directory
WORKDIR /build

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Explicitly install JWT libraries (fix for docker cache issues)
RUN pip install --no-cache-dir --user 'python-jose[cryptography]>=3.3.0' 'passlib[bcrypt]>=1.7.4' 'email-validator>=2.0.0'


# Stage 2: Production
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/root/.local/bin:$PATH \
    DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY:-} \
    DEEPGRAM_MODEL=${DEEPGRAM_MODEL:-whisper} \
    DEEPGRAM_LANGUAGE=${DEEPGRAM_LANGUAGE:-ru} \
    DEEPGRAM_TIMEOUT=${DEEPGRAM_TIMEOUT:-300} \
    TRANSCRIPTION_CACHE_SIZE=${TRANSCRIPTION_CACHE_SIZE:-100} \
    LOG_LEVEL=${LOG_LEVEL:-INFO} \
    MAX_FILE_SIZE=${MAX_FILE_SIZE:-52428800} \
    ALLOWED_EXTENSIONS=${ALLOWED_EXTENSIONS:-.mp3,.wav,.m4a,.ogg,.flac,.mp4,.webm} \
    ZAI_API_KEY=${ZAI_API_KEY:-} \
    ZAI_MODEL=${ZAI_MODEL:-claude-3-5-sonnet} \
    LLM_TIMEOUT=${LLM_TIMEOUT:-30} \
    EXPORT_CACHE_TTL=${EXPORT_CACHE_TTL:-3600}

# Install runtime dependencies (ffmpeg for audio processing, curl for health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -r voicecheck && useradd -r -g voicecheck voicecheck

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Fix permissions - make sure everything is executable
RUN chmod -R 755 /root/.local/bin && \
    chown -R root:root /root/.local

ENV PATH=/root/.local/bin:$PATH

# Set working directory
WORKDIR /app

# Create necessary directories
RUN mkdir -p /app/uploads /app/static \
    && chown -R voicecheck:voicecheck /app \
    && chmod 755 /app

# Copy application code
COPY --chown=voicecheck:voicecheck app ./app
COPY --chown=voicecheck:voicecheck static ./static

# Copy Alembic files for migrations
COPY --chown=voicecheck:voicecheck alembic ./alembic
COPY alembic.ini /app/alembic.ini

# Expose port
EXPOSE 8000

# Health check with timeout
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Switch to non-root user (commented out to fix uvicorn permission issues)
# USER voicecheck

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application (as root for now to avoid permission issues with /root/.local)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
