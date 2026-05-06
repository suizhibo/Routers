FROM python:3.12-slim

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application code
COPY agent_routers/ ./agent_routers/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Run migrations and start app
CMD alembic upgrade head && uvicorn agent_routers.main:app --host 0.0.0.0 --port 8000
