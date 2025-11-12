# GitHub Actions Solar Forecast Workflow

This directory contains the GitHub Actions workflow for automated daily solar forecasting.

## Overview

The workflow runs daily at **10:01 EET/EEST** (Romanian time) and:
1. Generates solar forecasts using real weather data
2. Creates Excel reports with 15-minute and 1-hour resolutions
3. Sends email reports to configured recipients

## Setup Instructions

### 1. Configure GitHub Secret

You must add your email configuration as a GitHub Secret:

1. Go to your repository on GitHub
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Create a secret named `EMAIL_CONFIG` with the following JSON content:

```json
{
    "smtp_settings": {
        "smtp_server": "smtp.zoho.eu",
        "smtp_port": 587,
        "username": "your-username@vollko.com",
        "password": "your-password",
        "from_email": "solarforecastingservices@vollko.com",
        "from_name": "Solar Forecasting Services"
    },
    "recipients": {
        "daily_report": [
            "recipient1@example.com",
            "recipient2@example.com"
        ],
        "alerts": [
            "alert-recipient@example.com"
        ]
    },
    "schedule": {
        "daily_report_time": "08:00",
        "enable_daily_report": true,
        "enable_alerts": true
    }
}
```

⚠️ **Important**: Never commit email credentials to the repository!

### 2. Enable GitHub Actions

GitHub Actions should be enabled by default. If not:
1. Go to **Settings** → **Actions** → **General**
2. Select **Allow all actions and reusable workflows**
3. Click **Save**

## How It Works

### Timezone Handling

The workflow handles Romanian timezone (EET/EEST) automatically:
- **Winter (EET)**: UTC+2 (November - March)
- **Summer (EEST)**: UTC+3 (March - October)

The workflow has two cron schedules:
- `1 7 * * *` - Runs at 07:01 UTC (10:01 EEST in summer)
- `1 8 * * *` - Runs at 08:01 UTC (10:01 EET in winter)

A timezone check ensures only one execution happens at 10:01 local time.

### Execution Flow

1. **Timezone Check**: Verifies it's 10:01 in Bucharest
2. **Setup**: Installs Python 3.11 and uv package manager
3. **Dependencies**: Caches and installs Python packages
4. **Configuration**: Creates email config from GitHub Secret
5. **Forecast**: Runs the three-step workflow:
   - `run_intraday_cm.py` - Generate forecast
   - `export_forecast_to_excel.py` - Create Excel report
   - `send_forecast_zoho.py` - Send email
6. **Artifacts**: Uploads forecast files for 30-day retention
7. **Cleanup**: Removes sensitive configuration files

## Manual Testing

To test the workflow manually:

1. Go to **Actions** tab in your repository
2. Select **Daily Solar Forecast** workflow
3. Click **Run workflow**
4. Options:
   - Leave defaults to respect timezone check
   - Check **Skip timezone check** to force execution
5. Click **Run workflow** button

## Monitoring

### View Execution History
- Go to **Actions** tab to see all workflow runs
- Click on any run to see detailed logs
- Green checkmark = success, Red X = failure

### Download Artifacts
Successful runs save forecast files as artifacts:
- Click on a successful workflow run
- Scroll to **Artifacts** section
- Download `forecast-{number}` to get:
  - Latest CSV files
  - Excel reports
  - System state JSON

### Failure Notifications
If the workflow fails:
- GitHub sends email to repository watchers
- Check logs for error details
- Common issues:
  - Missing EMAIL_CONFIG secret
  - Weather API timeout
  - Email server connection issues

## Troubleshooting

### Workflow Not Running
1. Check GitHub Actions is enabled
2. Verify cron syntax is correct
3. Check for timezone calculation issues

### Email Not Sending
1. Verify EMAIL_CONFIG secret is set correctly
2. Check SMTP credentials are valid
3. Review email server logs in workflow

### Forecast Generation Fails
1. Check weather API is accessible
2. Verify all Python dependencies installed
3. Look for error messages in logs

### Manual Override
If automated runs fail, you can run manually:
```bash
# Clone repository
git clone https://github.com/your-username/SolarProductionModel_v3.git
cd SolarProductionModel_v3

# Install dependencies
pip install uv
uv sync

# Run forecast
uv run python scripts/run_forecast_and_email.py
```

## Cost

This workflow is **FREE** under GitHub's pricing:
- Private repositories: 2,000 minutes/month free
- This workflow uses ~5 minutes/day = 150 minutes/month
- Well within free tier limits

## Security Notes

- Email credentials stored as encrypted GitHub Secrets
- Configuration file created only during runtime
- Automatic cleanup after each execution
- No sensitive data in logs or artifacts

## Support

For issues or questions:
1. Check workflow logs for error details
2. Review this documentation
3. Create an issue in the repository