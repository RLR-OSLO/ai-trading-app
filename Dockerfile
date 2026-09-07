FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY trader ./trader
RUN pip install --no-cache-dir .

USER nobody
CMD ["ai-trader"]

