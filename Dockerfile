# Образ для BotHost и любого хостинга с Docker.
#
# На BotHost включите «Использовать собственный Dockerfile»: иначе
# автоопределение найдёт webapp/app.js и попробует запустить Mini App
# через Node — контейнер будет падать в цикле.

FROM python:3.11-slim

WORKDIR /app

# Логи сразу в панель хостинга, без буфера; без мусора от pip.
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# База: data/shop.db. На хостинге этот путь — постоянный том,
# иначе при передеплое пропадут балансы и заказы.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Сервер Mini App слушает 0.0.0.0:$PORT. BotHost сам передаёт PORT
# (по умолчанию 3000), поэтому здесь его не задаём.
EXPOSE 3000

# HEALTHCHECK сознательно нет: прокси BotHost (Traefik) не пускает трафик,
# пока проверка не стала healthy, и домен отвечает 404. Проверка вручную: GET /health.
CMD ["python", "-u", "main.py"]
