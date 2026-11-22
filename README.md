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
