FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# El host 0.0.0.0 es obligatorio en Docker para exponer el puerto
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
