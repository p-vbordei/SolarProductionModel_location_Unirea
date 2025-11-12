"""
Quick launcher for CM intraday forecasting system

IMPORTANT: All forecast outputs are in CET/CEST (Europe/Berlin) timezone
- CSV files show local CET/CEST timestamps
- Trading format uses CET/CEST delivery times
- API responses include timezone metadata
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from intraday_system_with_spm import EnhancedIntradayForecastingSystem
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    """Run single intraday forecast for CM location"""
    try:
        print("🚀 Starting CRIPVSOL ENERGY SRL - Unirea Intraday Solar Forecast")
        print("📍 Location: 45.1116, 27.7846 (2.9 MW)")
        print("⏱️  Resolution: 15 minutes, Horizon: 7 days")
        print("="*60)
        
        # Initialize and run with enhanced system that exports weather parameters
        system = EnhancedIntradayForecastingSystem('cm_forecast', 'ml_physics')
        result = system.run_single_forecast()
        
        if result['status'] == 'success':
            print("\n✅ SUCCESS - Intraday forecast completed!")
            print(f"⚡ Peak Production: {result['summary']['capacity_analysis']['peak_production_mw']:.3f} MW")
            print(f"🔋 Total Energy (7d): {result['summary']['energy_analysis']['total_energy_mwh']:.1f} MWh")
            print(f"📊 Capacity Factor: {result['summary']['capacity_analysis']['capacity_factor']:.1%}")
            print(f"⚠️  Forecast Uncertainty: {result['summary']['uncertainty_analysis']['relative_uncertainty_pct']:.1f}%")
            print(f"🕒 Execution Time: {result['execution_time']:.1f} seconds")
            print(f"\n📁 Files created: {len(result['files_created'])}")
            
            # Show file locations
            print("\n📋 Output Files:")
            for file_path in result['files_created']:
                filename = os.path.basename(file_path)
                print(f"   • {filename}")
            
            # Export system state
            state_file = system.export_current_state()
            print(f"\n💾 System state: {os.path.basename(state_file)}")
            
        else:
            print(f"\n❌ FAILED - {result['error']}")
            return 1
            
    except Exception as e:
        print(f"\n💥 SYSTEM ERROR - {str(e)}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)