# Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# System dependencies for pydub + ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install Python dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Ensure logs directory exists
RUN mkdir -p /app/logs

# Environment
ENV PYTHONUNBUFFERED=1

# Default command (Render will override per service)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]