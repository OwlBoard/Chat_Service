# Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user and create SSL directories
RUN useradd -m -u 1000 chatuser && \
    mkdir -p /etc/ssl/private /etc/ssl/certs && \
    chown -R chatuser:chatuser /app /etc/ssl/private /etc/ssl/certs

USER chatuser

# Expose port
EXPOSE 8443

# Health check - verify the service is listening on port 8443
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.connect(('localhost', 8443)); s.close()" || exit 1

# Run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8443", \
     "--ssl-keyfile", "/etc/ssl/private/server.key", \
     "--ssl-certfile", "/etc/ssl/certs/server.crt"]