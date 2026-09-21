FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime
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
# `-m "not repo"`: l'immagine contiene solo `backend/`, quindi i test che leggono file
# del repository (il workflow, il pianeta spedito in `frontend/`) qui non possono
# girare. Li esegue il job `backend`, che ha il repository intero sotto mano.
CMD ["pytest", "-q", "-p", "no:cacheprovider", "-m", "not repo"]
