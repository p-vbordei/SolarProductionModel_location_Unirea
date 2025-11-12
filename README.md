# Solar Forecast Email System (Minimal)

This is a minimal branch containing only the code required for the solar forecast email workflow.

## Features

- Solar production forecasting for CRIPVSOL ENERGY SRL - Unirea (2.9 MW AC, 2.916 MW DC)
- Excel report generation with 15-minute and hourly data
- Automated email delivery via Zoho Mail

## Quick Start

### Using UV (Recommended)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run the complete workflow
uv run python scripts/run_forecast_and_email.py
```

### Using Traditional Python

```bash
# Install dependencies
pip install -r requirements.txt

# Run the complete workflow
python scripts/run_forecast_and_email.py
```

### Individual Steps

```bash
# Step 1: Generate forecast
uv run python scripts/run_intraday_cm.py

# Step 2: Create Excel report
uv run python scripts/export_forecast_to_excel.py

# Step 3: Send email
uv run python scripts/send_forecast_zoho.py
```

## Docker Deployment

```bash
# Build and run
docker-compose up -d

# Run once
docker-compose --profile manual up solar-forecast-once

# Check logs
docker-compose logs -f solar-forecast-email
```

## Configuration

1. Ensure `scripts/email_config_zoho_working.json` exists with valid Zoho credentials
2. The system is configured for CRIPVSOL ENERGY SRL (45°06'41.76"N 27°47'04.56"E / 45.1116°N, 27.7846°E, 2.9 MW AC)
   - Panels: Canadian Solar CS6W-540 540W x 5,400 panels
   - Inverters: Huawei SUN2000-215KTL-H0 185kW x 16 units
   - Location: Unirea, Brăila, Romania

## Output Files

- **Forecasts**: `data_output/intraday/cm_forecast_*.csv`
- **Excel Reports**: `data_output/intraday/cripvsol_unirea_forecast_*.xlsx`
- **System State**: `data_output/intraday/cm_forecast_system_state.json`

## Email Recipients

- bordeivlad@gmail.com
- vpinteay@gmail.com  
- office@enevopower.ro

## Minimal Dependencies

- pandas, numpy, pytz
- catboost, scikit-learn
- requests, pvlib
- openpyxl (Excel export)
- ephem (solar calculations)
- schedule (scheduling)