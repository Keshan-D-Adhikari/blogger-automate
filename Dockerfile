# Online dashboard (Render free web service, see SETUP-GUIDE.md "Online").
# Stage 1 builds the React UI, stage 2 runs the Flask API with waitress.
FROM node:20-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py links.txt ./
COPY --from=ui /ui/dist ui/dist
ENV CLOUD_SYNC=true PYTHONUNBUFFERED=1
CMD ["python", "-W", "ignore", "server.py"]
