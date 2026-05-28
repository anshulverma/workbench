FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir -e .
EXPOSE 8421
CMD ["python", "-m", "uvicorn", "workbench.main:app", "--host", "0.0.0.0", "--port", "8421"]
