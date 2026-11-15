# FINN: one container serving both the API and the built frontend from the same origin (no
# CORS, no separate frontend host/build-time API URL to configure). Deployed on Render (free
# plan, see render.yaml); runs on any Docker host. The platform injects $PORT; 8000 is the local
# default. Local development does NOT use this image -- see README (uvicorn + `npm run dev`
# as two separate processes, with Vite's dev-server proxy bridging them).

FROM node:22-alpine AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PORT=8000 FINN_DATA_DIR=/home/user/data FINN_STATIC_DIR=/home/user/app/static TZ=Asia/Kolkata

RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user backend/finn ./finn
COPY --chown=user backend/scripts ./scripts
COPY --chown=user --from=frontend-build /app/dist ./static
USER user
RUN mkdir -p /home/user/data

EXPOSE 8000
CMD ["sh", "-c", "uvicorn finn.api:app --host 0.0.0.0 --port ${PORT}"]
