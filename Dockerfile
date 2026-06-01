# ── BUILD STAGE ────────────────────────────────────────────────────────────────
# Use slim Python image — smaller final image, fewer vulnerabilities
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Install system dependencies psycopg2 needs
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first — Docker caches this layer
# Only re-runs pip install if requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port FastAPI runs on
EXPOSE 8000

# Run the FastAPI app with uvicorn
# --host 0.0.0.0 makes it reachable from outside the container
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]