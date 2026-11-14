FROM python:3.12-slim

WORKDIR /app
COPY vkv_backend /app/vkv_backend

ENV PYTHONUNBUFFERED=1 \
    VKV_AG_HOST=0.0.0.0 \
    VKV_AG_PORT=8780 \
    VKV_AG_HOME=/data

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8780

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8780/v1/durum', timeout=3)"

CMD ["python", "-m", "vkv_backend"]
