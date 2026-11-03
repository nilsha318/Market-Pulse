# Data dictionary: SuperMarket Analysis.csv

One row represents one supermarket invoice/transaction. The local file has 1,000
rows, 1,000 distinct Invoice IDs, and no blank fields in the profile run. Dates
span 2019-01-01 through 2019-03-30. Numeric summaries and categories below were
profiled from the included file; source meaning should be checked against the
dataset's original publication before business use.

| CSV column | SQLite column | Type | Meaning / observed values |
|---|---|---|---|
| Invoice ID | `invoice_id` | text | Invoice identifier; unique in this file. |
| Branch | `branch` | text | `Alex`, `Cairo`, `Giza`. |
| City | `city` | text | `Yangon`, `Naypyitaw`, `Mandalay`. |
| Customer type | `customer_type` | text | `Member`, `Normal`; not a unique customer identifier. |
| Gender | `gender` | text | `Female`, `Male`. |
| Product line | `product_line` | text | Electronic accessories; Fashion accessories; Food and beverages; Health and beauty; Home and lifestyle; Sports and travel. |
| Unit price | `unit_price` | decimal text | Observed range 10.08–99.96. |
| Quantity | `quantity` | integer text | Observed range 1–10. |
| Tax 5% | `tax_5_percent` | decimal text | Tax amount recorded on the transaction. |
| Sales | `sales` | decimal text | Transaction sales value; observed total 322,966.749. Currency is not specified in this local file. |
| Date | `date` | text (M/D/YYYY) | Transaction date. |
| Time | `time` | text | Transaction time in 12-hour format. |
| Payment | `payment` | text | `Cash`, `Credit card`, `Ewallet`. |
| cogs | `cogs` | decimal text | Cost of goods sold recorded by the source. |
| gross margin percentage | `gross_margin_percentage` | decimal text | Observed constant 4.761904762; definition should be verified from the source. |
| gross income | `gross_income` | decimal text | Gross income amount; observed total 15,379.369. |
| Rating | `rating` | decimal text | Customer rating; observed range 4.0–10.0. |

Numeric values are stored as text in SQLite to preserve source data exactly. KPI
code parses them as numbers. The dataset contains no personal customer ID, so
the role dashboard scopes a customer login to admin-assigned Invoice IDs; it
cannot identify a person or infer customer purchase history across invoices.

The project uses the source field names in `data/SuperMarket Analysis.csv` and
snake_case names in SQLite. The original 2019 sample is historical; the offers
in `data/offers.csv` are synthetic examples, not offers found in the sales data.
