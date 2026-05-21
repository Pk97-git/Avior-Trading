FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2, lxml, mplfinance
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev libxml2-dev libxslt-dev \
    libfreetype6-dev libpng-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir \
        torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create static dir
RUN mkdir -p app/static/charts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
