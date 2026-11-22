# Token Up

![Token Up](frontend/public/tokentrueup-logo.svg)

**Catch runaway AI agents before they become runaway AI bills.**

Token Up monitors AI-provider usage, estimates spend, detects abnormal run rates, and turns incidents into auditable cases for finance and engineering teams. It combines a fast synthetic product demo with an isolated authenticated workspace for real OpenAI and Anthropic usage.

## Why Token Up

AI workloads can move from normal to expensive in seconds. Provider dashboards often report usage after the fact, and the people responsible for finance, infrastructure, and individual API keys rarely share the same context.

Token Up brings that context together:

- Spend monitoring with minute, hourly, and daily views
- Runaway-agent detection against historical baselines
- Large in-app warnings and transactional email alerts
- Cases containing the affected key, model, baseline, run rate, and evidence
- API-key ownership and team mapping
- Month-end accrual and approval workflows
- Provider-invoice reconciliation and duplicate detection
- Authenticated imports from OpenAI and Anthropic

## Product modes

Token Up deliberately separates simulated and real provider data.

| Mode | Route | Purpose |
| --- | --- | --- |
| Synthetic demo | `/demo` | Demonstrates minute-level monitoring, runaway detection, close, and reconciliation without using real credentials or spend. |
| Connected workspace | `/app` | Imports usage belonging to the signed-in user's provider connections and displays real hourly analytics. |

The connected workspace never reads simulator tables, and the demo clearly labels all providers, keys, invoices, and spending as synthetic.

## Runaway-agent demo

1. Open `/demo` and reset the baseline if needed.
2. Select **Runaway agent** from the scenario menu.
3. The simulator automatically resumes and increases traffic for the support-triage agent.
4. TimescaleDB evaluates the real-time tail against the historical baseline.
5. After the graph begins to move, Token Up displays a runaway-spend warning.
6. If a real account is signed in and email is configured, the same case produces an email alert.
7. Open the case to inspect its financial impact, evidence, and audit trail.

Detection is recorded immediately for accurate latency metrics. The popup and email intentionally wait five seconds so the change is visible on the chart before the alert arrives.

## Architecture

| Layer | Technology | Responsibility |
| --- | --- | --- |
| Web application | Next.js 15, React 19, TypeScript, Tailwind CSS, Recharts | Dashboard, demo controls, cases, connections, and authentication UI |
| API | FastAPI, Pydantic, psycopg | Authentication, provider connections, analytics, simulator controls, and server-sent events |
| Data platform | PostgreSQL and TimescaleDB | Raw usage, continuous aggregates, baselines, anomaly jobs, cases, and notification queues |
| Security | AES-256-GCM and server-side sessions | Provider-key encryption, write-only credential handling, and role-based access |
| Integrations | OpenAI, Anthropic, Postmark | Provider usage imports and transactional email delivery |

Synthetic events are aggregated into minute, hourly, and daily views. A hybrid detector combines the historical aggregate baseline with a short raw-event window, allowing a spike to be detected before the current minute has finished materializing.

The database opens an anomaly case and publishes an event. The API relays that event to the browser over server-sent events, while a durable, deduplicated queue handles email separately so SMTP latency cannot slow detection.

## Local setup

### Prerequisites

- Docker with Docker Compose
- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- Node.js and npm
- GNU Make

### Start the project

Clone the repository and create the local environment file:

```bash
cp .env.example .env
```

Prepare TimescaleDB, the Python environment, migrations, seed data, and historical usage:

```bash
make up
```

The initial backfill creates 20 million usage events and can take a few minutes. Subsequent runs reuse the existing database.

Start the API:

```bash
make demo
```

In another terminal, start the frontend:

```bash
make web
```

