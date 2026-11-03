# Market Pulse

No/Low Code and AI-Assisted Development, Hochschule Kufstein Tirol. Synthetic
data only. This folder is a self-contained project; run its Python commands
from this directory.

## Quick start: local dashboard

In PowerShell, from the repository root:

```powershell
Set-Location .\projects\market-pulse
$env:MARKET_PULSE_DB = "sqlite"
python -m src.database
python -m src.dashboard --create-admin
python -m src.dashboard
```

Create the admin account when prompted, then open <http://127.0.0.1:8000>.
Leave the terminal running while you use the dashboard. Press **Ctrl+C** to stop
it. The database is saved locally at `data/orders.sqlite3`.

## Public internet deployment (Render)

`render.yaml` defines a free Render web service. For persistent database storage
without paying, connect it to a free PostgreSQL project on Neon. Render provides
the public HTTPS address. The app uses PostgreSQL rather than its local SQLite
file, and imports the synthetic sales CSV when the service first starts.

Free hosting has limits: Render sleeps after 15 minutes without traffic and can
take about a minute to wake for the next visitor. Render's free service also has
an ephemeral filesystem, so the database must stay on Neon rather than SQLite.
Neon's current free plan includes 1 GB storage and 100 compute-hours per project
per month; its database compute scales to zero when idle. Check the providers'
[Render free-plan limits](https://render.com/docs/free) and
[Neon free-plan details](https://neon.com/blog/neon-free-plan-1-gb-per-project).

To deploy:

1. Create a free PostgreSQL project on Neon and copy its connection string.
2. Put this project in a GitLab repository you can connect to Render.
3. In Render, create a Blueprint from that repository and set its Blueprint path
   to `projects/market-pulse/render.yaml` if using the course collection repo.
4. When prompted, enter the Neon connection string, a 3–40 character admin
   username, and a 10–256 character admin password.

The Blueprint creates the initial admin account on first start. Remove the two
`MARKET_PULSE_INITIAL_ADMIN_*` environment variables from the Render service
after the account is created. Stay on the free plans at both providers; applying
this configuration does not create a paid web service or database.

The existing local SQLite users and offers are not copied to the hosted
database. The hosted app starts with the synthetic sales data and the new admin
account; create employee and customer accounts there from the admin dashboard.

To use the existing PostgreSQL setup instead, follow
[`sql/pgadmin/README.md`](sql/pgadmin/README.md) and run the app with
`MARKET_PULSE_DB=postgres`.

## Project contents

## Part A: AI coding agent and skill

- `AGENTS.md`: project rules for the agent
- `.claude/settings.json`: permissions for Claude Code
- `data/SuperMarket Analysis.csv`: 1,000 synthetic supermarket transactions
- `docs/data-dictionary.md`: what each column should contain
- `src/kpis.py`: KPI calculations (run: `python -m src.kpis`)
- `src/database.py`: local SQLite database setup and CSV import
- `.agents/skills/data-quality-check/`: data quality review guidance
- `.agents/data-profiling/` and `.agents/offer-campaign-workflow/`: companion workflow guidance

The dashboard and KPI module default to the PostgreSQL `market_pulse` database.
For the simpler local setup above, select SQLite with `MARKET_PULSE_DB=sqlite`.
Import or refresh its sales table with `python -m src.database` or
`python -m src.database --replace`. The old `orders` table is left in place for
reference.
The source is synthetic and historical (2019); KPI values use its `Sales` and
`gross income` fields. The file does not specify a currency, so reports label
amounts as dataset units.

## Role-based dashboard

The local dashboard provides separate Admin, Customer, Guest, and Employee
views with role-specific navigation. Admins manage accounts, offers, and
coupons. Customers see only linked Invoice IDs and can use Offer Zone, Cart,
coupon entry, and checkout preview. Guests see aggregate figures and offers.
Employees receive department-scoped access; the Finance dashboard requires an
employee assigned to Finance with the exact job title `Accountant`. The sample
dataset has no individual customer ID, so admins assign Invoice IDs to
customer accounts.

Create the first Admin account interactively (the password is hashed in
SQLite; no default credentials are included):

```bash
python -m src.dashboard --create-admin
```

Then start the dashboard and open <http://127.0.0.1:8000>:

```bash
python -m src.dashboard
```

The server binds to the local machine by default. Admins can create customer
accounts and link or update comma-separated Invoice IDs. Dashboard metrics are
distinct invoices, sales, gross income, quantity sold, average rating, and sales
by product line. Amounts are shown in dataset units; the source file does not
state a currency.

The dashboard also includes an **Offer Zone** at `/offers`. It displays six
synthetic product-line promotions based on the dataset categories. These are
illustrative offers, not products or prices present in the historical data.
Admins can publish further offers by product line and branch. Customer offer
views include their linked branches. Customers can add active offers to their
account cart and update quantities. Guests can browse and build a temporary
cart. Admins can create percentage coupon codes with validity dates; customers
can apply them at `/checkout` to see a discounted total preview. No payment
details are collected, and payment processing or order placement is not enabled.

For PostgreSQL setup in pgAdmin, see [`sql/pgadmin/README.md`](sql/pgadmin/README.md).
The PostgreSQL connection uses `PGHOST=localhost`, `PGPORT=5432`,
`PGDATABASE=market_pulse`, and `PGUSER=postgres` by default, matching the saved
pgAdmin server `Nilsha`. When no `PGPASSWORD` is set, the app asks for the
password privately in the terminal. Keep it out of source files. Set the
`PGHOST`, `PGPORT`, `PGDATABASE`, or `PGUSER` environment variables if the
server's Connection properties show different values. Use
`MARKET_PULSE_DB=sqlite` to select the local SQLite database instead.

## Part B: n8n

```bash
cd n8n
docker compose up -d      # start n8n, then open http://localhost:5678
docker compose down       # stop n8n
```

The `data/` folder is mounted read-only in n8n as `/home/node/.n8n-files/`, so
the source transaction file is available there as
`/home/node/.n8n-files/SuperMarket Analysis.csv`.
