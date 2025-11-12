"""
Forecast Comparison Framework
Runs multiple forecasting models in parallel and compares their performance
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Tuple
import json
import os
import pytz
import matplotlib.pyplot as plt
from concurrent.futures import ProcessPoolExecutor, as_completed

from config import LOCATIONS
from intraday_forecast_model import IntradaySolarForecastModel
from smart_persistence_model import SmartPersistenceModel, create_spm_forecast
from intraday_weather_fetcher import IntradayWeatherFetcher

logger = logging.getLogger(__name__)


class ForecastComparison:
    """
    Compare different forecasting models for solar production
    """
    
    def __init__(self, location_key: str):
        if location_key not in LOCATIONS:
            raise ValueError(f"Unknown location: {location_key}")
        
        self.location_key = location_key
        self.location = LOCATIONS[location_key]
        self.capacity_mw = self.location['estimated_capacity_mw']
        self.timezone = pytz.timezone(self.location['timezone'])
        
        # Initialize models
        self.ml_model = IntradaySolarForecastModel(location_key, self.location)
        self.spm_model = SmartPersistenceModel(location_key, self.location)
        self.weather_fetcher = IntradayWeatherFetcher()
        
        # Results storage
        self.results = {}
        
    def run_comparison(self,
                      current_power_mw: Optional[float] = None,
                      current_timestamp: Optional[datetime] = None,
                      hours_ahead: int = 4,
                      resolution_minutes: int = 15) -> Dict[str, pd.DataFrame]:
        """
        Run all models and compare their forecasts
        
        Args:
            current_power_mw: Current measured power (if None, will simulate)
            current_timestamp: Current time (if None, uses now)
            hours_ahead: Forecast horizon
            resolution_minutes: Time resolution
            
        Returns:
            Dictionary with model names as keys and forecast DataFrames as values
        """
        if current_timestamp is None:
            current_timestamp = datetime.now(self.timezone)
        
        # Ensure timestamp is timezone aware
        if current_timestamp.tzinfo is None:
            current_timestamp = self.timezone.localize(current_timestamp)
        
        logger.info(f"Running forecast comparison for {self.location_key}")
        logger.info(f"Timestamp: {current_timestamp}")
        logger.info(f"Horizon: {hours_ahead} hours at {resolution_minutes}-minute resolution")
        
        # Fetch weather data
        start_time = current_timestamp
        end_time = current_timestamp + timedelta(hours=hours_ahead)
        
        weather_df = self.weather_fetcher.fetch_weather(
            self.location['latitude'],
            self.location['longitude'],
            start_time,
            end_time,
            self.location.get('country', 'RO')
        )
        
        # If no current power provided, estimate from weather
        if current_power_mw is None:
            current_power_mw = self._estimate_current_power(current_timestamp, weather_df)
        
        logger.info(f"Current power: {current_power_mw:.2f} MW")
        
        results = {}
        
        # 1. Run ML/Physics-based model
        try:
            logger.info("Running ML/Physics model...")
            ml_forecast = self.ml_model.predict_intraday(weather_df)
            # Align timestamps
            ml_forecast = ml_forecast[ml_forecast.index >= current_timestamp]
            results['ml_physics'] = ml_forecast
        except Exception as e:
            logger.error(f"ML/Physics model failed: {e}")
            results['ml_physics'] = None
        
        # 2. Run Smart Persistence Model
        try:
            logger.info("Running Smart Persistence Model...")
            spm_forecast = self.spm_model.forecast_intraday(
                current_power_mw=current_power_mw,
                current_timestamp=current_timestamp,
                hours_ahead=hours_ahead,
                resolution_minutes=resolution_minutes
            )
            results['smart_persistence'] = spm_forecast
        except Exception as e:
            logger.error(f"SPM failed: {e}")
            results['smart_persistence'] = None
        
        # 3. Run Standard Persistence (baseline)
        try:
            logger.info("Running Standard Persistence...")
            standard_persistence = self._run_standard_persistence(
                current_power_mw,
                current_timestamp,
                hours_ahead,
                resolution_minutes
            )
            results['standard_persistence'] = standard_persistence
        except Exception as e:
            logger.error(f"Standard persistence failed: {e}")
            results['standard_persistence'] = None
        
        self.results = results
        return results
    
    def _estimate_current_power(self, timestamp: datetime, weather_df: pd.DataFrame) -> float:
        """Estimate current power from weather conditions"""
        # Find closest weather data
        if timestamp in weather_df.index:
            weather = weather_df.loc[timestamp]
        else:
            # Find nearest timestamp
            time_diff = abs(weather_df.index - timestamp)
            nearest_idx = time_diff.argmin()
            weather = weather_df.iloc[nearest_idx]
        
        # Simple estimation
        ghi = weather.get('ghi', 0)
        if ghi > 0:
            temp_effect = 1 + (-0.004) * (weather.get('temperature', 25) - 25)
            power = self.capacity_mw * (ghi / 1000) * 0.78 * temp_effect
            return float(np.clip(power, 0, self.capacity_mw))
        else:
            return 0.0
    
    def _run_standard_persistence(self,
                                 current_power_mw: float,
                                 current_timestamp: datetime,
                                 hours_ahead: int,
                                 resolution_minutes: int) -> pd.DataFrame:
        """Simple persistence model - assumes power stays constant"""
        # Generate timestamps
        num_periods = int(hours_ahead * 60 / resolution_minutes)
        timestamps = [current_timestamp + timedelta(minutes=i * resolution_minutes) 
                     for i in range(1, num_periods + 1)]
        
        # Create forecast (constant power)
        forecast = pd.DataFrame({
            'timestamp': timestamps,
            'production_mw': current_power_mw,
            'q10': current_power_mw * 0.8,
            'q25': current_power_mw * 0.9,
            'q50': current_power_mw,
            'q75': current_power_mw * 1.1,
            'q90': current_power_mw * 1.2,
        })
        
        # Apply capacity limits
        for col in ['production_mw', 'q10', 'q25', 'q50', 'q75', 'q90']:
            forecast[col] = forecast[col].clip(0, self.capacity_mw)
        
        forecast.set_index('timestamp', inplace=True)
        
        # Add energy calculations
        resolution_hours = resolution_minutes / 60.0
        forecast['energy_mwh'] = forecast['production_mw'] * resolution_hours
        
        # Add metadata
        forecast['location'] = self.location_key
        forecast['model'] = 'standard_persistence'
        forecast['forecast_timestamp'] = current_timestamp
        
        return forecast
    
    def compare_forecasts(self, results: Optional[Dict] = None) -> pd.DataFrame:
        """
        Create comparison DataFrame with all model forecasts
        
        Args:
            results: Dictionary of model results (uses self.results if None)
            
        Returns:
            DataFrame with all forecasts aligned by timestamp
        """
        if results is None:
            results = self.results
        
        if not results:
            logger.warning("No results to compare")
            return pd.DataFrame()
        
        # Find common timestamps
        valid_results = {k: v for k, v in results.items() if v is not None}
        if not valid_results:
            return pd.DataFrame()
        
        # Get all timestamps
        all_timestamps = set()
        for df in valid_results.values():
            all_timestamps.update(df.index)
        
        common_timestamps = sorted(all_timestamps)
        
        # Create comparison DataFrame
        comparison = pd.DataFrame(index=common_timestamps)
        
        # Add each model's predictions
        for model_name, forecast_df in valid_results.items():
            if forecast_df is not None:
                comparison[f'{model_name}_mw'] = forecast_df['production_mw']
                comparison[f'{model_name}_q10'] = forecast_df['q10']
                comparison[f'{model_name}_q90'] = forecast_df['q90']
        
        return comparison
    
    def calculate_metrics(self, comparison_df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
        """
        Calculate comparison metrics between models
        
        Args:
            comparison_df: DataFrame with all model predictions
            
        Returns:
            Dictionary with metrics for each model pair
        """
        metrics = {}
        
        models = [col.replace('_mw', '') for col in comparison_df.columns if col.endswith('_mw')]
        
        # Compare each model pair
        for i, model1 in enumerate(models):
            for model2 in models[i+1:]:
                pair_key = f"{model1}_vs_{model2}"
                
                pred1 = comparison_df[f'{model1}_mw'].dropna()
                pred2 = comparison_df[f'{model2}_mw'].dropna()
                
                # Find common indices
                common_idx = pred1.index.intersection(pred2.index)
                if len(common_idx) == 0:
                    continue
                
                p1 = pred1.loc[common_idx].values
                p2 = pred2.loc[common_idx].values
                
                # Calculate metrics
                mae = np.mean(np.abs(p1 - p2))
                rmse = np.sqrt(np.mean((p1 - p2) ** 2))
                correlation = np.corrcoef(p1, p2)[0, 1] if len(p1) > 1 else np.nan
                
                metrics[pair_key] = {
                    'mae_mw': mae,
                    'rmse_mw': rmse,
                    'correlation': correlation,
                    'mean_diff_mw': np.mean(p1 - p2),
                    'max_diff_mw': np.max(np.abs(p1 - p2)),
                    'n_samples': len(common_idx)
                }
        
        return metrics
    
    def plot_comparison(self, 
                       results: Optional[Dict] = None,
                       save_path: Optional[str] = None) -> None:
        """
        Create visualization comparing all models
        
        Args:
            results: Model results dictionary
            save_path: Path to save the plot
        """
        if results is None:
            results = self.results
        
        valid_results = {k: v for k, v in results.items() if v is not None}
        if not valid_results:
            logger.warning("No valid results to plot")
            return
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
        
        colors = {
            'ml_physics': 'blue',
            'smart_persistence': 'green',
            'standard_persistence': 'red'
        }
        
        # Plot power forecasts
        for model_name, forecast_df in valid_results.items():
            color = colors.get(model_name, 'gray')
            
            # Main forecast line
            ax1.plot(forecast_df.index, forecast_df['production_mw'], 
                    label=model_name.replace('_', ' ').title(), 
                    color=color, linewidth=2)
            
            # Uncertainty bands
            ax1.fill_between(forecast_df.index, 
                           forecast_df['q10'], forecast_df['q90'],
                           alpha=0.2, color=color)
        
        ax1.set_ylabel('Power (MW)')
        ax1.set_title(f'Forecast Comparison - {self.location["name"]}')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(0, self.capacity_mw * 1.1)
        
        # Plot differences from ML/Physics model
        if 'ml_physics' in valid_results:
            ml_forecast = valid_results['ml_physics']['production_mw']
            
            for model_name, forecast_df in valid_results.items():
                if model_name != 'ml_physics':
                    # Calculate difference
                    common_idx = ml_forecast.index.intersection(forecast_df.index)
                    if len(common_idx) > 0:
                        diff = (forecast_df.loc[common_idx, 'production_mw'] - 
                               ml_forecast.loc[common_idx])
                        ax2.plot(common_idx, diff, 
                               label=f"{model_name.replace('_', ' ').title()} - ML/Physics",
                               color=colors.get(model_name, 'gray'))
        
        ax2.set_xlabel('Time')
        ax2.set_ylabel('Difference from ML/Physics (MW)')
        ax2.set_title('Model Differences')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        ax2.axhline(y=0, color='black', linestyle='--', alpha=0.5)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150)
            logger.info(f"Comparison plot saved to {save_path}")
        else:
            plt.show()
    
    def save_comparison_report(self, output_dir: str) -> str:
        """
        Save comprehensive comparison report
        
        Args:
            output_dir: Directory to save report
            
        Returns:
            Path to saved report
        """
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_path = os.path.join(output_dir, f'forecast_comparison_{self.location_key}_{timestamp}.json')
        
        # Prepare report data
        report = {
            'location': self.location_key,
            'location_name': self.location['name'],
            'capacity_mw': self.capacity_mw,
            'timestamp': datetime.now().isoformat(),
            'models_compared': list(self.results.keys()),
            'forecasts': {},
            'metrics': {}
        }
        
        # Add forecast summaries
        for model_name, forecast_df in self.results.items():
            if forecast_df is not None:
                report['forecasts'][model_name] = {
                    'start_time': forecast_df.index[0].isoformat(),
                    'end_time': forecast_df.index[-1].isoformat(),
                    'n_periods': len(forecast_df),
                    'peak_power_mw': float(forecast_df['production_mw'].max()),
                    'total_energy_mwh': float(forecast_df.get('energy_mwh', 
                                                            forecast_df['production_mw'] * 0.25).sum()),
                    'average_power_mw': float(forecast_df['production_mw'].mean())
                }
        
        # Add comparison metrics
        comparison_df = self.compare_forecasts()
        if not comparison_df.empty:
            report['metrics'] = self.calculate_metrics(comparison_df)
        
        # Save report
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Comparison report saved to {report_path}")
        return report_path


def run_model_comparison(location_key: str,
                        current_power_mw: Optional[float] = None,
                        hours_ahead: int = 4) -> Dict:
    """
    Convenience function to run model comparison
    
    Args:
        location_key: Location identifier
        current_power_mw: Current measured power (optional)
        hours_ahead: Forecast horizon
        
    Returns:
        Dictionary with results and metrics
    """
    comparison = ForecastComparison(location_key)
    
    # Run comparison
    results = comparison.run_comparison(
        current_power_mw=current_power_mw,
        hours_ahead=hours_ahead,
        resolution_minutes=15
    )
    
    # Generate comparison metrics
    comparison_df = comparison.compare_forecasts(results)
    metrics = comparison.calculate_metrics(comparison_df)
    
    # Create visualization
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'data_output', 'comparisons')
    os.makedirs(output_dir, exist_ok=True)
    
    plot_path = os.path.join(output_dir, f'comparison_{location_key}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
    comparison.plot_comparison(results, save_path=plot_path)
    
    # Save report
    report_path = comparison.save_comparison_report(output_dir)
    
    return {
        'results': results,
        'metrics': metrics,
        'plot_path': plot_path,
        'report_path': report_path
    }


if __name__ == "__main__":
    # Example comparison
    import sys
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Test location
    location_key = sys.argv[1] if len(sys.argv) > 1 else 'chisineu_cris'
    
    # Run comparison
    print(f"\nRunning forecast comparison for {LOCATIONS[location_key]['name']}...")
    
    comparison_results = run_model_comparison(
        location_key=location_key,
        current_power_mw=None,  # Will estimate from weather
        hours_ahead=4
    )
    
    # Print summary
    print("\nComparison Metrics:")
    for pair, metrics in comparison_results['metrics'].items():
        print(f"\n{pair}:")
        for metric, value in metrics.items():
            print(f"  {metric}: {value:.3f}" if isinstance(value, float) else f"  {metric}: {value}")
    
    print(f"\nPlot saved to: {comparison_results['plot_path']}")
    print(f"Report saved to: {comparison_results['report_path']}")