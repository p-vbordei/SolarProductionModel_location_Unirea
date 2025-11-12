"""
Real-time weather data fetcher for intraday solar forecasting
Supports high-frequency updates and 15-minute resolution data
"""
import pandas as pd
import numpy as np
import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
import pytz
from config import LOCATIONS, INTRADAY_FORECAST_DAYS, INTRADAY_RESOLUTION_MINUTES

logger = logging.getLogger(__name__)


class IntradayWeatherFetcher:
    """Real-time weather fetcher optimized for intraday operations"""
    
    def __init__(self):
        self.cache = {}
        self.cache_expiry_minutes = 30  # Cache weather data for 30 minutes
        
    def fetch_intraday_weather(self, location_key: str) -> Tuple[pd.DataFrame, str]:
        """
        Fetch high-resolution weather data for intraday forecasting
        
        Returns:
            weather_df: DataFrame with 15-minute resolution weather data
            source: Data source identifier
        """
        if location_key not in LOCATIONS:
            raise ValueError(f"Location {location_key} not found in configuration")
        
        location = LOCATIONS[location_key]
        
        # Check cache first
        cache_key = f"{location_key}_intraday"
        if self._is_cache_valid(cache_key):
            logger.info(f"Using cached weather data for {location_key}")
            return self.cache[cache_key]['data'], self.cache[cache_key]['source']
        
        # Calculate forecast period (7 days from midnight CET)
        # Get location timezone (CET)
        location_tz = pytz.timezone(location.get('timezone', 'Europe/Berlin'))
        
        # Get current time in location timezone
        now_local = datetime.now(location_tz)
        
        # Start from midnight tomorrow (D+1) in local timezone
        tomorrow_local = now_local + timedelta(days=1)
        start_local = tomorrow_local.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Convert to UTC for API calls
        start_time = start_local.astimezone(pytz.UTC)
        end_time = start_time + timedelta(days=INTRADAY_FORECAST_DAYS)
        
        logger.info(f"Fetching intraday weather for {location['name']}")
        logger.info(f"Period: {start_time} to {end_time}")
        logger.info(f"Resolution: {INTRADAY_RESOLUTION_MINUTES} minutes")
        
        # Try high-resolution weather sources
        weather_df, source = self._fetch_high_resolution_weather(
            location, start_time, end_time
        )
        
        if weather_df is not None:
            # Cache the result
            self.cache[cache_key] = {
                'data': weather_df,
                'source': source,
                'timestamp': datetime.now(pytz.UTC)
            }
            
            logger.info(f"Successfully fetched {len(weather_df)} data points from {source}")
            return weather_df, source
        else:
            # Fallback to synthetic weather data
            logger.warning("All weather sources failed, generating synthetic data")
            weather_df = self._generate_synthetic_weather(location, start_time, end_time)
            
            # Cache the synthetic result
            self.cache[cache_key] = {
                'data': weather_df,
                'source': 'synthetic',
                'timestamp': datetime.now(pytz.UTC)
            }
            
            logger.info(f"Generated {len(weather_df)} synthetic weather data points")
            return weather_df, 'synthetic'
    
    def _fetch_high_resolution_weather(self, location: Dict, 
                                     start_time: datetime, 
                                     end_time: datetime) -> Tuple[Optional[pd.DataFrame], str]:
        """Fetch high-resolution weather data"""
        
        # Try Open-Meteo with high resolution first
        try:
            weather_df = self._fetch_openmeteo_high_res(location, start_time, end_time)
            if weather_df is not None:
                return weather_df, 'open_meteo_high_res'
        except Exception as e:
            logger.warning(f"Open-Meteo high-res failed: {e}")
        
        # Fallback to standard resolution with interpolation
        try:
            weather_df = self._fetch_openmeteo_standard(location, start_time, end_time)
            if weather_df is not None:
                # Interpolate to 15-minute resolution
                weather_df = self._interpolate_to_15min(weather_df)
                return weather_df, 'open_meteo_interpolated'
        except Exception as e:
            logger.warning(f"Open-Meteo standard failed: {e}")
        
        return None, 'none'
    
    def _fetch_openmeteo_high_res(self, location: Dict, 
                                start_time: datetime, 
                                end_time: datetime) -> Optional[pd.DataFrame]:
        """Fetch data from Open-Meteo with 15-minute resolution"""
        
        url = "https://api.open-meteo.com/v1/forecast"
        
        params = {
            'latitude': location['latitude'],
            'longitude': location['longitude'],
            'hourly': 'temperature_2m,shortwave_radiation,direct_normal_irradiance,diffuse_radiation,windspeed_10m,cloudcover,relative_humidity_2m',
            'timezone': 'UTC',
            'forecast_days': 7
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        if 'hourly' not in data:
            return None
        
        hourly = data['hourly']
        
        # Create DataFrame
        timestamps = pd.to_datetime(hourly['time'], utc=True)
        
        weather_df = pd.DataFrame({
            'timestamp': timestamps,
            'temperature': hourly.get('temperature_2m', [np.nan] * len(timestamps)),
            'ghi': hourly.get('shortwave_radiation', [np.nan] * len(timestamps)),
            'dni': hourly.get('direct_normal_irradiance', [np.nan] * len(timestamps)),
            'dhi': hourly.get('diffuse_radiation', [np.nan] * len(timestamps)),
            'wind_speed': hourly.get('windspeed_10m', [np.nan] * len(timestamps)),
            'cloud_cover': hourly.get('cloudcover', [np.nan] * len(timestamps)),
            'humidity': hourly.get('relative_humidity_2m', [np.nan] * len(timestamps))
        })
        
        weather_df = weather_df.set_index('timestamp')
        
        # Filter to only include data from start_time onwards
        weather_df = weather_df[weather_df.index >= start_time]
        
        # Interpolate to 15-minute resolution
        weather_df = self._interpolate_to_15min(weather_df)
        
        return weather_df
    
    def _fetch_openmeteo_standard(self, location: Dict, 
                                start_time: datetime, 
                                end_time: datetime) -> Optional[pd.DataFrame]:
        """Fallback: fetch standard hourly data"""
        
        url = "https://api.open-meteo.com/v1/forecast"
        
        params = {
            'latitude': location['latitude'],
            'longitude': location['longitude'],
            'hourly': 'temperature_2m,shortwave_radiation,windspeed_10m,cloudcover',
            'timezone': 'UTC',
            'forecast_days': 7
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        if 'hourly' not in data:
            return None
        
        hourly = data['hourly']
        timestamps = pd.to_datetime(hourly['time'], utc=True)
        
        weather_df = pd.DataFrame({
            'timestamp': timestamps,
            'temperature': hourly.get('temperature_2m', [20] * len(timestamps)),
            'ghi': hourly.get('shortwave_radiation', [0] * len(timestamps)),
            'dni': [np.nan] * len(timestamps),  # Not available
            'dhi': [np.nan] * len(timestamps),  # Not available
            'wind_speed': hourly.get('windspeed_10m', [5] * len(timestamps)),
            'cloud_cover': hourly.get('cloudcover', [50] * len(timestamps)),
            'humidity': [60] * len(timestamps)  # Default
        })
        
        weather_df = weather_df.set_index('timestamp')
        
        # Filter to only include data from start_time onwards
        weather_df = weather_df[weather_df.index >= start_time]
        
        return weather_df
    
    def _interpolate_to_15min(self, hourly_df: pd.DataFrame) -> pd.DataFrame:
        """Interpolate hourly data to 15-minute resolution"""
        
        # Create 15-minute index
        start_time = hourly_df.index[0]
        end_time = hourly_df.index[-1] + timedelta(hours=1)
        
        freq_str = f'{INTRADAY_RESOLUTION_MINUTES}min'
        new_index = pd.date_range(start=start_time, end=end_time, freq=freq_str, tz='UTC')
        
        # Remove the last point to avoid going beyond end_time
        new_index = new_index[:-1]
        
        # Reindex and interpolate
        interpolated_df = hourly_df.reindex(new_index)
        
        # Use different interpolation methods for different variables
        for col in interpolated_df.columns:
            if col in ['temperature', 'wind_speed', 'humidity']:
                # Linear interpolation for smooth variables
                interpolated_df[col] = interpolated_df[col].interpolate(method='linear')
            elif col in ['ghi', 'dni', 'dhi']:
                # Special handling for solar irradiance
                interpolated_df[col] = self._interpolate_solar_irradiance(
                    interpolated_df[col], new_index
                )
            else:
                # Forward fill for discrete variables like cloud cover
                interpolated_df[col] = interpolated_df[col].ffill()
        
        # Fill any remaining NaN values
        interpolated_df = interpolated_df.ffill().bfill()
        
        return interpolated_df
    
    def _interpolate_solar_irradiance(self, irradiance_series: pd.Series, 
                                    timestamps: pd.DatetimeIndex) -> pd.Series:
        """Special interpolation for solar irradiance considering sun position"""
        
        # Fill NaN values first
        filled_series = irradiance_series.ffill().fillna(0)
        
        # For nighttime hours, set irradiance to 0
        for i, ts in enumerate(timestamps):
            hour = ts.hour
            if hour < 6 or hour > 20:  # Rough nighttime hours
                filled_series.iloc[i] = 0
        
        # Linear interpolation for daytime
        filled_series = filled_series.interpolate(method='linear')
        
        return filled_series
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid"""
        if cache_key not in self.cache:
            return False
        
        cache_age = datetime.now(pytz.UTC) - self.cache[cache_key]['timestamp']
        return cache_age.total_seconds() < (self.cache_expiry_minutes * 60)
    
    def get_current_weather(self, location_key: str) -> Dict:
        """Get current weather conditions for immediate use"""
        if location_key not in LOCATIONS:
            raise ValueError(f"Location {location_key} not found")
        
        location = LOCATIONS[location_key]
        
        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                'latitude': location['latitude'],
                'longitude': location['longitude'],
                'current': ['temperature_2m', 'cloudcover', 'windspeed_10m'],
                'timezone': 'UTC'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            current = data.get('current', {})
            
            return {
                'temperature': current.get('temperature_2m', 20),
                'cloud_cover': current.get('cloudcover', 50),
                'wind_speed': current.get('windspeed_10m', 5),
                'timestamp': datetime.now(pytz.UTC)
            }
            
        except Exception as e:
            logger.error(f"Failed to get current weather: {e}")
            # Return default values
            return {
                'temperature': 20,
                'cloud_cover': 50,
                'wind_speed': 5,
                'timestamp': datetime.now(pytz.UTC)
            }
    
    def _generate_synthetic_weather(self, location: Dict, 
                                  start_time: datetime, 
                                  end_time: datetime) -> pd.DataFrame:
        """Generate synthetic weather data as fallback"""
        
        # Create 15-minute timestamp index
        freq_str = f'{INTRADAY_RESOLUTION_MINUTES}min'
        timestamps = pd.date_range(start=start_time, end=end_time, freq=freq_str, tz='UTC')
        
        weather_df = pd.DataFrame(index=timestamps)
        
        # Generate realistic synthetic weather patterns
        lat = location['latitude']
        
        for i, ts in enumerate(timestamps):
            hour = ts.hour
            day_of_year = ts.dayofyear
            
            # Temperature pattern (seasonal + diurnal)
            seasonal_temp = 15 + 10 * np.sin((day_of_year - 80) * 2 * np.pi / 365)
            diurnal_temp = 8 * np.sin((hour - 6) * np.pi / 12)
            noise_temp = np.random.normal(0, 2)
            temperature = seasonal_temp + diurnal_temp + noise_temp
            
            # Solar irradiance (proper solar position calculation)
            # Calculate actual solar elevation for this timestamp
            lat_rad = np.radians(lat)
            
            # Solar declination
            declination = 23.45 * np.sin(np.radians((360 * (284 + day_of_year)) / 365))
            decl_rad = np.radians(declination)
            
            # Hour angle (approximate, using UTC time)
            hour_angle = 15 * (hour + location['longitude'] / 15 - 12)
            hour_angle_rad = np.radians(hour_angle)
            
            # Solar elevation
            solar_elevation = np.degrees(np.arcsin(
                np.sin(lat_rad) * np.sin(decl_rad) +
                np.cos(lat_rad) * np.cos(decl_rad) * np.cos(hour_angle_rad)
            ))
            
            if solar_elevation > 0:
                # Clear sky GHI model
                air_mass = 1 / (np.sin(np.radians(solar_elevation)) + 
                               0.50572 * (solar_elevation + 6.07995) ** -1.6364)
                clear_sky_ghi = 1361 * np.sin(np.radians(solar_elevation)) * 0.7 ** air_mass
                
                # Add cloud variability
                cloud_factor = 0.7 + 0.3 * np.random.random()
                ghi = clear_sky_ghi * cloud_factor
            else:
                ghi = 0
            
            # Wind speed
            wind_speed = 3 + 4 * np.random.random()
            
            # Cloud cover
            cloud_cover = 30 + 40 * np.random.random()
            
            # Humidity
            humidity = 50 + 30 * np.random.random()
            
            weather_df.loc[ts, 'temperature'] = temperature
            weather_df.loc[ts, 'ghi'] = max(0, ghi)
            weather_df.loc[ts, 'dni'] = max(0, ghi * 0.7) if ghi > 0 else 0
            weather_df.loc[ts, 'dhi'] = max(0, ghi * 0.3) if ghi > 0 else 0
            weather_df.loc[ts, 'wind_speed'] = wind_speed
            weather_df.loc[ts, 'cloud_cover'] = cloud_cover
            weather_df.loc[ts, 'humidity'] = humidity
        
        return weather_df