FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping adduser \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh \
    && useradd --uid 1000 --create-home wakehub

ENV PORT=8765 \
    WAKEHUB_HOST=0.0.0.0 \
    WAKEHUB_CONFIG_DIR=/config \
    WAKEHUB_DATA_DIR=/data \
    PYTHONUNBUFFERED=1

VOLUME ["/config", "/data"]
EXPOSE 8765
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "wakehub.main"]
