"""
Export weather parameters used in forecasting to help debug low production values
Creates a parameters-<forecast-day> folder with detailed weather inputs
"""
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
import logging

logger = logging.getLogger(__name__)


def export_weather_parameters(weather_df: pd.DataFrame, location_config: dict, 
                            forecast_timestamp: datetime, output_dir: str):
    """
    Export detailed weather parameters used in the forecast
    
    Args:
        weather_df: Weather data used for forecast
        location_config: Location configuration including GPS coords
        forecast_timestamp: When the forecast was generated
        output_dir: Base output directory
    """
    # Create parameters folder
    forecast_day = forecast_timestamp.strftime('%Y%m%d')
    params_dir = os.path.join(output_dir, f"parameters-{forecast_day}")
    os.makedirs(params_dir, exist_ok=True)
    
    # 1. Export location info
    location_info = {
        "location_name": location_config.get('name', 'Unknown'),
        "latitude": location_config.get('latitude'),
        "longitude": location_config.get('longitude'),
        "timezone": location_config.get('timezone', 'UTC'),
        "capacity_mw": location_config.get('estimated_capacity_mw'),
        "weather_source": "Open-Meteo API",
        "api_url": "https://api.open-meteo.com/v1/forecast",
        "forecast_generated_at": forecast_timestamp.isoformat()
    }
    
    with open(os.path.join(params_dir, 'location_info.json'), 'w') as f:
        json.dump(location_info, f, indent=2)
    
    # 2. Export raw weather data
    weather_df.to_csv(os.path.join(params_dir, 'raw_weather_data.csv'))
    
    # 3. Export weather statistics
    weather_stats = {
        "data_period": {
            "start": str(weather_df.index[0]),
            "end": str(weather_df.index[-1]),
            "hours": len(weather_df),
            "resolution": "15-minute interpolated from hourly"
        },
        "ghi_statistics": {
            "max": float(weather_df['ghi'].max()) if 'ghi' in weather_df else None,
            "mean": float(weather_df['ghi'].mean()) if 'ghi' in weather_df else None,
            "min": float(weather_df['ghi'].min()) if 'ghi' in weather_df else None,
            "daylight_mean": float(weather_df[weather_df['ghi'] > 0]['ghi'].mean()) if 'ghi' in weather_df else None,
            "peak_hours_mean": float(weather_df.between_time('10:00', '14:00')['ghi'].mean()) if 'ghi' in weather_df else None
        },
        "temperature_statistics": {
            "max": float(weather_df['temperature'].max()) if 'temperature' in weather_df else None,
            "mean": float(weather_df['temperature'].mean()) if 'temperature' in weather_df else None,
            "min": float(weather_df['temperature'].min()) if 'temperature' in weather_df else None
        },
        "cloud_cover_statistics": {
            "mean": float(weather_df['cloud_cover'].mean()) if 'cloud_cover' in weather_df else None,
            "clear_hours": int((weather_df['cloud_cover'] < 20).sum()) if 'cloud_cover' in weather_df else None,
            "cloudy_hours": int((weather_df['cloud_cover'] > 80).sum()) if 'cloud_cover' in weather_df else None
        }
    }
    
    with open(os.path.join(params_dir, 'weather_statistics.json'), 'w') as f:
        json.dump(weather_stats, f, indent=2)
    
    # 4. Export daily weather summary
    if not weather_df.empty:
        daily_summary = []
        for date in pd.date_range(start=weather_df.index[0].date(), 
                                 end=weather_df.index[-1].date(), freq='D'):
            day_data = weather_df[weather_df.index.date == date.date()]
            if not day_data.empty:
                summary = {
                    "date": str(date.date()),
                    "ghi_total_kwh_m2": float(day_data['ghi'].sum() / 4000) if 'ghi' in day_data else None,  # 15-min to hours, W to kW
                    "ghi_peak_w_m2": float(day_data['ghi'].max()) if 'ghi' in day_data else None,
                    "temperature_avg_c": float(day_data['temperature'].mean()) if 'temperature' in day_data else None,
                    "cloud_cover_avg_pct": float(day_data['cloud_cover'].mean()) if 'cloud_cover' in day_data else None,
                    "daylight_hours": float(len(day_data[day_data['ghi'] > 0]) / 4) if 'ghi' in day_data else None
                }
                daily_summary.append(summary)
        
        df_daily = pd.DataFrame(daily_summary)
        df_daily.to_csv(os.path.join(params_dir, 'daily_weather_summary.csv'), index=False)
    
    # 5. Export forecast model parameters
    from config import PERFORMANCE_RATIO_BY_WEATHER, PERFORMANCE_RATIO_DEFAULT, TEMPERATURE_COEFFICIENT
    
    model_params = {
        "pv_system": {
            "tilt_angle_degrees": 30,
            "azimuth_degrees": 180,
            "performance_ratio_default": PERFORMANCE_RATIO_DEFAULT,
            "performance_ratio_by_weather": PERFORMANCE_RATIO_BY_WEATHER,
            "soiling_factor": "Included in performance ratio",
            "temperature_coefficient": TEMPERATURE_COEFFICIENT,
            "inverter_efficiency": 0.99,
            "dc_clipping": "Capped at nameplate capacity"
        },
        "atmospheric": {
            "atmospheric_transmission": 0.78,
            "calibration_enabled": True,
            "albedo": 0.25
        },
        "calibration": {
            "peak_hour_factors": "1.08-1.10",
            "morning_factors": "1.05-1.12",
            "note": "Reduced to prevent overforecasting"
        }
    }
    
    with open(os.path.join(params_dir, 'model_parameters.json'), 'w') as f:
        json.dump(model_params, f, indent=2)
    
    # 6. Create a summary report
    summary_text = f"""Weather Parameters Export Summary
================================
Generated: {forecast_timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}
Location: {location_config.get('name', 'Unknown')}
GPS Coordinates: {location_config.get('latitude')}, {location_config.get('longitude')}
Capacity: {location_config.get('estimated_capacity_mw')} MW

Weather Data Source: Open-Meteo API
Data Period: {weather_df.index[0]} to {weather_df.index[-1]}

Key Statistics:
- GHI Max: {weather_df['ghi'].max():.0f} W/m² (if 'ghi' in weather_df else 'N/A')
- GHI Mean (daylight): {weather_df[weather_df['ghi'] > 0]['ghi'].mean():.0f} W/m² (if 'ghi' in weather_df else 'N/A')
- Cloud Cover Mean: {weather_df['cloud_cover'].mean():.1f}% (if 'cloud_cover' in weather_df else 'N/A')
- Temperature Range: {weather_df['temperature'].min():.1f}°C to {weather_df['temperature'].max():.1f}°C (if 'temperature' in weather_df else 'N/A')

Files Created:
- location_info.json: GPS coordinates and configuration
- raw_weather_data.csv: Complete weather data used
- weather_statistics.json: Statistical summary
- daily_weather_summary.csv: Day-by-day breakdown
- model_parameters.json: PV system parameters
"""
    
    with open(os.path.join(params_dir, 'README.txt'), 'w') as f:
        f.write(summary_text)
    
    logger.info(f"Weather parameters exported to: {params_dir}")
    return params_dir