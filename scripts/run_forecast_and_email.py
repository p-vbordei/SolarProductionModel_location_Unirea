#!/usr/bin/env python3
"""
Simple wrapper script to run the 3-step email workflow.
Only calls the three required scripts in sequence.
"""

import subprocess
import sys

# Step 1: Generate forecast
print("[1/3] Generating forecast...")
if subprocess.call([sys.executable, "scripts/run_intraday_cm.py"]) != 0:
    print("Forecast generation failed!")
    sys.exit(1)

# Step 2: Export to Excel
print("\n[2/3] Creating Excel report...")
if subprocess.call([sys.executable, "scripts/export_forecast_to_excel.py"]) != 0:
    print("Excel export failed!")
    sys.exit(1)

# Step 3: Send email
print("\n[3/3] Sending email...")
if subprocess.call([sys.executable, "scripts/send_forecast_zoho.py"]) != 0:
    print("Email sending failed!")
    sys.exit(1)

print("\nWorkflow completed successfully!")