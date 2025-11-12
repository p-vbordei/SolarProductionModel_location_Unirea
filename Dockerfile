# Minimal Dockerfile for Solar Forecast Email System
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for catboost
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    build-essential \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
ENV UV_SYSTEM_PYTHON=1
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files
COPY pyproject.toml requirements.txt ./

# Install Python dependencies
RUN uv sync --frozen --no-dev

# Copy only required scripts
COPY scripts/config.py \
     scripts/email_forecast_service.py \
     scripts/export_forecast_to_excel.py \
     scripts/export_weather_parameters.py \
     scripts/forecast_comparison.py \
     scripts/intraday_aggregator.py \
     scripts/intraday_forecast_model.py \
     scripts/intraday_system_with_spm.py \
     scripts/intraday_weather_fetcher.py \
     scripts/run_forecast_and_email.py \
     scripts/run_intraday_cm.py \
     scripts/send_forecast_zoho.py \
     scripts/smart_persistence_model.py \
     ./scripts/

# Copy email configuration
COPY scripts/email_config_zoho_working.json ./scripts/

# Copy required data input files
COPY data_input/pv_plants_metadata.csv ./data_input/

# Create output directories
RUN mkdir -p data_output/intraday \
    data_output/model_tracking \
    data_output/calibration \
    data_cache/weather \
    data_cache/intraday \
    logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Default command - run the workflow
CMD ["uv", "run", "python", "scripts/run_forecast_and_email.py"]