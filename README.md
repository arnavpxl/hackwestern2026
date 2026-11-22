# hackwestern2026

## Local encryption key

Provider credentials are encrypted before they are stored. `make up` and `make demo`
automatically generate a `TTU_ENCRYPTION_KEY` in the gitignored root `.env` file when one
does not already exist. Keep that value stable: changing it makes previously stored provider
credentials unreadable.
