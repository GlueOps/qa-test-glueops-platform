FROM python:3.14.2-slim

WORKDIR /app

# Install kubectl for port-forwarding, libzbar for QR code decoding, and build deps for Pillow and numpy
RUN apt-get update && apt-get install -y \
    curl \
    libzbar0 \
    zlib1g-dev \
    libjpeg-dev \
    libpng-dev \
    gcc \
    g++ \
    python3-dev && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy test code
COPY . .

# Disable Python output buffering for real-time logs
ENV PYTHONUNBUFFERED=1
ENV TZ=UTC

# Use pytest as entrypoint (accepts pytest args)
ENTRYPOINT ["pytest"]
CMD ["-m", "smoke", "-v"]
