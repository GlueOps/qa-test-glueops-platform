FROM python:3.11-slim

WORKDIR /app

# Install kubectl for port-forwarding
RUN apt-get update && apt-get install -y curl && \
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

# Use pytest as entrypoint (accepts pytest args)
ENTRYPOINT ["pytest"]
CMD ["-m", "smoke", "-v"]
