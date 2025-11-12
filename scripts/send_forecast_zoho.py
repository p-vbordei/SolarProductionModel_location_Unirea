#!/usr/bin/env python3
"""
Send Forecast Email with Zoho - Direct send using saved configuration
"""

import sys
import json
import os

sys.path.append(".")
from email_forecast_service import ForecastEmailService


def main():
    print("📧 Sending Solar Forecast Email via Zoho")
    print("=" * 50)

    # Hardcoded configuration
    smtp_settings = {
        "smtp_server": "smtp.zoho.eu",
        "smtp_port": 587,
        "username": "vlad@vollko.com",
        "password": "xiiesYCURsLt",
        "from_email": "solarforecastingservices@vollko.com",
        "from_name": "Solar Forecasting Services",
    }

    # Hardcoded recipient list
    recipients = [
        "bordeivlad@gmail.com",
        "vpinteay@gmail.com",
        "office@enevopower.ro",
        "alexandru.gheorghe@nepirockcastle.com",
    ]

    print(f"From: {smtp_settings['from_email']}")
    print(f"To: {', '.join(recipients)}")
    print()

    print("📧 Sending forecast email...")

    service = ForecastEmailService(smtp_config=smtp_settings)

    success = service.send_forecast_email(
        recipient_emails=recipients,
        subject="🌞 Solar Forecast Report - CRIPVSOL ENERGY SRL Unirea (2.9 MW)",
        attach_csv=False,
    )

    if success:
        print("\n🎉 EMAIL SENT SUCCESSFULLY!")
        print("✅ Excel report with both 15-min and 1-hour forecasts")
        print("✅ Professional HTML email with summary statistics")
        print("✅ Sent from Solar Forecasting Services")
        print("✅ Includes next 24h and 48h forecasts")
        print("✅ Real weather data from Open-Meteo API")
        print(f"\n📬 Check both email addresses: {', '.join(recipients)}")
    else:
        print("❌ Failed to send email")
        print("Check email configuration and network connection")


if __name__ == "__main__":
    main()
