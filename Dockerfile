# Один образ на всё: бот, дашборд и резервные копии запускаются из него разными командами (docker-compose.yml).
FROM python:3.12-slim

# Время по Москве: от него считаются напоминания, опрос через четыре месяца и даты в дашборде.
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 TZ=Europe/Moscow
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ключи (.env) и данные кандидатов (data/) в образ не попадают — см. .dockerignore.
COPY . .
