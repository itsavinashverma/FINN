# FINN API container. Deployed on Render (free plan, see render.yaml); runs on any Docker host.
# The platform injects $PORT; 8000 is the local default.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PORT=8000 FINN_DATA_DIR=/home/user/data TZ=Asia/Kolkata

RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user backend/finn ./finn
COPY --chown=user backend/scripts ./scripts
USER user
RUN mkdir -p /home/user/data

EXPOSE 8000
CMD ["sh", "-c", "uvicorn finn.api:app --host 0.0.0.0 --port ${PORT}"]
