FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for OpenCV and other libraries
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libopenblas0 \
    liblapack3 \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY requirements.txt .
COPY . .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Expose Flask port
EXPOSE 5000

# Set production environment
ENV FLASK_ENV=production

# Run application with gunicorn and eventlet worker (production-safe)
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:5000", "--timeout", "300", "--access-logfile", "-", "main:app"]
