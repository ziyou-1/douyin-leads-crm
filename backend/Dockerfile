FROM python:3.11-slim

WORKDIR /app

# Use Tencent Cloud Debian/PyPI mirrors
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|http://deb.debian.org/debian|http://mirrors.cloud.tencent.com/debian|g; s|http://deb.debian.org/debian-security|http://mirrors.cloud.tencent.com/debian-security|g; s|https://deb.debian.org/debian|http://mirrors.cloud.tencent.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|http://deb.debian.org|http://mirrors.cloud.tencent.com|g; s|https://deb.debian.org|http://mirrors.cloud.tencent.com|g' /etc/apt/sources.list; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple --trusted-host mirrors.cloud.tencent.com -r requirements.txt

# Install Chromium and its OS-level dependencies for Playwright browser automation
# Use the npmmirror mirror to avoid slow/unreliable downloads from the default CDN
ENV PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
RUN playwright install --with-deps chromium
RUN pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple --trusted-host mirrors.cloud.tencent.com Pillow moviepy imageio-ffmpeg && apt-get update && apt-get install -y --no-install-recommends fonts-wqy-microhei ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY . .

# Make start script executable
RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]
