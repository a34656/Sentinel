FROM python:3.11-slim

WORKDIR /app

# System deps needed for psycopg2 and reportlab
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create reports output directory
RUN mkdir -p /app/reports

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
