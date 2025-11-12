"""
Configuration file for solar production forecasting

IMPORTANT: All forecast outputs MUST be in CET/CEST (Europe/Berlin) timezone
This applies to:
- CSV files (timestamps must show local CET/CEST time)
- Excel reports (all times in CET/CEST)
- API responses (must include timezone metadata)
- Email reports (clearly state CET/CEST timezone)
"""
from datetime import datetime
import pytz

# Location configurations
LOCATIONS = {
    'chisineu_cris': {
        'name': 'Chisineu Cris PV',
        'latitude': 46.5225,  # 46°31'21"N
        'longitude': 21.5158,  # 21°30'57"E
        'country': 'RO',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 55.0  # Calibrated from 2026 data (8211 MWh/744h = 11 MW avg in July)
    },
    'aricestii_rahtivani': {
        'name': 'Aricestii Rahtivani PV Phase 2',
        'latitude': 44.9500,  # 44°57'0"N
        'longitude': 25.8333,  # 25°49'59.99"E
        'country': 'RO',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 65.0  # Calibrated from 2026 data (9701 MWh/744h = 13 MW avg in July)
    },
    # Rooftop PV locations
    'bulgaria_rooftop': {
        'name': 'Bulgaria Rooftop PV',
        'latitude': 42.6977,  # Sofia
        'longitude': 23.3219,
        'country': 'BG',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 0.733,
        'type': 'rooftop'
    },
    'croatia_rooftop': {
        'name': 'Croatia Rooftop PV',
        'latitude': 45.8150,  # Zagreb
        'longitude': 15.9819,
        'country': 'HR',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 1.874,
        'type': 'rooftop'
    },
    'czech_republic_rooftop': {
        'name': 'Czech Republic Rooftop PV',
        'latitude': 50.0755,  # Prague
        'longitude': 14.4378,
        'country': 'CZ',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 0.687,
        'type': 'rooftop'
    },
    'hungary_rooftop': {
        'name': 'Hungary Rooftop PV',
        'latitude': 47.4979,  # Budapest
        'longitude': 19.0402,
        'country': 'HU',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 2.318,
        'type': 'rooftop'
    },
    'lithuania_rooftop': {
        'name': 'Lithuania Rooftop PV',
        'latitude': 54.6872,  # Vilnius
        'longitude': 25.2797,
        'country': 'LT',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 0.475,
        'type': 'rooftop'
    },
    'poland_rooftop_1': {
        'name': 'Poland Rooftop PV Site 1',
        'latitude': 52.2297,  # Warsaw
        'longitude': 21.0122,
        'country': 'PL',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 5.386,
        'type': 'rooftop'
    },
    'poland_rooftop_2': {
        'name': 'Poland Rooftop PV Site 2',
        'latitude': 50.0647,  # Krakow (different location)
        'longitude': 19.9450,
        'country': 'PL',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 1.560,
        'type': 'rooftop'
    },
    'slovakia_rooftop': {
        'name': 'Slovakia Rooftop PV',
        'latitude': 48.1486,  # Bratislava
        'longitude': 17.1077,
        'country': 'SK',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 1.406,
        'type': 'rooftop'
    },
    'romania_rooftop': {
        'name': 'Romania Rooftop PV',
        'latitude': 44.4268,  # Bucharest
        'longitude': 26.1025,
        'country': 'RO',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 38.000,
        'type': 'rooftop'
    },
    'cm_forecast': {
        'name': 'CRIPVSOL ENERGY SRL',
        'latitude': 45.1116,  # 45°06'41.76"N
        'longitude': 27.7846,  # 27°47'04.56"E
        'country': 'RO',
        'timezone': 'Europe/Berlin',
        'estimated_capacity_mw': 2.9,  # AC max output (DC: 2.916 MW, AC: 2.9 MW)
        'dc_capacity_mw': 2.916,
        'ac_capacity_mw': 2.9,
        'type': 'intraday',
        'panels': {
            'type': 'Canadian Solar CS6W-540',  # 5,400 x 540W
            'power_wp': 540,  # 540W per panel
            'quantity': 5400,  # Total: 5,400
            'tilt': 25,  # degrees
            'orientation': 180  # South (azimuth)
        },
        'inverters': {
            'type': 'Huawei SUN2000-215KTL-H0',
            'power_kw': 185,
            'quantity': 16
        }
    }
}

