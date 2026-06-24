# PostgreSQL ML Runbook

This project can run the same ML pipeline against PostgreSQL/Supabase instead of local SQLite.

## 1. Set the connection string

Use `DATABASE_URL` with a PostgreSQL connection string.

Example:

```bash
export DATABASE_URL='postgresql://postgres:<PASSWORD>@db.<PROJECT>.supabase.co:5432/postgres?sslmode=require'
```

Notes:

- The Python scripts use `DATABASE_URL`.
- A Supabase anon/service key is not used by these SQLAlchemy scripts.
- If Supabase gave you a full connection string already, use that directly.

## 2. Initialize the PostgreSQL schema

```bash
PYTHONPATH=src .venv/bin/python scripts/init_db.py
```

## 3. Optional: copy your local SQLite data into PostgreSQL

If you want to test the remote pipeline with the same local data first:

```bash
PYTHONPATH=src .venv/bin/python scripts/migrate_sqlite_to_postgres.py
```

## 4. Build and test the ML pipeline against PostgreSQL

```bash
PYTHONPATH=src .venv/bin/python scripts/run_postgres_ml_test.py
```

This writes:

- `data/ml/postgres_test/hanoi_real_estate_ml_base.csv`
- `data/ml/postgres_test/hanoi_real_estate_ml_accessibility.csv`
- `data/ml/postgres_test/model/metrics.csv`
- `data/ml/postgres_test/model/xgboost_price_per_m2_pipeline.joblib`

## 5. Export the PostgreSQL-trained model for Streamlit

```bash
PYTHONPATH=src .venv/bin/python scripts/export_streamlit_model.py \
  --source data/ml/postgres_test/model/xgboost_price_per_m2_pipeline.joblib \
  --output models/xgboost_price_per_m2_pipeline.joblib
```

## 6. Run the dashboard against PostgreSQL

```bash
DATABASE_URL="$DATABASE_URL" PYTHONPATH=src .venv/bin/python -m streamlit run src/hanoi_real_estate/dashboard/app.py
```

## 7. What to verify

After the app opens:

- the predictor form shows `Property type`
- selecting `Đất` disables house-only inputs
- predictions still run successfully
- the dashboard loads rows from PostgreSQL instead of local SQLite
