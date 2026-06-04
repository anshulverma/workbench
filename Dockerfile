# Stage 1: Build React UI
FROM node:20-slim AS ui-builder
WORKDIR /ui
COPY ui/package.json ui/package-lock.json* ./
RUN npm install
COPY ui/ ./
RUN npm run build

# Stage 2: Python application
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
COPY entrypoint.sh .
RUN pip install --no-cache-dir -e .

# Copy built React UI from stage 1
COPY --from=ui-builder /ui/dist /app/ui-dist

EXPOSE 8421
ENTRYPOINT ["./entrypoint.sh"]