# Time range configuration
FORECAST_START = datetime(2024, 1, 1, 0, 0, 0, tzinfo=pytz.UTC)
FORECAST_END = datetime(2030, 12, 31, 23, 59, 59, tzinfo=pytz.UTC)
HISTORICAL_YEAR = 2023  # For training data

# Model configuration
QUANTILES = [0.1, 0.25, 0.5, 0.75, 0.9]  # P10, P25, P50, P75, P90

# Physical parameters
DEGRADATION_RATE_ANNUAL = 0.005  # 0.5% per year
PERFORMANCE_RATIO_DEFAULT = 0.92  # Based on actual measured data
TEMPERATURE_COEFFICIENT = -0.0040  # -0.40% per degree C above 25C
SOILING_LOSS = 0.02  # 2% soiling losses

# Weather-dependent performance ratios (based on actual data analysis)
# VALIDATED: Plant achieved 97.1% capacity on June 30, 2025 (summer clear day)
# These values are calibrated for year-round accuracy with conservative estimates
PERFORMANCE_RATIO_BY_WEATHER = {
    'clear_sky': 0.90,      # 90% for clear days - Conservative year-round estimate
    'partly_cloudy': 0.85,  # 85% for partly cloudy (reduced proportionally)
    'cloudy': 0.78,         # 78% for cloudy days (reduced proportionally)
    'overcast': 0.70,       # 70% for heavy clouds/rain (reduced proportionally)
    'default': 0.85         # Default 85% (reduced proportionally)
}

# Weather API configuration
WEATHER_SOURCES = [
    {
        'name': 'open_meteo_era5',
        'type': 'reanalysis',
        'priority': 1,
        'api_url': 'https://archive-api.open-meteo.com/v1/archive',
        'variables': ['temperature_2m', 'shortwave_radiation', 'direct_normal_irradiance', 
                     'diffuse_radiation', 'windspeed_10m', 'cloudcover', 'relative_humidity_2m']
    },
    {
        'name': 'open_meteo_gfs',
        'type': 'forecast',
        'priority': 2,
        'api_url': 'https://api.open-meteo.com/v1/forecast',
        'variables': ['temperature_2m', 'shortwave_radiation', 'direct_normal_irradiance',
                     'diffuse_radiation', 'windspeed_10m', 'cloudcover']
    },
    {
        'name': 'open_meteo_default',
        'type': 'mixed',
        'priority': 3,
        'api_url': 'https://api.open-meteo.com/v1/forecast',
        'variables': ['temperature_2m', 'shortwave_radiation', 'windspeed_10m', 'cloudcover']
    }
]

# 2026 monthly production data for validation (MWh)
VALIDATION_DATA_2026 = {
    'chisineu_cris': {
        1: 1978.54, 2: 2893.06, 3: 5437.45, 4: 6041.11,
        5: 7920.32, 6: 7963.75, 7: 8211.88, 8: 8151.33,
        9: 5297.73, 10: 4448.21, 11: 2735.91, 12: 1182.54
    },
    'aricestii_rahtivani': {
        1: 2337.10, 2: 3417.54, 3: 6423.41, 4: 7136.58,
        5: 9356.65, 6: 9407.96, 7: 9701.09, 8: 9629.53,
        9: 6258.37, 10: 5254.74, 11: 3231.84, 12: 1396.74
    }
}

# Annual production estimates for rooftop PV (MWh/year)
ROOFTOP_ANNUAL_PRODUCTION = {
    'bulgaria_rooftop': 877,
    'croatia_rooftop': 2127,
    'czech_republic_rooftop': 649,
    'hungary_rooftop': 2488,
    'lithuania_rooftop': 436,
    'poland_rooftop_1': 5249,
    'poland_rooftop_2': 1520,
    'slovakia_rooftop': 1371,
    'romania_rooftop': 41000
}

# Intraday forecasting configuration
INTRADAY_FORECAST_DAYS = 7  # 7-day rolling forecast
INTRADAY_RESOLUTION_MINUTES = 15  # 15-minute precision
INTRADAY_UPDATE_FREQUENCY_HOURS = 1  # Update every hour

# Output aggregation levels
AGGREGATION_LEVELS = ['15min', '1hour']

# Timezone configuration
# CRITICAL: All outputs MUST use this timezone for display
OUTPUT_TIMEZONE = 'Europe/Berlin'  # CET/CEST
OUTPUT_TIMEZONE_NAME = 'CET/CEST'
OUTPUT_TIMEZONE_NOTICE = "All timestamps are in CET/CEST (Europe/Berlin timezone)"

# Logging configuration
LOG_LEVEL = 'INFO'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'