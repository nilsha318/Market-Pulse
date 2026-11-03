# Create the PostgreSQL database in pgAdmin

These scripts create the PostgreSQL schema for the supermarket transaction
dataset. The Python dashboard can use this database when configured with
`MARKET_PULSE_DB=postgres` as described in the project README.

## Create and load the database

1. In pgAdmin, connect to your PostgreSQL server.
2. Open Query Tool connected to the default `postgres` database and run
   [`01_create_database.sql`](01_create_database.sql). If `market_pulse` already
   exists, skip the `CREATE DATABASE` statement.
3. Refresh the server tree, select `market_pulse`, open its Query Tool, and run
   [`02_schema.sql`](02_schema.sql).
4. Import the synthetic CSV files into matching tables:
   - Right-click `public.sales` → **Import/Export Data** → **Import**. Choose
     `data/SuperMarket Analysis.csv`, format CSV, enable **Header**, encoding
     UTF8. Map the 17 source columns in their original order to `invoice_id`,
     `branch`, `city`, `customer_type`, `gender`, `product_line`, `unit_price`,
     `quantity`, `tax_5_percent`, `sales`, `date`, `time`, `payment`, `cogs`,
     `gross_margin_percentage`, `gross_income`, and `rating`. Leave
     `source_row` out so PostgreSQL generates it.
   - Right-click `public.offers` and import `data/offers.csv` with Header enabled.
     Map all eight CSV fields, leaving `offer_id` and `created_at` out.
5. Inspect the imports:

   ```sql
   SELECT count(*), count(DISTINCT invoice_id) FROM sales;
   SELECT product_line, count(*), sum(sales::numeric)
   FROM sales GROUP BY product_line ORDER BY product_line;
   SELECT * FROM offers ORDER BY offer_id;
   ```

The included source has 1,000 unique Invoice IDs. Currency is not specified in
the local CSV, so numeric amounts are kept in dataset units. Text storage for
sales fields preserves the source values as imported. No accounts or passwords
are seeded. If an older `orders` table exists, it is left untouched and is not
used by the updated dashboard.
