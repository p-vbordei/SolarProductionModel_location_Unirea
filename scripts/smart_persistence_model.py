"""
Smart Persistence Model (SPM) for Solar Power Forecasting
Based on the concept that clear-sky index remains constant over short forecast horizons
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import logging
import pytz

# Try importing ephem for accurate solar calculations
try:
    import ephem
    EPHEM_AVAILABLE = True
except ImportError:
    EPHEM_AVAILABLE = False
    logging.warning("ephem library not found. Install with: pip install ephem")

# Try importing pvlib for clear sky models
try:
    import pvlib
    from pvlib.location import Location
    from pvlib.clearsky import ineichen
    PVLIB_AVAILABLE = True
except ImportError:
    PVLIB_AVAILABLE = False
    logging.warning("pvlib library not found. Install with: pip install pvlib")

from config import LOCATIONS

logger = logging.getLogger(__name__)


class SmartPersistenceModel:
    """
    Smart Persistence Model for solar power forecasting
    
    The model assumes that the clear-sky index (CSI) remains constant
    over the forecast horizon, which is more accurate than standard
    persistence for solar applications.
    
    CSI = Actual Power / Clear-Sky Power
    Forecast = CSI * Future Clear-Sky Power
    """
    
    def __init__(self, location_key: str, location_config: Dict):
        self.location_key = location_key
        self.location = location_config
        self.capacity_mw = location_config['estimated_capacity_mw']
        self.latitude = location_config['latitude']
        self.longitude = location_config['longitude']
        self.timezone = pytz.timezone(location_config['timezone'])
        
        # Model parameters
        self.min_solar_elevation = 0.1  # degrees, below this we assume zero production
        self.clear_sky_model = 'ineichen'  # Can be 'ineichen', 'simplified_solis', or 'haurwitz'
        
        # Performance ratio for converting irradiance to power
        self.performance_ratio = 0.78  # Typical value including all system losses
        
        # Initialize pvlib location if available
        if PVLIB_AVAILABLE:
            self.pvlib_location = Location(
                latitude=self.latitude,
                longitude=self.longitude,
                tz=self.timezone,
                altitude=0  # Sea level, can be updated if elevation data available
            )
        
        # Cache for clear sky calculations
        self._clear_sky_cache = {}
        
    def forecast(self, 
                current_power_mw: float,
                current_timestamp: datetime,
                forecast_horizons_minutes: List[int],
                current_weather: Optional[Dict] = None) -> pd.DataFrame:
        """
        Generate smart persistence forecast
        
        Args:
            current_power_mw: Current measured power output in MW
            current_timestamp: Current time (aware datetime)
            forecast_horizons_minutes: List of forecast horizons in minutes (e.g., [15, 30, 45, 60])
            current_weather: Optional current weather conditions
            
        Returns:
            DataFrame with forecasts for each horizon
        """
        logger.info(f"Generating SPM forecast for {self.location_key}")
        logger.info(f"Current power: {current_power_mw:.2f} MW at {current_timestamp}")
        
        # Ensure timestamp is timezone aware
        if current_timestamp.tzinfo is None:
            current_timestamp = self.timezone.localize(current_timestamp)
        
        # Calculate current clear-sky power
        current_clear_sky = self._calculate_clear_sky_power(current_timestamp)
        
        # Calculate clear-sky index
        if current_clear_sky > 0.001:  # Avoid division by zero
            clear_sky_index = current_power_mw / current_clear_sky
            # Limit CSI to reasonable bounds (0.0 to 1.2, allowing for slight over-irradiance)
            clear_sky_index = np.clip(clear_sky_index, 0.0, 1.2)
        else:
            # Night time or very low sun angle
            clear_sky_index = 0.0
        
        logger.info(f"Clear-sky index: {clear_sky_index:.3f}")
        
        # Generate forecasts for each horizon
        results = []
        
        for horizon_minutes in forecast_horizons_minutes:
            forecast_time = current_timestamp + timedelta(minutes=horizon_minutes)
            
            # Calculate clear-sky power at forecast time
            forecast_clear_sky = self._calculate_clear_sky_power(forecast_time)
            
            # Apply smart persistence
            forecast_power = clear_sky_index * forecast_clear_sky
            
            # Apply capacity constraints
            forecast_power = np.clip(forecast_power, 0, self.capacity_mw)
            
            # Generate uncertainty bands based on forecast horizon
            uncertainty = self._calculate_uncertainty(horizon_minutes, clear_sky_index)
            
            result = {
                'timestamp': forecast_time,
                'horizon_minutes': horizon_minutes,
                'production_mw': forecast_power,
                'clear_sky_mw': forecast_clear_sky,
                'clear_sky_index': clear_sky_index,
                'q10': forecast_power * (1 - 2 * uncertainty),
                'q25': forecast_power * (1 - uncertainty),
                'q50': forecast_power,
                'q75': forecast_power * (1 + uncertainty),
                'q90': forecast_power * (1 + 2 * uncertainty),
            }
            
            # Ensure quantiles respect capacity limits
            for q in ['q10', 'q25', 'q50', 'q75', 'q90']:
                result[q] = np.clip(result[q], 0, self.capacity_mw)
            
            results.append(result)
        
        forecast_df = pd.DataFrame(results)
        forecast_df.set_index('timestamp', inplace=True)
        
        # Add metadata
        forecast_df['location'] = self.location_key
        forecast_df['model'] = 'smart_persistence'
        forecast_df['forecast_timestamp'] = current_timestamp
        
        return forecast_df
    
    def forecast_intraday(self,
                         current_power_mw: float,
                         current_timestamp: datetime,
                         hours_ahead: int = 4,
                         resolution_minutes: int = 15) -> pd.DataFrame:
        """
        Generate high-resolution intraday forecast
        
        Args:
            current_power_mw: Current measured power
            current_timestamp: Current time
            hours_ahead: Hours to forecast ahead
            resolution_minutes: Time resolution in minutes
            
        Returns:
            DataFrame with intraday forecasts
        """
        # Generate list of forecast horizons
        num_periods = int(hours_ahead * 60 / resolution_minutes)
        horizons = [i * resolution_minutes for i in range(1, num_periods + 1)]
        
        # Use main forecast method
        forecast = self.forecast(
            current_power_mw=current_power_mw,
            current_timestamp=current_timestamp,
            forecast_horizons_minutes=horizons
        )
        
        # Add energy calculations (MWh for each period)
        resolution_hours = resolution_minutes / 60.0
        forecast['energy_mwh'] = forecast['production_mw'] * resolution_hours
        forecast['energy_q10_mwh'] = forecast['q10'] * resolution_hours
        forecast['energy_q25_mwh'] = forecast['q25'] * resolution_hours
        forecast['energy_q50_mwh'] = forecast['q50'] * resolution_hours
        forecast['energy_q75_mwh'] = forecast['q75'] * resolution_hours
        forecast['energy_q90_mwh'] = forecast['q90'] * resolution_hours
        
        return forecast
    
    def _calculate_clear_sky_power(self, timestamp: datetime) -> float:
        """
        Calculate theoretical clear-sky power output
        
        Args:
            timestamp: Time for calculation
            
        Returns:
            Clear-sky power in MW
        """
        # Check cache first
        cache_key = timestamp.strftime('%Y%m%d%H%M')
        if cache_key in self._clear_sky_cache:
            return self._clear_sky_cache[cache_key]
        
        if PVLIB_AVAILABLE:
            # Use pvlib for accurate clear-sky calculations
            clear_sky_power = self._calculate_clear_sky_pvlib(timestamp)
        else:
            # Use simplified clear-sky model
            clear_sky_power = self._calculate_clear_sky_simple(timestamp)
        
        # Cache the result
        self._clear_sky_cache[cache_key] = clear_sky_power
        
        # Limit cache size
        if len(self._clear_sky_cache) > 1000:
            # Remove oldest entries
            oldest_keys = sorted(self._clear_sky_cache.keys())[:500]
            for key in oldest_keys:
                del self._clear_sky_cache[key]
        
        return clear_sky_power
    
    def _calculate_clear_sky_pvlib(self, timestamp: datetime) -> float:
        """Calculate clear-sky power using pvlib"""
        try:
            # Create time index
            times = pd.DatetimeIndex([timestamp])
            
            # Get solar position
            solar_position = self.pvlib_location.get_solarposition(times)
            
            # Check if sun is above horizon
            if solar_position['elevation'].iloc[0] < self.min_solar_elevation:
                return 0.0
            
            # Get clear-sky GHI using Ineichen model
            clear_sky = self.pvlib_location.get_clearsky(times, model=self.clear_sky_model)
            ghi = clear_sky['ghi'].iloc[0]
            
            # Convert GHI to power
            # Simple model: Power = Capacity * (GHI / 1000) * Performance Ratio
            clear_sky_power = self.capacity_mw * (ghi / 1000) * self.performance_ratio
            
            return float(clear_sky_power)
            
        except Exception as e:
            logger.warning(f"Error in pvlib clear-sky calculation: {e}")
            # Fallback to simple model
            return self._calculate_clear_sky_simple(timestamp)
    
    def _calculate_clear_sky_simple(self, timestamp: datetime) -> float:
        """Simple clear-sky model without pvlib"""
        # Get solar elevation
        elevation = self._calculate_solar_elevation(timestamp)
        
        # Check if sun is above horizon
        if elevation < self.min_solar_elevation:
            return 0.0
        
        # Simple clear-sky GHI model
        # GHI = 1361 * sin(elevation) * atmospheric_transmission
        atmospheric_transmission = 0.65  # More realistic value, aligned with ML model
        ghi = 1361 * np.sin(np.radians(elevation)) * atmospheric_transmission
        
        # Convert to power
        clear_sky_power = self.capacity_mw * (ghi / 1000) * self.performance_ratio
        
        return float(clear_sky_power)
    
    def _calculate_solar_elevation(self, timestamp: datetime) -> float:
        """Calculate solar elevation angle"""
        if EPHEM_AVAILABLE:
            # Use ephem for accurate calculation
            observer = ephem.Observer()
            observer.lat = str(self.latitude)
            observer.lon = str(self.longitude)
            observer.elevation = 0
            
            # Convert timestamp to UTC for ephem
            utc_dt = timestamp.astimezone(pytz.utc).replace(tzinfo=None)
            observer.date = ephem.Date(utc_dt)
            
            sun = ephem.Sun()
            sun.compute(observer)
            
            elevation = np.degrees(sun.alt)
            return float(elevation)
        else:
            # Simplified calculation
            local_ts = timestamp.astimezone(self.timezone)
            
            day_of_year = local_ts.timetuple().tm_yday
            hour_decimal = local_ts.hour + local_ts.minute / 60.0
            
            # Solar declination
            declination = 23.45 * np.sin(np.radians((360 * (284 + day_of_year)) / 365))
            
            # Hour angle
            solar_time = hour_decimal  # Simplified, ignoring equation of time
            hour_angle = 15 * (solar_time - 12)
            
            # Solar elevation
            lat_rad = np.radians(self.latitude)
            decl_rad = np.radians(declination)
            hour_rad = np.radians(hour_angle)
            
            elevation = np.degrees(np.arcsin(
                np.sin(lat_rad) * np.sin(decl_rad) +
                np.cos(lat_rad) * np.cos(decl_rad) * np.cos(hour_rad)
            ))
            
            return float(elevation)
    
    def _calculate_uncertainty(self, horizon_minutes: int, clear_sky_index: float) -> float:
        """
        Calculate forecast uncertainty based on horizon and sky conditions
        
        Args:
            horizon_minutes: Forecast horizon in minutes
            clear_sky_index: Current clear-sky index (0-1)
            
        Returns:
            Uncertainty factor (0-1)
        """
        # Base uncertainty increases with forecast horizon
        # Approximately 1% per 10 minutes
        base_uncertainty = 0.05 + (horizon_minutes / 10) * 0.01
        
        # Adjust based on sky conditions
        # Clear sky (CSI > 0.8): lower uncertainty
        # Partly cloudy (0.3 < CSI < 0.8): higher uncertainty
        # Overcast (CSI < 0.3): moderate uncertainty
        
        if clear_sky_index > 0.8:
            # Clear sky - low uncertainty
            condition_factor = 0.5
        elif clear_sky_index > 0.3:
            # Partly cloudy - high uncertainty
            condition_factor = 1.5
        else:
            # Overcast - moderate uncertainty
            condition_factor = 1.0
        
        # Total uncertainty
        uncertainty = base_uncertainty * condition_factor
        
        # Cap at reasonable maximum (30%)
        return min(uncertainty, 0.3)
    
    def validate_forecast(self, 
                         forecasts: pd.DataFrame, 
                         actuals: pd.DataFrame) -> Dict[str, float]:
        """
        Validate SPM forecasts against actual values
        
        Args:
            forecasts: DataFrame with forecast values
            actuals: DataFrame with actual values
            
        Returns:
            Dictionary with validation metrics
        """
        # Align forecasts and actuals
        common_idx = forecasts.index.intersection(actuals.index)
        
        if len(common_idx) == 0:
            logger.warning("No common timestamps for validation")
            return {}
        
        forecast_values = forecasts.loc[common_idx, 'production_mw'].values
        actual_values = actuals.loc[common_idx, 'production_mw'].values
        
        # Calculate metrics
        mae = np.mean(np.abs(forecast_values - actual_values))
        rmse = np.sqrt(np.mean((forecast_values - actual_values) ** 2))
        mbe = np.mean(forecast_values - actual_values)
        
        # Normalized metrics
        capacity_normalized_mae = mae / self.capacity_mw
        capacity_normalized_rmse = rmse / self.capacity_mw
        
        # Correlation
        if len(forecast_values) > 1:
            correlation = np.corrcoef(forecast_values, actual_values)[0, 1]
        else:
            correlation = np.nan
        
        # Forecast skill score (compared to persistence)
        # For SPM, we compare against standard persistence
        persistence_errors = np.abs(actual_values[:-1] - actual_values[1:])
        if len(persistence_errors) > 0:
            persistence_mae = np.mean(persistence_errors)
            skill_score = 1 - (mae / persistence_mae)
        else:
            skill_score = np.nan
        
        metrics = {
            'mae_mw': mae,
            'rmse_mw': rmse,
            'mbe_mw': mbe,
            'normalized_mae': capacity_normalized_mae,
            'normalized_rmse': capacity_normalized_rmse,
            'correlation': correlation,
            'skill_score': skill_score,
            'n_samples': len(common_idx)
        }
        
        return metrics


def create_spm_forecast(location_key: str,
                       current_power_mw: float,
                       current_timestamp: datetime,
                       hours_ahead: int = 4,
                       resolution_minutes: int = 15) -> pd.DataFrame:
    """
    Convenience function to create SPM forecast
    
    Args:
        location_key: Key from LOCATIONS config
        current_power_mw: Current measured power
        current_timestamp: Current time
        hours_ahead: Forecast horizon in hours
        resolution_minutes: Time resolution
        
    Returns:
        DataFrame with SPM forecasts
    """
    if location_key not in LOCATIONS:
        raise ValueError(f"Unknown location: {location_key}")
    
    location_config = LOCATIONS[location_key]
    
    # Initialize model
    model = SmartPersistenceModel(location_key, location_config)
    
    # Generate forecast
    forecast = model.forecast_intraday(
        current_power_mw=current_power_mw,
        current_timestamp=current_timestamp,
        hours_ahead=hours_ahead,
        resolution_minutes=resolution_minutes
    )
    
    return forecast


if __name__ == "__main__":
    # Example usage
    import pytz
    
    # Test location
    location_key = 'chisineu_cris'
    
    # Current conditions
    current_time = datetime.now(pytz.timezone('Europe/Berlin'))
    current_power = 5.0  # MW
    
    # Generate forecast
    forecast = create_spm_forecast(
        location_key=location_key,
        current_power_mw=current_power,
        current_timestamp=current_time,
        hours_ahead=4,
        resolution_minutes=15
    )
    
    print(f"\nSmart Persistence Model Forecast for {LOCATIONS[location_key]['name']}")
    print(f"Current time: {current_time}")
    print(f"Current power: {current_power:.2f} MW")
    print("\nForecast:")
    print(forecast[['production_mw', 'clear_sky_mw', 'clear_sky_index', 'q10', 'q90']].head(16))