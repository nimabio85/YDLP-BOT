FROM python:3.12-slim

# Install ffmpeg and aria2 (required/optional download helpers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    aria2 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Temp download and data directories
RUN mkdir -p /tmp/ytdl-bot /app/data

CMD ["python", "bot.py"]
