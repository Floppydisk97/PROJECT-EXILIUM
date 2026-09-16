FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt \
    && useradd --create-home --uid 10001 exilium
COPY --chown=exilium:exilium . .
USER exilium
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir -r requirements-dev.lock.txt
USER exilium
CMD ["pytest", "-q", "-p", "no:cacheprovider"]
