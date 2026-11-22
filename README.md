# hackwestern2026

## Local encryption key

Provider credentials are encrypted before they are stored. `make up` and `make demo`
automatically generate a `TTU_ENCRYPTION_KEY` in the gitignored root `.env` file when one
does not already exist. Keep that value stable: changing it makes previously stored provider
credentials unreadable.

## Connected analytics

The authenticated dashboard at `/app` reads only `provider_usage_hourly` rows belonging to
connections created by the signed-in user. It does not query the simulator tables. OpenAI and
Anthropic usage APIs provide hourly token counts, so this view intentionally uses hourly charts
rather than presenting synthetic minute-level precision.

Spend is an estimate based on the effective public list-price rows in
`provider_model_prices`. Models without a matching price are excluded from dollar totals and
shown as unpriced in the UI; unmapped provider usage is included under `Unmapped` without
returning the provider's key identifier to the browser.

## Demo email alerts

When SMTP is configured, a real signed-in user who starts the demo's runaway-agent scenario is
automatically emailed when its anomaly case opens. The public `demo@tokentrueup.local` session is
never emailed. Delivery is queued and deduplicated in Postgres, so SMTP does not delay detection.

Set these values in the gitignored root `.env` file:

```dotenv
TTU_SMTP_HOST=smtp.postmarkapp.com
TTU_SMTP_PORT=587
TTU_SMTP_USERNAME=YOUR_POSTMARK_SERVER_TOKEN
TTU_SMTP_PASSWORD=YOUR_POSTMARK_SERVER_TOKEN
TTU_SMTP_FROM="Token Up Alerts <your-verified-sender@example.com>"
TTU_SMTP_MESSAGE_STREAM=outbound
TTU_SMTP_STARTTLS=true
TTU_SMTP_SSL=false
TTU_APP_URL=http://localhost:3000
```

Use port 587 with STARTTLS, or port 465 with `TTU_SMTP_SSL=true` and
`TTU_SMTP_STARTTLS=false`. Restart the API after changing these settings.
