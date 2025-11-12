"""
High-resolution solar forecasting model optimized for intraday operations
Supports 15-minute resolution predictions with fast execution

OUTPUT TIMEZONE: All timestamps in output files MUST be in CET/CEST
Internal calculations use UTC, but all user-facing outputs are converted to Europe/Berlin timezone
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
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
    PVLIB_AVAILABLE = True
except ImportError:
    PVLIB_AVAILABLE = False
    logging.warning("pvlib library not found. Install with: pip install pvlib")

from config import (
    INTRADAY_RESOLUTION_MINUTES, DEGRADATION_RATE_ANNUAL,
    PERFORMANCE_RATIO_DEFAULT, PERFORMANCE_RATIO_BY_WEATHER, TEMPERATURE_COEFFICIENT
)

# Try importing calibration module
try:
    from calibration_module import calibrate_forecast
    CALIBRATION_AVAILABLE = True
except ImportError:
    CALIBRATION_AVAILABLE = False
    logging.warning("Calibration module not found. Forecasts will not be bias-corrected.")

logger = logging.getLogger(__name__)


class IntradaySolarForecastModel:
    """Fast, high-resolution solar forecasting model for intraday operations"""
    
    def __init__(self, location_key: str, location_config: Dict):
        self.location_key = location_key
        self.location = location_config
        # Separate DC and AC capacities for accurate modeling
        self.dc_capacity_mw = location_config.get('dc_capacity_mw', location_config['estimated_capacity_mw'])
        self.ac_capacity_mw = location_config.get('ac_capacity_mw', location_config['estimated_capacity_mw'])
        self.capacity_mw = self.ac_capacity_mw  # For backwards compatibility
        self.timezone = pytz.timezone(location_config['timezone'])
        
        # Performance parameters optimized for intraday accuracy
        self.performance_ratio = PERFORMANCE_RATIO_DEFAULT
        self.temp_coefficient = TEMPERATURE_COEFFICIENT
        self.soiling_factor = 0.98  # 2% soiling losses
        
        # PV system configuration
        # Get panel configuration from location config if available
        panel_config = location_config.get('panels', {})
        self.tilt_angle = panel_config.get('tilt', 25)  # degrees - actual installation angle
        self.azimuth_angle = panel_config.get('orientation', 180)  # degrees - south facing
        
        # Intraday-specific parameters
        self.cloud_response_factor = 0.8  # How quickly output responds to cloud changes
        self.smoothing_window = 4  # 4 * 15min = 1 hour smoothing for stability
        
        # Initialize pvlib location if available
        if PVLIB_AVAILABLE:
            self.pvlib_location = Location(
                latitude=location_config['latitude'],
                longitude=location_config['longitude'],
                tz=self.timezone,
                altitude=0  # Sea level, can be updated if elevation data available
            )
        
    def predict_intraday(self, weather_df: pd.DataFrame,
                        current_conditions: Optional[Dict] = None,
                        save_processed_weather: bool = False,
                        output_dir: Optional[str] = None) -> pd.DataFrame:
        """
        Generate high-resolution intraday predictions

        Args:
            weather_df: 15-minute resolution weather data
            current_conditions: Current weather for calibration
            save_processed_weather: If True, save processed weather data with local solar calculations
            output_dir: Directory to save processed weather (required if save_processed_weather=True)

        Returns:
            DataFrame with 15-minute solar production forecasts
        """
        logger.info(f"Generating intraday forecast for {self.location_key}")
        logger.info(f"Period: {weather_df.index[0]} to {weather_df.index[-1]}")
        logger.info(f"Resolution: {INTRADAY_RESOLUTION_MINUTES} minutes")
        
        predictions = pd.DataFrame(index=weather_df.index)
        
        # Calculate solar position for all timestamps
        solar_data = self._calculate_solar_positions(weather_df.index)
        
        # Base PV model calculations
        dc_power = self._calculate_dc_power(weather_df, solar_data)

        # Save processed weather data with local solar calculations if requested
        if save_processed_weather and output_dir:
            self._save_processed_weather(weather_df, solar_data, output_dir)

        # Apply system losses and inefficiencies
        ac_power = self._apply_system_losses(dc_power, weather_df)
        
        # Apply cloud dynamics and smoothing
        ac_power = self._apply_cloud_dynamics(ac_power, weather_df)
        
        # Apply real-time calibration if current conditions available
        if current_conditions:
            ac_power = self._apply_realtime_calibration(ac_power, current_conditions)
        
        # Generate uncertainty bands for intraday risk management
        predictions = self._generate_uncertainty_bands(ac_power, weather_df)
        
        # Calculate energy values (integrate power over time period)
        resolution_hours = INTRADAY_RESOLUTION_MINUTES / 60.0
        predictions['energy_mwh'] = predictions['production_mw'] * resolution_hours
        predictions['energy_q10_mwh'] = predictions['q10'] * resolution_hours
        predictions['energy_q25_mwh'] = predictions['q25'] * resolution_hours
        predictions['energy_q50_mwh'] = predictions['q50'] * resolution_hours
        predictions['energy_q75_mwh'] = predictions['q75'] * resolution_hours
        predictions['energy_q90_mwh'] = predictions['q90'] * resolution_hours
        
        # Apply calibration if available
        if CALIBRATION_AVAILABLE:
            logger.info("Applying bias calibration based on historical performance")
            predictions = calibrate_forecast(
                predictions, 
                weather_df,
                location_key=self.location_key,
                model_type='ensemble'
            )
        
        # Add metadata
        predictions['location'] = self.location_key
        predictions['forecast_timestamp'] = datetime.now(pytz.UTC)
        predictions['resolution_minutes'] = INTRADAY_RESOLUTION_MINUTES
        
        logger.info(f"Generated {len(predictions)} 15-minute predictions")
        
        return predictions
    
    def _calculate_solar_positions(self, timestamps: pd.DatetimeIndex) -> pd.DataFrame:
        """Calculate solar position data for all timestamps using accurate astronomical calculations"""
        solar_data = pd.DataFrame(index=timestamps)
        
        lat = self.location['latitude']
        lon = self.location['longitude']
        
        elevations = []
        azimuths = []
        air_masses = []
        
        if EPHEM_AVAILABLE:
            # Use ephem for accurate solar calculations
            observer = ephem.Observer()
            observer.lat = str(lat)
            observer.lon = str(lon)
            observer.elevation = 0
            sun = ephem.Sun()
            
            for ts in timestamps:
                # Ensure datetime is naive UTC for ephem
                if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
                    naive_utc_dt = ts.astimezone(pytz.utc).replace(tzinfo=None)
                else:
                    naive_utc_dt = ts
                
                observer.date = ephem.Date(naive_utc_dt)
                sun.compute(observer)
                
                elevation = np.degrees(sun.alt)
                azimuth = np.degrees(sun.az)
                
                elevations.append(max(0, elevation))
                azimuths.append(azimuth)
                
                # Calculate air mass
                if elevation > 0:
                    air_mass = 1 / (np.sin(np.radians(elevation)) + 
                                   0.50572 * (elevation + 6.07995) ** -1.6364)
                else:
                    air_mass = np.inf
                air_masses.append(air_mass)
        else:
            # Fallback to previous calculation if ephem not available
            logger.warning("Using simplified solar calculations. Install ephem for accurate results: pip install ephem")
            lat_rad = np.radians(lat)
            
            for ts in timestamps:
                # Convert to local time for solar calculations
                local_ts = ts.tz_convert(self.timezone)
                
                day_of_year = local_ts.dayofyear
                hour_decimal = local_ts.hour + local_ts.minute / 60.0
                
                # Solar declination
                declination = 23.45 * np.sin(np.radians((360 * (284 + day_of_year)) / 365))
                decl_rad = np.radians(declination)
                
                # Equation of time
                B = 2 * np.pi * (day_of_year - 81) / 365
                equation_of_time = 9.87 * np.sin(2 * B) - 7.53 * np.cos(B) - 1.5 * np.sin(B)
                
                # Solar time
                standard_meridian = 15 * round(local_ts.utcoffset().total_seconds() / 3600)
                longitude_correction = 4 * (standard_meridian - lon)
                solar_time = hour_decimal + (equation_of_time + longitude_correction) / 60
                
                # Hour angle
                hour_angle = 15 * (solar_time - 12)
                hour_angle_rad = np.radians(hour_angle)
                
                # Solar elevation
                elevation = np.degrees(np.arcsin(
                    np.sin(lat_rad) * np.sin(decl_rad) +
                    np.cos(lat_rad) * np.cos(decl_rad) * np.cos(hour_angle_rad)
                ))
                
                # Solar azimuth
                azimuth = np.degrees(np.arctan2(
                    np.sin(hour_angle_rad),
                    np.cos(hour_angle_rad) * np.sin(lat_rad) - 
                    np.tan(decl_rad) * np.cos(lat_rad)
                ))
                
                elevations.append(max(0, elevation))
                azimuths.append(azimuth)
                
                # Calculate air mass
                if elevation > 0:
                    air_mass = 1 / (np.sin(np.radians(elevation)) + 
                                   0.50572 * (elevation + 6.07995) ** -1.6364)
                else:
                    air_mass = np.inf
                air_masses.append(air_mass)
        
        solar_data['elevation'] = elevations
        solar_data['azimuth'] = azimuths
        solar_data['air_mass'] = air_masses
        
        return solar_data
    
    def _calculate_clear_sky_ghi(self, timestamps: pd.DatetimeIndex, 
                                solar_data: pd.DataFrame) -> pd.Series:
        """Calculate clear-sky GHI using pvlib or simple model"""
        
        if PVLIB_AVAILABLE:
            try:
                # Use pvlib for accurate clear-sky calculations
                clear_sky = self.pvlib_location.get_clearsky(timestamps, model='ineichen')
                return clear_sky['ghi']
            except Exception as e:
                logger.warning(f"pvlib clear-sky calculation failed: {e}, using simple model")
        
        # Fallback to simple model
        # Use higher atmospheric transmission for clear sky conditions
        atmospheric_transmission = 0.75
        clear_sky_ghi = 1361 * np.sin(np.radians(solar_data['elevation'])) * atmospheric_transmission
        return pd.Series(clear_sky_ghi, index=timestamps)
    
    def _ghi_to_poa(self, ghi: pd.Series, solar_data: pd.DataFrame, 
                    weather_df: pd.DataFrame) -> pd.Series:
        """Convert Global Horizontal Irradiance (GHI) to Plane of Array (POA) irradiance
        
        This accounts for the tilt and orientation of the solar panels.
        """
        # Convert angles to radians
        tilt_rad = np.radians(self.tilt_angle)
        azimuth_rad = np.radians(self.azimuth_angle)
        
        # Solar angles in radians
        solar_elevation_rad = np.radians(solar_data['elevation'])
        solar_azimuth_rad = np.radians(solar_data['azimuth'])
        
        # Calculate angle of incidence (AOI) between sun and panel normal
        # Using the cosine of angle formula for tilted surfaces
        cos_aoi = (np.sin(solar_elevation_rad) * np.cos(tilt_rad) +
                   np.cos(solar_elevation_rad) * np.sin(tilt_rad) * 
                   np.cos(solar_azimuth_rad - azimuth_rad))
        
        # Ensure cos_aoi is between -1 and 1 (numerical stability)
        cos_aoi = np.clip(cos_aoi, -1, 1)
        
        # Direct beam component estimation
        # Estimate DNI from GHI (simplified approach)
        if 'dni' in weather_df.columns and not weather_df['dni'].isna().all():
            dni = weather_df['dni'].fillna(0)
        else:
            # Estimate DNI from GHI using empirical relationship
            # DNI ≈ GHI / sin(elevation) * clearness_factor
            # Improved clearness factor for better clear-sky performance
            cloud_cover = weather_df.get('cloud_cover', 0)
            # More aggressive clearness for low cloud cover - calibrated values
            clearness_factor = np.where(
                cloud_cover < 10, 
                0.90,  # Very clear sky - increased from 0.85
                np.where(
                    cloud_cover < 30,
                    0.80,  # Mostly clear - increased from 0.75
                    1 - (cloud_cover / 100) * 0.7  # Original formula for cloudy
                )
            )
            with np.errstate(divide='ignore', invalid='ignore'):
                dni = ghi / np.maximum(np.sin(solar_elevation_rad), 0.1) * clearness_factor
                dni = np.clip(dni, 0, 950)  # Max DNI around 950 W/m² for very clear conditions
        
        # Diffuse component (simplified isotropic model)
        if 'dhi' in weather_df.columns and not weather_df['dhi'].isna().all():
            dhi = weather_df['dhi'].fillna(0)
        else:
            # Estimate DHI as remainder
            dhi = ghi - dni * np.sin(solar_elevation_rad)
            dhi = np.clip(dhi, 0, ghi)
        
        # Calculate POA irradiance
        # Direct beam on tilted surface
        poa_direct = dni * np.maximum(cos_aoi, 0)
        
        # Diffuse on tilted surface (isotropic sky model)
        poa_diffuse = dhi * (1 + np.cos(tilt_rad)) / 2
        
        # Ground reflected component (albedo)
        albedo = 0.25  # Increased for typical solar farm surroundings (was 0.2)
        poa_reflected = ghi * albedo * (1 - np.cos(tilt_rad)) / 2
        
        # Total POA irradiance
        poa_total = poa_direct + poa_diffuse + poa_reflected
        
        # Ensure non-negative and reasonable values
        poa_total = np.clip(poa_total, 0, 1200)  # Max POA around 1200 W/m²
        
        return pd.Series(poa_total, index=ghi.index)
    
    def _calculate_dc_power(self, weather_df: pd.DataFrame, 
                          solar_data: pd.DataFrame) -> pd.Series:
        """Calculate DC power output"""
        
        # Get irradiance (prioritize GHI, fallback to calculated)
        if 'ghi' in weather_df.columns and not weather_df['ghi'].isna().all():
            ghi = weather_df['ghi'].fillna(0)
        else:
            # Calculate clear-sky GHI
            clear_sky_ghi = self._calculate_clear_sky_ghi(weather_df.index, solar_data)
            
            # Apply cloud factor
            cloud_factor = 1 - (weather_df.get('cloud_cover', 0) / 100) * 0.8
            ghi = clear_sky_ghi * cloud_factor
            ghi = ghi.clip(lower=0)
        
        # Convert GHI to POA (Plane of Array) irradiance
        poa_irradiance = self._ghi_to_poa(ghi, solar_data, weather_df)
        
        # Temperature effect
        if 'temperature' in weather_df.columns:
            temp_effect = 1 + self.temp_coefficient * (weather_df['temperature'] - 25)
            temp_effect = temp_effect.clip(0.7, 1.1)
        else:
            temp_effect = 1.0
        
        # Determine weather-dependent performance ratio
        if 'cloud_cover' in weather_df.columns:
            # Use weather-dependent performance ratios
            performance_ratio = pd.Series(index=weather_df.index, dtype=float)
            
            # Classify weather conditions based on cloud cover
            clear_mask = weather_df['cloud_cover'] < 20
            partly_cloudy_mask = (weather_df['cloud_cover'] >= 20) & (weather_df['cloud_cover'] < 50)
            cloudy_mask = (weather_df['cloud_cover'] >= 50) & (weather_df['cloud_cover'] < 80)
            overcast_mask = weather_df['cloud_cover'] >= 80
            
            # Apply appropriate performance ratios
            performance_ratio[clear_mask] = PERFORMANCE_RATIO_BY_WEATHER['clear_sky']
            performance_ratio[partly_cloudy_mask] = PERFORMANCE_RATIO_BY_WEATHER['partly_cloudy']
            performance_ratio[cloudy_mask] = PERFORMANCE_RATIO_BY_WEATHER['cloudy']
            performance_ratio[overcast_mask] = PERFORMANCE_RATIO_BY_WEATHER['overcast']
            performance_ratio.fillna(PERFORMANCE_RATIO_BY_WEATHER['default'], inplace=True)
        else:
            # Use default performance ratio if no cloud data
            performance_ratio = PERFORMANCE_RATIO_BY_WEATHER['default']
        
        # Basic DC power calculation with weather-dependent performance ratio
        # Using POA irradiance instead of GHI for tilted panels
        # IMPORTANT: Use DC capacity for DC power calculations
        dc_power = self.dc_capacity_mw * (poa_irradiance / 1000) * temp_effect * performance_ratio

        # Soiling factor is already included in the performance ratio
        # dc_power = dc_power * self.soiling_factor

        # Set nighttime production to zero
        dc_power[solar_data['elevation'] <= 0] = 0

        # Clip to DC capacity (not AC capacity)
        return dc_power.clip(lower=0, upper=self.dc_capacity_mw)
    
    def _apply_system_losses(self, dc_power: pd.Series,
                           weather_df: pd.DataFrame) -> pd.Series:
        """Apply system losses and convert to AC power with inverter clipping"""

        # Inverter efficiency is already included in the performance ratio
        # Set to 1.0 to avoid double counting losses
        inverter_efficiency_base = 1.0

        # Dynamic inverter efficiency adjustment for very low/high loads
        # Use DC capacity for load ratio calculation
        load_ratio = dc_power / (self.dc_capacity_mw + 0.001)
        inverter_efficiency = np.where(
            load_ratio < 0.1,
            inverter_efficiency_base * 0.95,  # 5% additional loss at very low loads
            np.where(
                load_ratio > 0.95,
                inverter_efficiency_base * 0.99,  # 1% loss at very high loads
                inverter_efficiency_base  # Normal efficiency
            )
        )

        # Wind cooling effect (small dynamic improvement)
        wind_effect = 1.0
        if 'wind_speed' in weather_df.columns:
            wind_effect = 1 + 0.002 * weather_df['wind_speed'].clip(0, 10)  # Max 2% improvement

        # Calculate AC power
        ac_power = dc_power * inverter_efficiency * wind_effect

        # CRITICAL: Clip to AC capacity to model inverter clipping
        # When DC power exceeds inverter capacity, AC output is limited
        return ac_power.clip(lower=0, upper=self.ac_capacity_mw)
    
    def _apply_cloud_dynamics(self, ac_power: pd.Series, 
                            weather_df: pd.DataFrame) -> pd.Series:
        """Apply cloud-induced variability and smoothing"""
        
        if 'cloud_cover' not in weather_df.columns:
            return ac_power
        
        cloud_cover = weather_df['cloud_cover']
        
        # Cloud variability factor (higher cloud cover = more variability)
        variability_factor = (cloud_cover / 100) * 0.3  # Max 30% variability
        
        # Add some realistic cloud-induced fluctuations
        np.random.seed(42)  # For reproducible results
        noise = np.random.normal(0, variability_factor, len(ac_power))
        
        # Apply noise only during daylight hours
        daylight_mask = ac_power > 0.01
        ac_power_noisy = ac_power.copy()
        ac_power_noisy[daylight_mask] *= (1 + noise[daylight_mask])
        
        # Apply smoothing to reduce unrealistic fluctuations
        if len(ac_power_noisy) > self.smoothing_window:
            ac_power_smoothed = ac_power_noisy.rolling(
                window=self.smoothing_window,
                center=True,
                min_periods=1
            ).mean()
        else:
            ac_power_smoothed = ac_power_noisy

        return ac_power_smoothed.clip(lower=0, upper=self.ac_capacity_mw)
    
    def _apply_realtime_calibration(self, ac_power: pd.Series, 
                                  current_conditions: Dict) -> pd.Series:
        """Apply real-time calibration based on current conditions"""
        
        # This is where you would calibrate against actual measurements
        # For now, we'll apply a simple adjustment based on current weather
        
        current_temp = current_conditions.get('temperature', 20)
        current_clouds = current_conditions.get('cloud_cover', 50)
        
        # Simple calibration adjustment (would be more sophisticated in practice)
        if current_temp > 30:
            # High temperature reduces efficiency
            calibration_factor = 0.95
        elif current_temp < 10:
            # Low temperature improves efficiency but reduces irradiance
            calibration_factor = 1.02
        else:
            calibration_factor = 1.0
        
        # Apply calibration to first few hours (assumes current conditions persist)
        calibration_window = min(16, len(ac_power))  # 4 hours at 15-min resolution
        ac_power_calibrated = ac_power.copy()
        ac_power_calibrated[:calibration_window] *= calibration_factor
        
        return ac_power_calibrated
    
    def _generate_uncertainty_bands(self, ac_power: pd.Series, 
                                  weather_df: pd.DataFrame) -> pd.DataFrame:
        """Generate uncertainty bands for risk management"""
        
        predictions = pd.DataFrame(index=ac_power.index)
        predictions['production_mw'] = ac_power
        
        # Base uncertainty depends on forecast horizon
        hours_ahead = np.arange(len(ac_power)) * (INTRADAY_RESOLUTION_MINUTES / 60)
        base_uncertainty = 0.05 + 0.02 * (hours_ahead / 24)  # 5-19% uncertainty
        
        # Weather-dependent uncertainty
        if 'cloud_cover' in weather_df.columns:
            weather_uncertainty = weather_df['cloud_cover'] / 100 * 0.15  # Up to 15% for full clouds
        else:
            weather_uncertainty = 0.1  # Default 10%
        
        # Combine uncertainties
        total_uncertainty = np.sqrt(base_uncertainty**2 + weather_uncertainty**2)
        
        # Generate quantiles
        predictions['q10'] = ac_power * (1 - 2 * total_uncertainty)
        predictions['q25'] = ac_power * (1 - total_uncertainty)
        predictions['q50'] = ac_power  # Median = mean for this model
        predictions['q75'] = ac_power * (1 + total_uncertainty)
        predictions['q90'] = ac_power * (1 + 2 * total_uncertainty)

        # Ensure physical constraints (clip to AC capacity)
        for col in ['q10', 'q25', 'q50', 'q75', 'q90']:
            predictions[col] = predictions[col].clip(lower=0, upper=self.ac_capacity_mw)
        
        # Ensure quantile ordering
        for i in range(len(predictions)):
            row = predictions.iloc[i]
            sorted_values = sorted([row['q10'], row['q25'], row['q50'], row['q75'], row['q90']])
            predictions.iloc[i, predictions.columns.get_loc('q10')] = sorted_values[0]
            predictions.iloc[i, predictions.columns.get_loc('q25')] = sorted_values[1]
            predictions.iloc[i, predictions.columns.get_loc('q50')] = sorted_values[2]
            predictions.iloc[i, predictions.columns.get_loc('q75')] = sorted_values[3]
            predictions.iloc[i, predictions.columns.get_loc('q90')] = sorted_values[4]
        
        return predictions
    
    def aggregate_to_hourly(self, predictions_15min: pd.DataFrame) -> pd.DataFrame:
        """Aggregate 15-minute predictions to hourly resolution"""
        
        # Define aggregation methods
        agg_methods = {
            'production_mw': 'mean',
            'q10': 'mean',
            'q25': 'mean',
            'q50': 'mean',
            'q75': 'mean',
            'q90': 'mean'
        }
        
        # For energy values, sum them up (since they're already in MWh for each 15-min period)
        energy_columns = ['energy_mwh', 'energy_q10_mwh', 'energy_q25_mwh', 
                         'energy_q50_mwh', 'energy_q75_mwh', 'energy_q90_mwh']
        
        for col in energy_columns:
            if col in predictions_15min.columns:
                agg_methods[col] = 'sum'
        
        # Resample to hourly
        hourly = predictions_15min.resample('h').agg(agg_methods)
        
        # Add metadata
        hourly['location'] = self.location_key
        hourly['resolution_minutes'] = 60
        hourly['aggregated_from'] = INTRADAY_RESOLUTION_MINUTES
        
        return hourly
    
    def get_forecast_summary(self, predictions: pd.DataFrame) -> Dict:
        """Generate a summary of the forecast for quick reference"""
        
        total_period_hours = len(predictions) * (INTRADAY_RESOLUTION_MINUTES / 60)
        
        summary = {
            'location': self.location_key,
            'forecast_start': predictions.index[0].isoformat(),
            'forecast_end': predictions.index[-1].isoformat(),
            'total_hours': total_period_hours,
            'resolution_minutes': INTRADAY_RESOLUTION_MINUTES,
            'capacity_mw': self.ac_capacity_mw,
            'dc_capacity_mw': self.dc_capacity_mw,
            'peak_production_mw': predictions['production_mw'].max(),
            'total_energy_mwh': predictions['production_mw'].sum() * (INTRADAY_RESOLUTION_MINUTES / 60),
            'average_hourly_mw': predictions['production_mw'].mean(),
            'capacity_factor': predictions['production_mw'].mean() / self.ac_capacity_mw,
            'generation_window': {
                'first_production': None,
                'last_production': None,
                'peak_hour': None
            }
        }
        
        # Find generation window
        producing = predictions[predictions['production_mw'] > 0.01]
        if not producing.empty:
            summary['generation_window']['first_production'] = producing.index[0].isoformat()
            summary['generation_window']['last_production'] = producing.index[-1].isoformat()
            peak_idx = producing['production_mw'].idxmax()
            summary['generation_window']['peak_hour'] = peak_idx.isoformat()

        return summary

    def _save_processed_weather(self, weather_df: pd.DataFrame,
                               solar_data: pd.DataFrame,
                               output_dir: str):
        """
        Save processed weather data with correct local solar calculations

        This creates weather data that matches the actual irradiance values
        used by the forecast model, corrected for local solar position.
        """
        import os

        logger.info("Generating processed weather data with local solar calculations")

        # Create processed weather DataFrame
        processed_weather = pd.DataFrame(index=weather_df.index)

        # Calculate corrected GHI based on local solar position
        # IMPORTANT: Always calculate GHI based on local solar elevation
        # Do NOT use raw API GHI as it's calculated for UTC solar position

        # Calculate clear-sky GHI for local position
        clear_sky_ghi = self._calculate_clear_sky_ghi(weather_df.index, solar_data)

        # Apply cloud factor from weather data
        cloud_factor = 1 - (weather_df.get('cloud_cover', 0) / 100) * 0.8
        ghi = clear_sky_ghi * cloud_factor
        ghi = ghi.clip(lower=0)

        # Set GHI to zero when sun is below horizon
        ghi[solar_data['elevation'] <= 0] = 0
        processed_weather['ghi'] = ghi

        # Calculate DNI and DHI using local solar geometry
        solar_elevation_rad = np.radians(solar_data['elevation'])

        # DNI calculation - ALWAYS calculate using local solar elevation
        # Do NOT use raw API DNI as it's based on UTC solar position
        cloud_cover = weather_df.get('cloud_cover', 0)
        clearness_factor = np.where(
            cloud_cover < 10,
            0.90,
            np.where(
                cloud_cover < 30,
                0.80,
                1 - (cloud_cover / 100) * 0.7
            )
        )
        with np.errstate(divide='ignore', invalid='ignore'):
            dni = ghi / np.maximum(np.sin(solar_elevation_rad), 0.1) * clearness_factor
            dni = np.clip(dni, 0, 950)

        # Set DNI to zero when sun is below horizon
        dni[solar_data['elevation'] <= 0] = 0
        processed_weather['dni'] = dni

        # DHI calculation - ALWAYS calculate using local values
        # Estimate DHI as remainder: GHI = DNI * sin(elevation) + DHI
        dhi = ghi - dni * np.sin(solar_elevation_rad)
        dhi = np.clip(dhi, 0, ghi)

        # Set DHI to zero when sun is below horizon
        dhi[solar_data['elevation'] <= 0] = 0
        processed_weather['dhi'] = dhi

        # Calculate POA irradiance (Plane of Array)
        poa_irradiance = self._ghi_to_poa(ghi, solar_data, weather_df)
        processed_weather['poa_irradiance'] = poa_irradiance

        # Add solar position data
        processed_weather['solar_elevation'] = solar_data['elevation']
        processed_weather['solar_azimuth'] = solar_data['azimuth']
        processed_weather['air_mass'] = solar_data['air_mass']

        # Copy other weather parameters directly (these don't depend on solar position)
        for col in ['temperature', 'wind_speed', 'cloud_cover', 'humidity',
                   'precipitation', 'pressure', 'weather_code']:
            if col in weather_df.columns:
                processed_weather[col] = weather_df[col]

        # Convert to local timezone (CET/CEST) for saving
        processed_weather_local = processed_weather.copy()
        if processed_weather_local.index.tz is not None:
            processed_weather_local.index = processed_weather_local.index.tz_convert('Europe/Berlin')
            # Make naive for CSV compatibility
            processed_weather_local.index = processed_weather_local.index.tz_localize(None)

        # Save to CSV
        output_path = os.path.join(output_dir, 'processed_weather_local.csv')
        processed_weather_local.to_csv(output_path)
        logger.info(f"Saved processed weather data to {output_path}")
        logger.info(f"Processed weather includes local solar calculations for {len(processed_weather_local)} timestamps")