Open [http://localhost:3000](http://localhost:3000).

Useful commands:

```bash
make test          # backend test suite
make lint          # Python lint checks
make bench         # database and detector benchmarks
make psql          # PostgreSQL shell
make down          # stop TimescaleDB
make down-volumes  # remove local database data and start fresh
```

## Accounts and provider connections

The public demo silently creates an internal `demo@tokentrueup.local` session. This account can control the simulation but cannot enter the connected workspace or receive email.

Create a real account through `/signup`, then open **Connections** to add OpenAI or Anthropic credentials. Provider credentials are write-only: the browser can submit them, but API responses never return them.

Anthropic usage and cost imports require an Admin API key beginning with:

```text
sk-ant-admin...
```

The authenticated dashboard displays the hourly resolution supplied by provider reporting APIs rather than presenting synthetic minute-level precision. Spend is estimated using effective public list prices. Unknown models are reported as unpriced and excluded from dollar totals.

## Credential encryption

Provider credentials are encrypted at rest with AES-256-GCM. `make up` and `make demo` generate a master key in the gitignored root `.env` if it is missing:

```dotenv
TTU_ENCRYPTION_KEY=BASE64_ENCODED_32_BYTE_KEY
```

You can generate one manually:

```bash
openssl rand -base64 32
```

Keep this value stable. Changing it does not re-encrypt existing provider credentials; it makes their ciphertext unreadable. After rotating the master key, restart the API and rotate each stored provider credential with its real provider key, or revoke and recreate the connections.

## Demo email alerts

A real signed-in user who triggers the runaway scenario is automatically enrolled for that incident. The recipient always comes from the authenticated user record, never from browser input. The public demo account is excluded, and a database constraint prevents duplicate emails for the same user and case.

Configure Postmark in the root `.env`:

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

Restart the API after changing email settings. The sender address or domain must be verified in Postmark. While a Postmark account is pending approval, its recipient domain must match the sender domain.

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `DATABASE_URL` | Yes | PostgreSQL/TimescaleDB connection string |
| `TTU_ENCRYPTION_KEY` | Yes for provider connections | Stable Base64-encoded 32-byte master key |
| `ANTHROPIC_API_KEY` | No | Enables live Anthropic-powered explanation agents; deterministic fallbacks are used otherwise |
| `ANTHROPIC_MODEL` | No | Model used by live explanation agents |
| `TTU_SMTP_*` | No | Postmark/SMTP configuration for demo email alerts |
| `TTU_APP_URL` | No | Base URL used in links inside alert emails |
| `TTU_COOKIE_SECURE` | Production only | Enables secure cookies when the app is served over HTTPS |

See [`.env.example`](.env.example) for the complete local template.

## Testing

The backend suite covers:

- Authentication and session lifecycle
- Provider-credential encryption and connection management
- Usage ingestion and account isolation
- Continuous aggregates and late-arriving data
- Spend estimation and pricing changes
- Raw-tail anomaly detection and bounded spike attribution
- Simulation controls and baseline generation
- Email enrollment, deduplication, delay, and delivery state

Run the suite with:

```bash
make test
```

Validate the production frontend build with:

```bash
cd frontend
npm run build
```

## Troubleshooting

### `stored key failed authentication`

The stored provider credential was encrypted with a different `TTU_ENCRYPTION_KEY`. Restore the original master key, or keep the new key and rotate/recreate each provider connection. Creating another user account does not repair the ciphertext.

### The runaway scenario does not produce an alert

Reset the baseline and trigger the scenario again. The runaway action automatically resumes a paused simulation. An existing recent anomaly may be deduplicated until the demo is reset.

### Postmark accepts SMTP but no email arrives

Check the server's Postmark Activity page, sender verification, recipient suppression, and account approval. Pending Postmark accounts may only send to a recipient sharing the sender's domain.

### Connected analytics are hourly

This is intentional. Provider reporting APIs expose hourly usage, while the synthetic demo owns the high-frequency event stream required for minute-level visualization and rapid anomaly demonstrations.

## What's next

- Real-data anomaly detection as provider reports become available
- Streaming and webhook ingestion for lower-latency providers
- User-configurable budgets and thresholds
- Slack, Microsoft Teams, and PagerDuty notifications
- More AI and cloud providers
- Automated owner outreach and cost allocation
- Invoice ingestion from accounting platforms
- Postmark delivery webhooks
- Organization workspaces and team invitations

Token Up's long-term goal is to become the financial control plane for AI usage: detect problems early, explain their impact, and carry them through reconciliation and close.
