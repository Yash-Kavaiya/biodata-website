FROM python:3.11-slim

# Install system dependencies (required for OpenCV)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create storage directories
RUN mkdir -p uploads storage

# Expose port (Cloud Run sets PORT env var, we default to 8080)
EXPOSE 8080

# Command to run the application
# We use shell form to ensure $PORT is expanded
CMD exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}
