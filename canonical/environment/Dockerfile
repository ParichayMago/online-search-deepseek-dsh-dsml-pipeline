FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget jq less file ripgrep lynx \
      python3 python3-pip python3-venv poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --break-system-packages --no-cache-dir \
      beautifulsoup4==4.13.4 httpx==0.28.1 pypdf==6.0.0 requests==2.32.4

RUN useradd --create-home --shell /bin/bash agent \
    && mkdir -p /app/output \
    && chown -R agent:agent /app /home/agent

WORKDIR /app
CMD ["sleep", "infinity"]
