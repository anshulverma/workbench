FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY memory/ memory/
COPY memory-config.example.yml memory-config.yml
RUN pip install --no-cache-dir -e .
EXPOSE 8422
CMD ["uvicorn", "memory.main:app", "--host", "0.0.0.0", "--port", "8422"]
