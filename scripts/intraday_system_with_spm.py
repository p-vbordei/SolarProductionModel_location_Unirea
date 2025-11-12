"""
Enhanced Intraday Forecasting System with SPM Support
Allows choosing between ML/Physics model and Smart Persistence Model
"""
import pandas as pd
import numpy as np
import logging
import sys
import os
from datetime import datetime, timedelta
import json
import pytz
from typing import Dict, Optional, List
import time
import schedule
import threading

# Add scripts directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import (
    LOCATIONS, INTRADAY_FORECAST_DAYS, INTRADAY_RESOLUTION_MINUTES,
    INTRADAY_UPDATE_FREQUENCY_HOURS, AGGREGATION_LEVELS,
    LOG_LEVEL, LOG_FORMAT
)
from intraday_weather_fetcher import IntradayWeatherFetcher
from intraday_forecast_model import IntradaySolarForecastModel
from smart_persistence_model import SmartPersistenceModel
from intraday_aggregator import IntradayDataAggregator
from forecast_comparison import ForecastComparison
from export_weather_parameters import export_weather_parameters

# Set up logging
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


class EnhancedIntradayForecastingSystem:
    """Enhanced intraday solar forecasting system with multiple model support"""
    
    def __init__(self, location_key: str = 'cm_forecast', model_type: str = 'ml_physics'):
        """
        Initialize the enhanced system
        
        Args:
            location_key: Location identifier from config
            model_type: 'ml_physics', 'smart_persistence', or 'comparison'
        """
        self.location_key = location_key
        self.model_type = model_type
        
        if location_key not in LOCATIONS:
            raise ValueError(f"Location {location_key} not found in configuration")
            
        self.location_config = LOCATIONS[location_key]
        
        # Initialize components
        self.weather_fetcher = IntradayWeatherFetcher()
        self.aggregator = IntradayDataAggregator()
        
        # Initialize forecast models based on type
        if model_type in ['ml_physics', 'comparison']:
            self.ml_model = IntradaySolarForecastModel(location_key, self.location_config)
        
        if model_type in ['smart_persistence', 'comparison']:
            self.spm_model = SmartPersistenceModel(location_key, self.location_config)
            
        if model_type == 'comparison':
            self.comparison = ForecastComparison(location_key)
        
        # System state
        self.latest_forecast = None
        self.forecast_history = {}
        self.system_status = 'initialized'
        self.last_update = None
        
        # Output configuration
        self.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'data_output', 'intraday'
        )
        os.makedirs(self.output_dir, exist_ok=True)
        
        logger.info(f"Enhanced intraday system initialized for {self.location_config['name']}")
        logger.info(f"Model type: {model_type}")
    
    def run_single_forecast(self) -> Dict:
        """Run a single forecast update with selected model"""
        start_time = time.time()
        
        try:
            logger.info("="*60)
            logger.info("STARTING ENHANCED INTRADAY FORECAST UPDATE")
            logger.info(f"Location: {self.location_config['name']}")
            logger.info(f"Model: {self.model_type}")
            logger.info(f"Time: {datetime.now(pytz.UTC)}")
            logger.info("="*60)
            
            # Step 1: Fetch weather data
            logger.info("Step 1: Fetching real-time weather data...")
            weather_df, weather_source = self.weather_fetcher.fetch_intraday_weather(self.location_key)
            
            # Get current conditions
            current_conditions = self.weather_fetcher.get_current_weather(self.location_key)
            
            logger.info(f"Weather data: {len(weather_df)} points from {weather_source}")
            logger.info(f"Current conditions: {current_conditions['temperature']:.1f}°C, "
                       f"{current_conditions['cloud_cover']:.0f}% clouds")
            
            # Export weather parameters for debugging
            params_dir = export_weather_parameters(
                weather_df=weather_df,
                location_config=self.location_config,
                forecast_timestamp=datetime.now(pytz.UTC),
                output_dir=self.output_dir
            )

            # Step 2: Generate predictions based on model type
            if self.model_type == 'ml_physics':
                predictions_15min = self._run_ml_physics_model(weather_df, current_conditions, params_dir)
            elif self.model_type == 'smart_persistence':
                predictions_15min = self._run_spm_model(weather_df, current_conditions)
            elif self.model_type == 'comparison':
                predictions_15min = self._run_comparison(weather_df, current_conditions, params_dir)
            else:
                raise ValueError(f"Unknown model type: {self.model_type}")
            
            # For comparison mode, we'll use the ML model output for aggregation
            if self.model_type == 'comparison' and 'ml_physics' in predictions_15min:
                forecast_to_aggregate = predictions_15min['ml_physics']
            else:
                forecast_to_aggregate = predictions_15min
            
            # Step 3: Create multiple aggregations
            logger.info("Step 3: Creating multiple time resolutions...")
            aggregated_forecasts = self.aggregator.aggregate_forecast(
                forecast_to_aggregate, AGGREGATION_LEVELS
            )
            
            # Step 4: Create outputs
            logger.info("Step 4: Generating outputs...")
            
            # API format
            api_data = self.aggregator.create_api_format(
                aggregated_forecasts, self.location_key
            )
            api_data['model_type'] = self.model_type
            
            # Trading format
            if '1hour' in aggregated_forecasts:
                trading_data = self.aggregator.create_trading_format(
                    aggregated_forecasts['1hour']
                )
            
            # Summary report
            summary_report = self.aggregator.create_summary_report(
                aggregated_forecasts, self.location_key
            )
            summary_report['model_type'] = self.model_type
            
            # Step 5: Export files
            logger.info("Step 5: Exporting files...")
            
            # Add model suffix to filenames
            model_suffix = f"_{self.model_type}" if self.model_type != 'ml_physics' else ""
            
            # CSV exports
            csv_files = self.aggregator.create_csv_exports(
                aggregated_forecasts, self.location_key, self.output_dir
            )
            
            # JSON API export
            api_file = os.path.join(self.output_dir, 
                                   f"{self.location_key}_api_latest{model_suffix}.json")
            with open(api_file, 'w') as f:
                json.dump(api_data, f, indent=2, default=str)
            
            # Trading format export
            if '1hour' in aggregated_forecasts:
                trading_file = os.path.join(self.output_dir, 
                                          f"{self.location_key}_trading_latest{model_suffix}.csv")
                trading_data.to_csv(trading_file)
            
            # Summary report export
            summary_file = os.path.join(self.output_dir, 
                                       f"{self.location_key}_summary_latest{model_suffix}.json")
            self.aggregator.export_json_summary(summary_report, summary_file)
            
            # For comparison mode, export comparison results
            if self.model_type == 'comparison':
                comparison_report = self._export_comparison_results(predictions_15min)
                summary_report['comparison'] = comparison_report
            
            # Update system state
            self.latest_forecast = {
                'timestamp': datetime.now(pytz.UTC),
                'forecasts': aggregated_forecasts,
                'api_data': api_data,
                'summary': summary_report,
                'weather_source': weather_source,
                'model_type': self.model_type,
                'execution_time_seconds': time.time() - start_time
            }
            
            self.last_update = datetime.now(pytz.UTC)
            self.system_status = 'operational'
            
            # Store in history
            history_key = self.last_update.strftime('%Y%m%d_%H%M')
            self.forecast_history[history_key] = self.latest_forecast
            
            # Clean old history
            if len(self.forecast_history) > 48:  # Keep 48 updates
                oldest_key = min(self.forecast_history.keys())
                del self.forecast_history[oldest_key]
            
            execution_time = time.time() - start_time
            
            logger.info("="*60)
            logger.info("ENHANCED INTRADAY FORECAST UPDATE COMPLETED")
            logger.info(f"Model: {self.model_type}")
            logger.info(f"Execution time: {execution_time:.1f} seconds")
            logger.info(f"Files exported to: {self.output_dir}")
            logger.info(f"Peak forecast: {summary_report['capacity_analysis']['peak_production_mw']:.3f} MW")
            logger.info(f"Total energy: {summary_report['energy_analysis']['total_energy_mwh']:.1f} MWh")
            logger.info("="*60)
            
            return {
                'status': 'success',
                'model_type': self.model_type,
                'execution_time': execution_time,
                'summary': summary_report,
                'files_created': csv_files + [api_file, summary_file],
                'forecast_timestamp': self.last_update.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Forecast update failed: {str(e)}", exc_info=True)
            self.system_status = 'error'
            
            return {
                'status': 'error',
                'model_type': self.model_type,
                'error': str(e),
                'execution_time': time.time() - start_time,
                'forecast_timestamp': datetime.now(pytz.UTC).isoformat()
            }
    
    def _run_ml_physics_model(self, weather_df: pd.DataFrame,
                             current_conditions: Dict,
                             params_dir: str) -> pd.DataFrame:
        """Run ML/Physics model with processed weather saving"""
        logger.info("Step 2: Generating 15-minute ML/Physics forecasts...")
        predictions = self.ml_model.predict_intraday(
            weather_df,
            current_conditions,
            save_processed_weather=True,
            output_dir=params_dir
        )
        predictions['model'] = 'ml_physics'
        return predictions
    
    def _run_spm_model(self, weather_df: pd.DataFrame, 
                      current_conditions: Dict) -> pd.DataFrame:
        """Run Smart Persistence Model"""
        logger.info("Step 2: Generating 15-minute SPM forecasts...")
        
        # Get current power from weather conditions or estimate
        current_timestamp = datetime.now(self.location_config['timezone'])
        
        # Estimate current power from weather if not measured
        if 'ghi' in weather_df.columns and current_timestamp in weather_df.index:
            current_ghi = weather_df.loc[current_timestamp, 'ghi']
            current_temp = current_conditions['temperature']
            temp_effect = 1 + (-0.004) * (current_temp - 25)
            current_power = self.location_config['estimated_capacity_mw'] * (current_ghi / 1000) * 0.78 * temp_effect
        else:
            # Fallback estimation
            current_power = self.location_config['estimated_capacity_mw'] * 0.3
        
        current_power = float(np.clip(current_power, 0, self.location_config['estimated_capacity_mw']))
        
        # Generate SPM forecast
        hours_ahead = INTRADAY_FORECAST_DAYS * 24
        predictions = self.spm_model.forecast_intraday(
            current_power_mw=current_power,
            current_timestamp=current_timestamp,
            hours_ahead=hours_ahead,
            resolution_minutes=INTRADAY_RESOLUTION_MINUTES
        )
        
        predictions['model'] = 'smart_persistence'
        return predictions
    
    def _run_comparison(self, weather_df: pd.DataFrame,
                       current_conditions: Dict,
                       params_dir: str) -> Dict[str, pd.DataFrame]:
        """Run comparison of multiple models"""
        logger.info("Step 2: Running model comparison...")

        results = {}

        # Run ML/Physics model
        try:
            ml_predictions = self._run_ml_physics_model(weather_df, current_conditions, params_dir)
            results['ml_physics'] = ml_predictions
        except Exception as e:
            logger.error(f"ML model failed: {e}")
        
        # Run SPM
        try:
            spm_predictions = self._run_spm_model(weather_df, current_conditions)
            results['smart_persistence'] = spm_predictions
        except Exception as e:
            logger.error(f"SPM failed: {e}")
        
        return results
    
    def _export_comparison_results(self, predictions: Dict[str, pd.DataFrame]) -> Dict:
        """Export comparison results and metrics"""
        if not isinstance(predictions, dict):
            return {}
        
        comparison_data = {}
        
        # Calculate differences between models
        if 'ml_physics' in predictions and 'smart_persistence' in predictions:
            ml_df = predictions['ml_physics']
            spm_df = predictions['smart_persistence']
            
            # Find common timestamps
            common_idx = ml_df.index.intersection(spm_df.index)
            
            if len(common_idx) > 0:
                ml_values = ml_df.loc[common_idx, 'production_mw'].values
                spm_values = spm_df.loc[common_idx, 'production_mw'].values
                
                # Calculate metrics
                mae = np.mean(np.abs(ml_values - spm_values))
                rmse = np.sqrt(np.mean((ml_values - spm_values) ** 2))
                correlation = np.corrcoef(ml_values, spm_values)[0, 1] if len(ml_values) > 1 else np.nan
                
                comparison_data = {
                    'ml_vs_spm': {
                        'mae_mw': float(mae),
                        'rmse_mw': float(rmse),
                        'correlation': float(correlation),
                        'mean_diff_mw': float(np.mean(ml_values - spm_values)),
                        'max_diff_mw': float(np.max(np.abs(ml_values - spm_values))),
                        'n_samples': len(common_idx)
                    }
                }
                
                # Export comparison plot
                plot_file = os.path.join(self.output_dir, 
                                       f"{self.location_key}_comparison_latest.png")
                self.comparison.plot_comparison(predictions, save_path=plot_file)
                comparison_data['plot_file'] = plot_file
        
        return comparison_data
    
    def get_model_info(self) -> Dict:
        """Get information about the configured model"""
        info = {
            'model_type': self.model_type,
            'description': '',
            'advantages': [],
            'use_cases': []
        }
        
        if self.model_type == 'ml_physics':
            info['description'] = 'Machine Learning with Physics-based fallback'
            info['advantages'] = [
                'High accuracy for complex weather patterns',
                'Learns from historical data',
                'Handles non-linear relationships'
            ]
            info['use_cases'] = [
                'Day-ahead forecasting',
                'Complex weather conditions',
                'Long-term accuracy optimization'
            ]
        elif self.model_type == 'smart_persistence':
            info['description'] = 'Smart Persistence Model using clear-sky index'
            info['advantages'] = [
                'Simple and robust',
                'No training data required',
                'Fast computation',
                'Good baseline performance'
            ]
            info['use_cases'] = [
                'Short-term forecasting (< 4 hours)',
                'Real-time updates',
                'Baseline comparison',
                'Limited data scenarios'
            ]
        elif self.model_type == 'comparison':
            info['description'] = 'Run multiple models for comparison'
            info['advantages'] = [
                'Compare model performance',
                'Ensemble insights',
                'Risk assessment'
            ]
            info['use_cases'] = [
                'Model validation',
                'Performance benchmarking',
                'Research and development'
            ]
        
        return info
    
    def get_system_status(self) -> Dict:
        """Get current system status"""
        status = {
            'system_status': self.system_status,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'location': self.location_config['name'],
            'model_type': self.model_type,
            'forecast_available': self.latest_forecast is not None,
            'forecast_history_count': len(self.forecast_history)
        }
        
        if self.latest_forecast:
            status['latest_forecast_time'] = self.latest_forecast.get('forecast_time')
            
        return status
    
    def get_forecast_history(self) -> Dict:
        """Get forecast history summary"""
        history_data = {}
        
        for timestamp, forecast_data in self.forecast_history.items():
            history_data[timestamp] = {
                'model': forecast_data.get('model_type', self.model_type),
                'timestamp': forecast_data.get('timestamp', timestamp),
                'peak_mw': forecast_data['summary']['capacity_analysis']['peak_production_mw'],
                'total_mwh': forecast_data['summary']['energy_analysis']['total_energy_mwh']
            }
        
        return history_data
    
    def export_current_state(self) -> str:
        """Export current system state for debugging"""
        state_file = os.path.join(self.output_dir, f"{self.location_key}_system_state.json")
        
        state_data = {
            'system_status': self.get_system_status(),
            'latest_forecast_summary': self.latest_forecast['summary'] if self.latest_forecast else None,
            'forecast_history_summary': self.get_forecast_history(),
            'export_timestamp': datetime.now(pytz.UTC).isoformat()
        }
        
        with open(state_file, 'w') as f:
            json.dump(state_data, f, indent=2, default=str)
        
        logger.info(f"System state exported to: {state_file}")
        return state_file


def main():
    """Main entry point for enhanced system"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced Intraday Solar Forecasting System')
    parser.add_argument('--location', default='cm_forecast', help='Location key for forecasting')
    parser.add_argument('--model', choices=['ml_physics', 'smart_persistence', 'comparison'], 
                       default='ml_physics', help='Forecasting model to use')
    parser.add_argument('--mode', choices=['single', 'scheduled'], default='single', 
                       help='Run mode: single update or continuous scheduled updates')
    parser.add_argument('--export-state', action='store_true', 
                       help='Export system state after execution')
    
    args = parser.parse_args()
    
    try:
        # Initialize system
        system = EnhancedIntradayForecastingSystem(args.location, args.model)
        
        # Print model info
        model_info = system.get_model_info()
        print(f"\n🤖 Model: {model_info['description']}")
        print(f"✨ Advantages: {', '.join(model_info['advantages'])}")
        
        if args.mode == 'single':
            # Run single forecast
            result = system.run_single_forecast()
            
            if result['status'] == 'success':
                print(f"\n✅ Forecast completed successfully in {result['execution_time']:.1f}s")
                print(f"📊 Peak production: {result['summary']['capacity_analysis']['peak_production_mw']:.3f} MW")
                print(f"⚡ Total energy: {result['summary']['energy_analysis']['total_energy_mwh']:.1f} MWh")
                
                if 'comparison' in result['summary']:
                    comp = result['summary']['comparison'].get('ml_vs_spm', {})
                    if comp:
                        print(f"\n📈 Model Comparison:")
                        print(f"   MAE: {comp['mae_mw']:.3f} MW")
                        print(f"   RMSE: {comp['rmse_mw']:.3f} MW")
                        print(f"   Correlation: {comp['correlation']:.3f}")
            else:
                print(f"\n❌ Forecast failed: {result['error']}")
                sys.exit(1)
                
        elif args.mode == 'scheduled':
            # Scheduled mode not fully implemented for comparison
            if args.model == 'comparison':
                print("⚠️  Comparison mode not recommended for scheduled updates")
                print("Consider using --model ml_physics or smart_persistence instead")
                
            print(f"\n🚀 Starting scheduled updates with {args.model} model...")
            print("Press Ctrl+C to stop...")
            
            # Implementation would follow similar pattern to original system
            
    except Exception as e:
        logger.error(f"System startup failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()