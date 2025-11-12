"""
Data aggregation system for intraday solar forecasts
Converts between different time resolutions and formats
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz
import json

from config import (
    INTRADAY_RESOLUTION_MINUTES, AGGREGATION_LEVELS,
    OUTPUT_TIMEZONE, OUTPUT_TIMEZONE_NAME, OUTPUT_TIMEZONE_NOTICE
)

logger = logging.getLogger(__name__)


class IntradayDataAggregator:
    """Handles aggregation and formatting of intraday forecast data"""
    
    def __init__(self):
        self.supported_resolutions = ['15min', '30min', '1hour', '3hour', '6hour', '1day']
        
    def aggregate_forecast(self, forecast_15min: pd.DataFrame,
                         target_resolutions: List[str] = None) -> Dict[str, pd.DataFrame]:
        """
        Aggregate 15-minute forecast to multiple resolutions
        
        Args:
            forecast_15min: DataFrame with 15-minute resolution forecasts
            target_resolutions: List of target resolutions to generate
            
        Returns:
            Dictionary with DataFrames for each resolution
        """
        if target_resolutions is None:
            target_resolutions = AGGREGATION_LEVELS
            
        logger.info(f"Aggregating forecast to resolutions: {target_resolutions}")
        
        aggregated_data = {}
        
        for resolution in target_resolutions:
            if resolution not in self.supported_resolutions:
                logger.warning(f"Unsupported resolution: {resolution}, skipping")
                continue
                
            logger.debug(f"Aggregating to {resolution}")
            aggregated_df = self._aggregate_to_resolution(forecast_15min, resolution)
            aggregated_data[resolution] = aggregated_df
            
        return aggregated_data
    
    def _aggregate_to_resolution(self, df: pd.DataFrame, resolution: str) -> pd.DataFrame:
        """Aggregate data to a specific resolution"""
        
        # Define frequency mapping
        freq_map = {
            '15min': '15min',
            '30min': '30min', 
            '1hour': '1h',
            '3hour': '3h',
            '6hour': '6h',
            '1day': '1D'
        }
        
        if resolution not in freq_map:
            raise ValueError(f"Unsupported resolution: {resolution}")
            
        freq = freq_map[resolution]
        
        # Define aggregation methods for different columns
        agg_methods = {
            'production_mw': 'mean',  # Average power
            'q10': 'mean',
            'q25': 'mean', 
            'q50': 'mean',
            'q75': 'mean',
            'q90': 'mean'
        }
        
        # Energy columns should be summed when aggregating
        energy_columns = ['energy_mwh', 'energy_q10_mwh', 'energy_q25_mwh', 
                         'energy_q50_mwh', 'energy_q75_mwh', 'energy_q90_mwh']
        
        for col in energy_columns:
            if col in df.columns:
                agg_methods[col] = 'sum'
        
        # Add special handling for metadata columns
        metadata_cols = []
        for col in df.columns:
            if col not in agg_methods:
                if col in ['location', 'forecast_timestamp']:
                    metadata_cols.append(col)
                    agg_methods[col] = 'first'
                elif col == 'resolution_minutes':
                    metadata_cols.append(col)
                    agg_methods[col] = 'first'
        
        # Perform aggregation
        try:
            aggregated = df.resample(freq).agg(agg_methods)
            
            # Update resolution metadata
            if 'resolution_minutes' in aggregated.columns:
                resolution_minutes = self._get_resolution_minutes(resolution)
                aggregated['resolution_minutes'] = resolution_minutes
                
            # Add energy calculations
            if resolution != '15min':
                resolution_hours = self._get_resolution_hours(resolution)
                aggregated['energy_mwh'] = aggregated['production_mw'] * resolution_hours
                
            return aggregated
            
        except Exception as e:
            logger.error(f"Failed to aggregate to {resolution}: {e}")
            return pd.DataFrame()
    
    def _get_resolution_minutes(self, resolution: str) -> int:
        """Get resolution in minutes"""
        resolution_map = {
            '15min': 15,
            '30min': 30,
            '1hour': 60,
            '3hour': 180,
            '6hour': 360,
            '1day': 1440
        }
        return resolution_map.get(resolution, 15)
    
    def _get_resolution_hours(self, resolution: str) -> float:
        """Get resolution in hours"""
        return self._get_resolution_minutes(resolution) / 60.0
    
    def create_trading_format(self, hourly_forecast: pd.DataFrame) -> pd.DataFrame:
        """Create format suitable for energy trading operations"""
        
        trading_df = hourly_forecast.copy()
        
        # Add trading-specific columns
        trading_df['delivery_start'] = trading_df.index
        trading_df['delivery_end'] = trading_df.index + timedelta(hours=1)
        
        # Convert to output timezone (CET/CEST)
        local_tz = pytz.timezone(OUTPUT_TIMEZONE)
        trading_df['delivery_start_local'] = trading_df['delivery_start'].dt.tz_convert(local_tz)
        trading_df['delivery_end_local'] = trading_df['delivery_end'].dt.tz_convert(local_tz)
        
        # Add market hour
        trading_df['market_hour'] = trading_df['delivery_start_local'].dt.hour + 1  # Hour 1-24
        
        # Energy calculations (use integrated energy if available, otherwise calculate from power)
        if 'energy_mwh' in trading_df.columns:
            # Use already calculated integrated energy
            trading_df['energy_p10_mwh'] = trading_df.get('energy_q10_mwh', trading_df['q10'])
            trading_df['energy_p90_mwh'] = trading_df.get('energy_q90_mwh', trading_df['q90'])
        else:
            # Calculate from power (assuming 1 hour duration)
            trading_df['energy_mwh'] = trading_df['production_mw']
            trading_df['energy_p10_mwh'] = trading_df['q10']
            trading_df['energy_p90_mwh'] = trading_df['q90']
        
        # Risk metrics
        trading_df['forecast_uncertainty'] = trading_df['q90'] - trading_df['q10']
        trading_df['relative_uncertainty'] = trading_df['forecast_uncertainty'] / (trading_df['production_mw'] + 0.001)
        
        # Reorder columns for trading desk
        trading_columns = [
            'delivery_start_local', 'delivery_end_local', 'market_hour',
            'production_mw', 'energy_mwh',
            'q10', 'q25', 'q50', 'q75', 'q90',
            'energy_p10_mwh', 'energy_p90_mwh',
            'forecast_uncertainty', 'relative_uncertainty'
        ]
        
        return trading_df[trading_columns]
    
    def create_api_format(self, forecasts: Dict[str, pd.DataFrame],
                         location_key: str) -> Dict:
        """Create API-ready format for external consumption"""
        
        api_data = {
            'metadata': {
                'location': location_key,
                'forecast_timestamp': datetime.now(pytz.UTC).isoformat(),
                'forecast_horizon_days': 7,
                'available_resolutions': list(forecasts.keys()),
                'data_timezone': 'UTC',
                'display_timezone': OUTPUT_TIMEZONE,
                'display_timezone_name': OUTPUT_TIMEZONE_NAME,
                'timezone_notice': OUTPUT_TIMEZONE_NOTICE
            },
            'forecasts': {}
        }
        
        for resolution, df in forecasts.items():
            forecast_data = []
            
            for idx, row in df.iterrows():
                data_point = {
                    'timestamp': idx.isoformat(),
                    'production_mw': round(row['production_mw'], 4),
                    'uncertainty_bands': {
                        'p10': round(row['q10'], 4),
                        'p25': round(row['q25'], 4),
                        'p50': round(row['q50'], 4),
                        'p75': round(row['q75'], 4),
                        'p90': round(row['q90'], 4)
                    }
                }
                
                # Add energy values if available
                if 'energy_mwh' in row:
                    data_point['energy_mwh'] = round(row['energy_mwh'], 6)
                    data_point['energy_uncertainty_bands'] = {
                        'p10': round(row.get('energy_q10_mwh', 0), 6),
                        'p25': round(row.get('energy_q25_mwh', 0), 6),
                        'p50': round(row.get('energy_q50_mwh', 0), 6),
                        'p75': round(row.get('energy_q75_mwh', 0), 6),
                        'p90': round(row.get('energy_q90_mwh', 0), 6)
                    }
                    
                forecast_data.append(data_point)
            
            api_data['forecasts'][resolution] = {
                'resolution_minutes': self._get_resolution_minutes(resolution),
                'data_points': len(forecast_data),
                'data': forecast_data
            }
        
        return api_data
    
    def create_csv_exports(self, forecasts: Dict[str, pd.DataFrame],
                          location_key: str, output_dir: str) -> List[str]:
        """Export forecasts to CSV files"""
        
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        # Import LOCATIONS config to get timezone
        from config import LOCATIONS
        
        exported_files = []
        timestamp = datetime.now(pytz.UTC).strftime('%Y%m%d_%H%M%S')
        
        # Get local timezone for the location
        location_tz = pytz.timezone(LOCATIONS[location_key]['timezone'])
        
        for resolution, df in forecasts.items():
            # Prepare export DataFrame
            export_df = df.copy()
            
            # Reset index to make timestamp a column
            export_df = export_df.reset_index()
            export_df = export_df.rename(columns={'index': 'timestamp_utc'})
            
            # Convert timestamps from UTC to local time and shift backward by 1 hour
            if 'timestamp_utc' in export_df.columns:
                export_df['timestamp_utc'] = pd.to_datetime(export_df['timestamp_utc'])
                # Convert to local time and subtract 1 hour shift (for EET/CET difference)
                export_df['timestamp'] = export_df['timestamp_utc'].dt.tz_convert(location_tz) - timedelta(hours=1)
                
                # For hourly format, create the required columns
                if resolution == '1hour':
                    # Extract date/time components in local time
                    export_df['YEAR'] = export_df['timestamp'].dt.year
                    export_df['MONTH'] = export_df['timestamp'].dt.month
                    export_df['DAY'] = export_df['timestamp'].dt.day
                    export_df['HOUR_START'] = export_df['timestamp'].dt.hour
                    export_df['HOUR_END'] = (export_df['timestamp'] + timedelta(hours=1)).dt.hour
                    
                    # Add DAY_END for cases where hour crosses midnight
                    export_df['DAY_END'] = (export_df['timestamp'] + timedelta(hours=1)).dt.day
                    
                    # Map hours to intervals (1-24)
                    export_df['interval'] = export_df['HOUR_START'] + 1
                    
                    # Rename columns to match required format
                    export_df = export_df.rename(columns={
                        'production_mw': 'power_mw'
                    })
                    
                    # Apply hardcoded forecast values at specific intervals ONLY if current forecast is 0
                    # Convert kW to MW (divide by 1000)
                    hardcoded_values = {
                        # Removed hardcoded intervals to allow natural physics-based models
                    }
                    
                    for interval, power_mw in hardcoded_values.items():
                        # Only apply hardcoded value if current power is 0
                        mask = (export_df['interval'] == interval) & (export_df['power_mw'] == 0)
                        if mask.any():
                            export_df.loc[mask, 'power_mw'] = power_mw
                            export_df.loc[mask, 'energy_mwh'] = power_mw
                            
                            # Update quantiles to be consistent
                            export_df.loc[mask, 'q10'] = power_mw * 0.9
                            export_df.loc[mask, 'q25'] = power_mw * 0.95
                            export_df.loc[mask, 'q50'] = power_mw
                            export_df.loc[mask, 'q75'] = power_mw * 1.05
                            export_df.loc[mask, 'q90'] = power_mw * 1.1
                    
                    # Select and order columns for hourly format
                    hourly_columns = [
                        'timestamp', 'YEAR', 'MONTH', 'DAY', 'HOUR_START', 'HOUR_END', 'interval',
                        'power_mw', 'energy_mwh', 'q10', 'q25', 'q50', 'q75', 'q90'
                    ]
                    
                    # Add DAY_END only if needed (when crossing midnight)
                    if (export_df['DAY_END'] != export_df['DAY']).any():
                        hourly_columns.insert(6, 'DAY_END')
                    else:
                        export_df = export_df.drop(columns=['DAY_END'])
                    
                    # Keep only required columns
                    export_df = export_df[hourly_columns]
                    
                    # Filter out entries from July 2nd (keep only July 3rd and later)
                    # This ensures the forecast starts at July 3rd 00:00
                    export_df_datetime = pd.to_datetime(export_df['timestamp'])
                    export_df = export_df[export_df_datetime >= '2025-07-03']
                    
                    # Format timestamp for hourly
                    export_df['timestamp'] = export_df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
                elif resolution == '15min':
                    # For 15-minute format, add time component columns
                    export_df['YEAR'] = export_df['timestamp'].dt.year
                    export_df['MONTH'] = export_df['timestamp'].dt.month
                    export_df['DAY'] = export_df['timestamp'].dt.day
                    export_df['HOUR_START'] = export_df['timestamp'].dt.hour
                    export_df['MINUTE_START'] = export_df['timestamp'].dt.minute
                    export_df['HOUR_END'] = (export_df['timestamp'] + timedelta(minutes=15)).dt.hour
                    export_df['MINUTE_END'] = (export_df['timestamp'] + timedelta(minutes=15)).dt.minute
                    export_df['DAY_END'] = (export_df['timestamp'] + timedelta(minutes=15)).dt.day

                    # Calculate interval (1-96 for 15-minute intervals in a day)
                    export_df['interval'] = (export_df['HOUR_START'] * 4) + (export_df['MINUTE_START'] // 15) + 1

                    # Rename production_mw to power_mw for consistency
                    if 'production_mw' in export_df.columns:
                        export_df = export_df.rename(columns={'production_mw': 'power_mw'})

                    # Select and order columns for 15-minute format
                    columns_15min = [
                        'timestamp', 'YEAR', 'MONTH', 'DAY', 'HOUR_START', 'MINUTE_START',
                        'HOUR_END', 'MINUTE_END', 'DAY_END', 'interval',
                        'power_mw', 'energy_mwh',
                        'q10', 'energy_q10_mwh',
                        'q25', 'energy_q25_mwh',
                        'q50', 'energy_q50_mwh',
                        'q75', 'energy_q75_mwh',
                        'q90', 'energy_q90_mwh'
                    ]

                    # Keep only columns that exist
                    columns_15min = [col for col in columns_15min if col in export_df.columns]
                    export_df = export_df[columns_15min]

                    # Format timestamp for 15-minute
                    export_df['timestamp'] = pd.to_datetime(export_df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    # For other resolutions, keep simpler structure
                    export_df['timestamp'] = export_df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
                    # Remove the UTC timestamp column and location column
                    export_df = export_df.drop(columns=['timestamp_utc'])
                    if 'location' in export_df.columns:
                        export_df = export_df.drop(columns=['location'])
            
            # Round numerical values
            numeric_cols = ['power_mw', 'production_mw', 'q10', 'q25', 'q50', 'q75', 'q90',
                           'energy_mwh', 'energy_q10_mwh', 'energy_q25_mwh', 
                           'energy_q50_mwh', 'energy_q75_mwh', 'energy_q90_mwh']
            for col in numeric_cols:
                if col in export_df.columns:
                    export_df[col] = export_df[col].round(6)  # More precision for energy values
            
            # Create filename
            filename = f"{location_key}_intraday_{resolution}_{timestamp}.csv"
            filepath = os.path.join(output_dir, filename)
            
            # Export CSV data directly without comments
            export_df.to_csv(filepath, index=False)
            
            exported_files.append(filepath)
            
            logger.info(f"Exported {resolution} forecast to: {filepath}")
        
        return exported_files
    
    def create_summary_report(self, forecasts: Dict[str, pd.DataFrame],
                            location_key: str) -> Dict:
        """Create a comprehensive summary report"""
        
        report = {
            'location': location_key,
            'report_timestamp': datetime.now(pytz.UTC).isoformat(),
            'forecast_period': {},
            'capacity_analysis': {},
            'energy_analysis': {},
            'uncertainty_analysis': {},
            'operational_insights': {}
        }
        
        # Use hourly data for main analysis
        if '1hour' in forecasts:
            hourly_df = forecasts['1hour']
        else:
            # Fallback to 15min aggregated to hourly
            hourly_df = self._aggregate_to_resolution(forecasts['15min'], '1hour')
        
        # Forecast period
        report['forecast_period'] = {
            'start': hourly_df.index[0].isoformat(),
            'end': hourly_df.index[-1].isoformat(),
            'duration_hours': len(hourly_df),
            'duration_days': len(hourly_df) / 24
        }
        
        # Capacity analysis - use actual capacity from config
        from config import LOCATIONS
        if location_key in LOCATIONS:
            capacity_mw = LOCATIONS[location_key]['estimated_capacity_mw']
        else:
            # Fallback to estimation (should not happen)
            capacity_mw = hourly_df['production_mw'].max() / 0.8
        
        report['capacity_analysis'] = {
            'capacity_mw': round(capacity_mw, 3),
            'peak_production_mw': round(hourly_df['production_mw'].max(), 3),
            'average_production_mw': round(hourly_df['production_mw'].mean(), 3),
            'capacity_factor': round(hourly_df['production_mw'].mean() / capacity_mw, 3) if capacity_mw > 0 else 0
        }
        
        # Energy analysis
        total_energy = hourly_df['production_mw'].sum()  # MWh
        report['energy_analysis'] = {
            'total_energy_mwh': round(total_energy, 1),
            'daily_average_mwh': round(total_energy / (len(hourly_df) / 24), 1),
            'peak_day_mwh': round(hourly_df.resample('D')['production_mw'].sum().max(), 1),
            'energy_p10_mwh': round(hourly_df['q10'].sum(), 1),
            'energy_p90_mwh': round(hourly_df['q90'].sum(), 1)
        }
        
        # Uncertainty analysis
        avg_uncertainty = (hourly_df['q90'] - hourly_df['q10']).mean()
        relative_uncertainty = avg_uncertainty / (hourly_df['production_mw'].mean() + 0.001)
        
        report['uncertainty_analysis'] = {
            'average_uncertainty_mw': round(avg_uncertainty, 3),
            'relative_uncertainty_pct': round(relative_uncertainty * 100, 1),
            'max_uncertainty_mw': round((hourly_df['q90'] - hourly_df['q10']).max(), 3),
            'uncertainty_range_mwh': round((hourly_df['q90'] - hourly_df['q10']).sum(), 1)
        }
        
        # Operational insights
        producing_hours = (hourly_df['production_mw'] > 0.01).sum()
        peak_hour = hourly_df['production_mw'].idxmax()
        
        report['operational_insights'] = {
            'producing_hours': producing_hours,
            'non_producing_hours': len(hourly_df) - producing_hours,
            'peak_production_time': peak_hour.isoformat() if pd.notna(peak_hour) else None,
            'generation_efficiency': round(producing_hours / len(hourly_df), 3),
            'forecast_quality': 'high' if relative_uncertainty < 0.15 else 'medium' if relative_uncertainty < 0.30 else 'low'
        }
        
        return report
    
    def export_json_summary(self, report: Dict, output_path: str):
        """Export summary report as JSON"""
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Summary report exported to: {output_path}")