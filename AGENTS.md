# Project rules

- Read the relevant files before you propose changes.
- Name open questions about KPI definitions. Do not guess.
- Work on one limited task at a time.
- Never change expected values in tests just to make a test pass.
- Check KPIs with `python -m src.kpis`. Say which checks you did not run.
- Use only the synthetic (generated, not real) data in `data/`.
- Never read `.env`. Never write passwords or API keys into code.

## Business rules

- One sales row is one supermarket invoice transaction.
- Use `Invoice ID` as the transaction key and count each invoice once.
- `Sales` and `gross income` are source measures. Their currency is not specified
  in the local dataset, so label totals as dataset units rather than assuming a
  currency.
- `Customer type` is a membership category, not an individual customer ID.
- The sales sample has no product catalog; offer examples are synthetic and
  should be categorized by `Product line`.
