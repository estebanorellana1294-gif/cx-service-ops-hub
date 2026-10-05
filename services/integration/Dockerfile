FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cx_integration ./cx_integration

RUN useradd --create-home appuser
USER appuser

ENTRYPOINT ["python", "-m", "cx_integration"]
CMD ["--base-url", "http://mock-api:8000"]
