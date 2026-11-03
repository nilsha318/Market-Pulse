"""KPI calculations for the supermarket sales dataset."""

from contextlib import closing
from pathlib import Path

from src.database import CSV_PATH, DATABASE_PATH, connect, initialize, is_postgres


def load(path: Path = DATABASE_PATH) -> list[dict]:
    """Load sales rows from SQLite; also accept a CSV path for inspection."""
    if path.suffix.lower() == ".csv":
        import csv
        with path.open(newline="", encoding="utf-8-sig") as file:
            raw_rows = list(csv.DictReader(file))
        from src.database import SALES_COLUMNS
        return [{key: row.get(source, "") for key, source in SALES_COLUMNS.items()}
                for row in raw_rows]

    if is_postgres(path):
        initialize(CSV_PATH, path)
    elif not path.exists():
        initialize(CSV_PATH, path)
    else:
        with closing(connect(path)) as connection:
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sales'"
            ).fetchone()
        if not table_exists:
            initialize(CSV_PATH, path)

    with closing(connect(path)) as connection:
        return [dict(row) for row in connection.execute(
            """SELECT invoice_id, branch, city, customer_type, gender, product_line,
                      unit_price, quantity, tax_5_percent, sales, date, time, payment,
                      cogs, gross_margin_percentage, gross_income, rating
               FROM sales ORDER BY source_row"""
        )]


def value(row: dict, column: str) -> float:
    return float(row[column])


def sales_total(rows: list[dict]) -> float:
    """Sum the dataset's Sales field; its currency is not specified locally."""
    return sum(value(row, "sales") for row in rows)


def invoice_count(rows: list[dict]) -> int:
    """Count distinct Invoice IDs."""
    return len({row["invoice_id"] for row in rows if row["invoice_id"]})


def average_invoice_value(rows: list[dict]) -> float:
    count = invoice_count(rows)
    return sales_total(rows) / count if count else 0.0


def quantity_sold(rows: list[dict]) -> int:
    return sum(int(row["quantity"]) for row in rows)


def gross_income(rows: list[dict]) -> float:
    return sum(value(row, "gross_income") for row in rows)


def average_rating(rows: list[dict]) -> float:
    ratings = [value(row, "rating") for row in rows if row.get("rating")]
    return sum(ratings) / len(ratings) if ratings else 0.0


if __name__ == "__main__":
    rows = load()
    print(f"Sales total:          {sales_total(rows):12,.2f} dataset units")
    print(f"Distinct invoices:    {invoice_count(rows):12,d}")
    print(f"Average invoice:      {average_invoice_value(rows):12,.2f} dataset units")
    print(f"Quantity sold:        {quantity_sold(rows):12,d}")
    print(f"Gross income:         {gross_income(rows):12,.2f} dataset units")
    print(f"Average rating:       {average_rating(rows):12.2f} / 10")
