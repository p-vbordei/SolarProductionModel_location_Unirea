# Email Setup for Solar Forecast System

## Overview

The system sends automated Excel reports with solar production forecasts for CRIPVSOL ENERGY SRL - Unirea (2.9 MW AC, 2.916 MW DC).

## Configuration

All email settings are stored in `scripts/email_config_zoho_working.json`:
- **SMTP**: Zoho Mail (smtp.zoho.eu:587)
- **From**: solarforecastingservices@vollko.com
- **Recipients**: bordeivlad@gmail.com
- **Schedule**: 6 AM and 2 PM daily (via Docker)

## Usage

### Email Workflow (3-Step Process)

**Step 1: Generate forecast data**
```bash
# Generate forecast with improved hybrid model (recommended)
python scripts/hybrid_forecast_with_tracking.py

# OR generate standard forecast
python scripts/run_intraday_cm.py
```

**Step 2: Create Excel report**
```bash
# Generate Excel file from latest forecast data
python scripts/export_forecast_to_excel.py
```

**Step 3: Send email report**
```bash
# Send email with latest forecast data and Excel attachment
python scripts/send_forecast_zoho.py
```

### Production Deployment
The Docker container automatically runs the 3-step process at scheduled times:
```yaml
# docker-compose.yml
solar-forecast-email:
  command: ["sh", "-c", "while true; do hour=$$(date +%H); if [ $$hour -eq 6 ] || [ $$hour -eq 14 ]; then python scripts/hybrid_forecast_with_tracking.py && python scripts/export_forecast_to_excel.py && python scripts/send_forecast_zoho.py; fi; sleep 3600; done"]
```

## Email Contents

Each email includes:
- **Excel Attachment**: 15-minute and 1-hour forecasts
- **HTML Summary**: Next 24h and 48h production
- **Key Metrics**: Peak power, total energy, capacity factor
- **Forecast Uncertainty**: P10-P90 confidence bands

## Files

- `email_forecast_service.py` - Core email functionality
- `email_config_zoho_working.json` - Zoho credentials and settings
- `send_forecast_zoho.py` - Email sender (uses latest forecast data)
- `hybrid_forecast_with_tracking.py` - Improved forecast generation
- `run_intraday_cm.py` - Standard forecast generation
- `export_forecast_to_excel.py` - Excel report generation