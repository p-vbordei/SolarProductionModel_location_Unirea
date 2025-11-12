# Solar Forecast Email System - Minimal Branch

This minimal branch contains only the code required for the solar forecast email workflow.

## Core Scripts

1. **run_intraday_cm.py** - Generates solar production forecast
2. **export_forecast_to_excel.py** - Creates Excel report from forecast data
3. **send_forecast_zoho.py** - Sends email with Excel attachment

## Wrapper Script

**run_forecast_and_email.py** - Runs all 3 scripts in sequence

## Quick Start

```bash
# Using uv (recommended)
uv run python scripts/run_forecast_and_email.py

# Using traditional Python
python scripts/run_forecast_and_email.py
```

## Docker

```bash
# Run scheduled (6 AM and 2 PM)
docker-compose up -d

# Run once
docker-compose --profile manual up solar-forecast-once
```

## Critical Notes

- **Location**: CRIPVSOL ENERGY SRL, Unirea, Județul Brăila (45.1116°N, 27.7846°E)
- **Capacity**: 2.9 MW AC, 2.916 MW DC
- **Panels**:
  - Canadian Solar CS6W-540 540W x 5,400 panels (fixed)
  - Total: 5,400 panels
- **Panel Configuration**: 25° tilt angle, South orientation
- **Inverters**: Huawei SUN2000-215KTL-H0 185kW x 16 units
- **Email Config**: Must have `scripts/email_config_zoho_working.json`
- **Weather Data**: Uses Open-Meteo API (real data only, no synthetic data)
- **GitHub Repository**: https://github.com/p-vbordei/SolarProductionModel_location_Unirea

## All Errors Fixed

- ✅ Pandas deprecation warnings fixed (fillna → ffill/bfill)
- ✅ Ephem library added for solar calculations
- ✅ All dependencies minimal and working
