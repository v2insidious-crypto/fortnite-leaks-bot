FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY discord_leaks_bot.py leaks_bot_config.json ./
# state file will be created at runtime; mount as volume to persist
RUN mkdir -p /data
ENV PYTHONUNBUFFERED=1
# Use env var DISCORD_WEBHOOK_URL (overrides config). Don't hardcode webhook in image.
CMD ["python", "-u", "discord_leaks_bot.py", "--loop"]
