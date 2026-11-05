FROM python:3.15-slim@sha256:8c13a3f37a6a5b71498228e902c4b9f51c1f7900d49fabf71f9a650c6120e0d0 AS runtime
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
