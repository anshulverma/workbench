FROM python:3.12-slim
WORKDIR /app
ARG HTTP_PROXY
ARG HTTPS_PROXY
COPY pyproject.toml .
COPY src/ src/
COPY entrypoint.sh .
RUN pip install --no-cache-dir -e .
EXPOSE 8421
ENTRYPOINT ["./entrypoint.sh"]
