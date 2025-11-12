#!/usr/bin/env python3
"""
Email Service for Solar Forecast Reports
Sends Excel files containing both 15-minute and 1-hour resolution forecasts

IMPORTANT: All timestamps in reports are in CET/CEST (Europe/Berlin) timezone
"""
import os
import sys
import smtplib
import pandas as pd
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import logging
from typing import List, Dict, Optional
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ForecastEmailService:
    """Service for sending forecast reports via email"""
    
    def __init__(self, smtp_config: Optional[Dict] = None):
        """
        Initialize email service
        
        Args:
            smtp_config: Dictionary with SMTP configuration
                {
                    'smtp_server': 'smtp.gmail.com',
                    'smtp_port': 587,
                    'username': 'your_email@gmail.com',
                    'password': 'your_app_password',
                    'from_email': 'your_email@gmail.com',
                    'from_name': 'Solar Forecast System'
                }
        """
        # Default configuration (can be overridden)
        self.config = smtp_config or self.load_config_from_env()
        
        # Forecast file paths - use v3 directory
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data_output', 'intraday')
        # Find the latest forecast files
        import glob
        forecast_15min_files = glob.glob(os.path.join(self.data_dir, 'cm_forecast_intraday_15min_*.csv'))
        forecast_1h_files = glob.glob(os.path.join(self.data_dir, 'cm_forecast_intraday_1hour_*.csv'))
        
        if not forecast_15min_files or not forecast_1h_files:
            raise FileNotFoundError("No forecast files found. Please run forecast generation first.")
        
        # Sort by modification time to get truly latest files
        forecast_15min_files.sort(key=lambda x: os.path.getmtime(x))
        forecast_1h_files.sort(key=lambda x: os.path.getmtime(x))
            
        self.forecast_15min = forecast_15min_files[-1]  # Latest file
        self.forecast_1h = forecast_1h_files[-1]  # Latest file
        
    def load_config_from_env(self) -> Dict:
        """Load SMTP configuration from environment variables"""
        return {
            'smtp_server': os.environ.get('SMTP_SERVER', 'smtp.gmail.com'),
            'smtp_port': int(os.environ.get('SMTP_PORT', '587')),
            'username': os.environ.get('SMTP_USERNAME', ''),
            'password': os.environ.get('SMTP_PASSWORD', ''),
            'from_email': os.environ.get('SMTP_FROM_EMAIL', ''),
            'from_name': os.environ.get('SMTP_FROM_NAME', 'Solar Forecast System')
        }
    
    def create_excel_report(self, output_path: str = None) -> str:
        """
        Create Excel file with both forecast resolutions
        
        Args:
            output_path: Path for the Excel file (optional)
            
        Returns:
            Path to the created Excel file
        """
        if output_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
            output_path = os.path.join(self.data_dir, f'solar_forecast_report_{timestamp}.xlsx')
        
        logger.info(f"Creating Excel report: {output_path}")
        
        # Load CSV files - timestamp is the last column
        df_15min = pd.read_csv(self.forecast_15min)
        df_1h = pd.read_csv(self.forecast_1h)
        
        # Set timestamp as index and parse dates
        if 'timestamp' in df_15min.columns:
            df_15min['timestamp'] = pd.to_datetime(df_15min['timestamp'])
            df_15min = df_15min.set_index('timestamp')
        
        if 'timestamp' in df_1h.columns:
            df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'])
            df_1h = df_1h.set_index('timestamp')
        
        # Standardize column names
        if 'production_kw' in df_15min.columns:
            df_15min['power_kw'] = df_15min['production_kw']
        elif 'production_mw' in df_15min.columns:
            # Legacy support - convert MW to kW
            df_15min['power_kw'] = df_15min['production_mw'] * 1000

        if 'production_kw' in df_1h.columns:
            df_1h['power_kw'] = df_1h['production_kw']
        elif 'production_mw' in df_1h.columns:
            # Legacy support - convert MW to kW
            df_1h['power_kw'] = df_1h['production_mw'] * 1000

        # Remove timezone info for Excel compatibility (if present)
        if hasattr(df_15min.index, 'tz_localize'):
            df_15min.index = df_15min.index.tz_localize(None)
        if hasattr(df_1h.index, 'tz_localize'):
            df_1h.index = df_1h.index.tz_localize(None)
        
        # Create Excel writer
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Write 15-minute data
            df_15min.to_excel(writer, sheet_name='15-Minute Forecast', freeze_panes=(1, 1))
            
            # Write 1-hour data
            df_1h.to_excel(writer, sheet_name='1-Hour Forecast', freeze_panes=(1, 1))
            
            # Create summary sheet
            summary_data = self.create_summary_data(df_15min, df_1h)
            summary_df = pd.DataFrame([summary_data])
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            # Format the Excel file (simplified for openpyxl)
            # Auto-adjust column widths
            for sheet in writer.sheets.values():
                for column_cells in sheet.columns:
                    length = max(len(str(cell.value or '')) for cell in column_cells)
                    sheet.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 50)
        
        logger.info(f"✓ Excel report created: {output_path}")
        return output_path
    
    def create_summary_data(self, df_15min: pd.DataFrame, df_1h: pd.DataFrame) -> Dict:
        """Create summary statistics for the report"""
        return {
            'Report Generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'Location': 'CRIPVSOL ENERGY SRL - Unirea (2.9 MW)',
            'Forecast Period Start': str(df_15min.index[0]),
            'Forecast Period End': str(df_15min.index[-1]),
            'Total Energy 15min (kWh)': round(df_15min['energy_kwh'].sum(), 2),
            'Total Energy 1h (kWh)': round(df_1h['energy_kwh'].sum(), 2),
            'Peak Power 15min (kW)': round(df_15min['power_kw'].max(), 1),
            'Peak Power 1h (kW)': round(df_1h['power_kw'].max(), 1),
            'Average Confidence': round(((df_15min['q25'] + df_15min['q75']) / 2).mean(), 2),
            'Data Source': 'Open-Meteo Weather Data'
        }
    
    
    def send_forecast_email(self, 
                          recipient_emails: List[str],
                          subject: str = None,
                          body: str = None,
                          attach_csv: bool = False) -> bool:
        """
        Send forecast email with Excel attachment
        
        Args:
            recipient_emails: List of recipient email addresses
            subject: Email subject (optional, auto-generated if not provided)
            body: Email body (optional, auto-generated if not provided)
            attach_csv: Whether to also attach the original CSV files
            
        Returns:
            True if email sent successfully, False otherwise
        """
        # Validate configuration
        if not self.config.get('username') or not self.config.get('password'):
            logger.error("SMTP credentials not configured. Set SMTP_USERNAME and SMTP_PASSWORD environment variables.")
            return False
        
        # Create Excel report using the corrected export script
        import subprocess
        result = subprocess.run([sys.executable, 'export_forecast_to_excel.py'], 
                              capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
        if result.returncode != 0:
            logger.error(f"Failed to create Excel report: {result.stderr}")
            return False
        
        # Find the latest Excel file
        import glob
        excel_files = glob.glob(os.path.join(self.data_dir, 'cripvsol_unirea_forecast_*.xlsx'))
        if not excel_files:
            logger.error("No Excel file found after generation")
            return False
        excel_files.sort(key=lambda x: os.path.getmtime(x))
        excel_path = excel_files[-1]

        # Generate default subject and body if not provided
        if subject is None:
            subject = f"Solar Forecast Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        if body is None:
            body = self.generate_email_body()

        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = f"{self.config['from_name']} <{self.config['from_email']}>"
            msg['To'] = ', '.join(recipient_emails)
            msg['Subject'] = subject

            # Add body
            msg.attach(MIMEText(body, 'html'))

            # Attach Excel file with date in filename
            date_str = datetime.now().strftime('%Y%m%d')
            attachment_name = f'{date_str}_CRIPVSOL_Unirea_Solar_FC.xlsx'
            self.attach_file(msg, excel_path, attachment_name)
            
            # Optionally attach CSV files
            if attach_csv:
                self.attach_file(msg, self.forecast_15min, 'forecast_15min.csv')
                self.attach_file(msg, self.forecast_1h, 'forecast_1h.csv')
            
            # Send email
            logger.info(f"Sending email to: {', '.join(recipient_emails)}")
            
            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port']) as server:
                server.starttls()
                server.login(self.config['username'], self.config['password'])
                server.send_message(msg)
            
            logger.info("✓ Email sent successfully!")
            
            # Keep the Excel file (don't delete it)
            # os.remove(excel_path)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
    
    def attach_file(self, msg: MIMEMultipart, filepath: str, filename: str):
        """Attach a file to the email message"""
        with open(filepath, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename={filename}')
            msg.attach(part)
    
    def generate_email_body(self) -> str:
        """Generate HTML email body with forecast summary"""
        # Load latest data for summary
        df_15min = pd.read_csv(self.forecast_15min)
        df_1h = pd.read_csv(self.forecast_1h)
        
        # Set timestamp as index and parse dates
        if 'timestamp' in df_15min.columns:
            df_15min['timestamp'] = pd.to_datetime(df_15min['timestamp'])
            df_15min = df_15min.set_index('timestamp')
        
        if 'timestamp' in df_1h.columns:
            df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'])
            df_1h = df_1h.set_index('timestamp')
        
        # Standardize column names and convert MW to kW
        if 'production_kw' in df_15min.columns:
            df_15min['power_kw'] = df_15min['production_kw']
        elif 'production_mw' in df_15min.columns:
            # Legacy support - convert MW to kW
            df_15min['power_kw'] = df_15min['production_mw'] * 1000
        elif 'power_mw' in df_15min.columns:
            df_15min['power_kw'] = df_15min['power_mw'] * 1000

        if 'production_kw' in df_1h.columns:
            df_1h['power_kw'] = df_1h['production_kw']
        elif 'production_mw' in df_1h.columns:
            # Legacy support - convert MW to kW
            df_1h['power_kw'] = df_1h['production_mw'] * 1000
        elif 'power_mw' in df_1h.columns:
            df_1h['power_kw'] = df_1h['power_mw'] * 1000

        # Ensure energy_kwh column exists
        if 'energy_kwh' not in df_15min.columns:
            if 'energy_mwh' in df_15min.columns:
                df_15min['energy_kwh'] = df_15min['energy_mwh'] * 1000
            else:
                # Calculate from power (15 min = 0.25 hours)
                df_15min['energy_kwh'] = df_15min['power_kw'] * 0.25

        if 'energy_kwh' not in df_1h.columns:
            if 'energy_mwh' in df_1h.columns:
                df_1h['energy_kwh'] = df_1h['energy_mwh'] * 1000
            else:
                # Calculate from power (1 hour)
                df_1h['energy_kwh'] = df_1h['power_kw'] * 1.0

        # Calculate summary statistics
        summary = self.create_summary_data(df_15min, df_1h)

        # Next 24h statistics
        next_24h_15min = df_15min.head(96)  # 96 x 15min = 24h
        next_24h_energy = next_24h_15min['energy_kwh'].sum()
        next_24h_peak = next_24h_15min['power_kw'].max()
        
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2 style="color: #4472C4;">Solar Production Forecast Report</h2>

            <h3>Location: CRIPVSOL ENERGY SRL - Unirea (2.9 MW)</h3>
            
            <div style="background-color: #f0f4f8; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h4 style="color: #4472C4; margin-top: 0;">Forecast Summary</h4>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 5px;"><strong>Report Generated:</strong></td>
                        <td style="padding: 5px;">{summary['Report Generated']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Forecast Period:</strong></td>
                        <td style="padding: 5px;">{df_15min.index[0].strftime('%Y-%m-%d %H:%M')} to {df_15min.index[-1].strftime('%Y-%m-%d %H:%M')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Timezone:</strong></td>
                        <td style="padding: 5px;"><strong>CET/CEST (Europe/Berlin)</strong></td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Data Source:</strong></td>
                        <td style="padding: 5px;">Open-Meteo Weather Forecast + ERA5 Reanalysis</td>
                    </tr>
                </table>
            </div>
            
            <div style="background-color: #e8f5e9; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h4 style="color: #2e7d32; margin-top: 0;">Next 24 Hours</h4>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 5px;"><strong>Total Energy:</strong></td>
                        <td style="padding: 5px;">{next_24h_energy:.2f} kWh</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Peak Power:</strong></td>
                        <td style="padding: 5px;">{next_24h_peak:.1f} kW</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Capacity Factor:</strong></td>
                        <td style="padding: 5px;">{(next_24h_energy / (2900 * 24) * 100):.1f}%</td>
                    </tr>
                </table>
            </div>
            
            <div style="background-color: #fff3e0; padding: 15px; border-radius: 5px; margin: 20px 0;">
                <h4 style="color: #e65100; margin-top: 0;">Full Forecast Period (48 hours)</h4>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 5px;"><strong>Total Energy (15-min):</strong></td>
                        <td style="padding: 5px;">{summary['Total Energy 15min (kWh)']} kWh</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Total Energy (1-hour):</strong></td>
                        <td style="padding: 5px;">{summary['Total Energy 1h (kWh)']} kWh</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Peak Power:</strong></td>
                        <td style="padding: 5px;">{summary['Peak Power 15min (kW)']} kW</td>
                    </tr>
                </table>
            </div>
            
            <p style="margin-top: 30px;">
                <strong>Attached Files:</strong>
                <ul>
                    <li><strong>{datetime.now().strftime('%Y%m%d')}_CRIPVSOL_Unirea_Solar_FC.xlsx</strong> - Excel workbook with both forecast resolutions</li>
                </ul>
            </p>
            
            <p style="margin-top: 30px; font-size: 12px; color: #666;">
                This forecast uses weather data from Open-Meteo including ERA5 reanalysis and GFS forecast models.
                The system provides both 15-minute and 1-hour resolution 
                forecasts with uncertainty quantiles (P10-P90) for risk management.
                <br><br>
                <strong>Important:</strong> All timestamps in this report and attached files are in CET/CEST (Central European Time).
            </p>
            
            <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
            <p style="font-size: 11px; color: #888; text-align: center;">
                Generated by Solar Forecast System | Powered by Open-Meteo Weather Data
            </p>
        </body>
        </html>
        """
        
        return html


def main():
    """Example usage of the email service"""
    
    # Example configuration (use environment variables in production)
    # For Gmail, you need to use an App Password, not your regular password
    # Go to Google Account settings > Security > 2-Step Verification > App passwords
    
    # Example 1: Using environment variables (recommended)
    # Set these in your environment:
    # export SMTP_USERNAME="your_email@gmail.com"
    # export SMTP_PASSWORD="your_app_password"
    # export SMTP_FROM_EMAIL="your_email@gmail.com"
    
    service = ForecastEmailService()
    
    # Example 2: Using explicit configuration
    # config = {
    #     'smtp_server': 'smtp.gmail.com',
    #     'smtp_port': 587,
    #     'username': 'your_email@gmail.com',
    #     'password': 'your_app_password',
    #     'from_email': 'your_email@gmail.com',
    #     'from_name': 'Solar Forecast System'
    # }
    # service = ForecastEmailService(smtp_config=config)
    
    # Send email
    recipients = ['recipient@example.com']  # Replace with actual recipient
    
    # Simple send with defaults
    # success = service.send_forecast_email(recipients)
    
    # Custom send with all options
    # success = service.send_forecast_email(
    #     recipient_emails=recipients,
    #     subject="Solar Forecast - CRIPVSOL ENERGY SRL Unirea",
    #     body=None,  # Use auto-generated body
    #     attach_csv=True  # Also attach original CSV files
    # )
    
    # Just create Excel without sending (for testing)
    excel_path = service.create_excel_report()
    logger.info(f"Excel report created at: {excel_path}")
    logger.info("\nTo send emails, configure SMTP settings and uncomment the send_forecast_email call above.")


if __name__ == "__main__":
    main()