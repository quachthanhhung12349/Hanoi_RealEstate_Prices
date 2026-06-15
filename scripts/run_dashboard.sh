#!/usr/bin/env sh
set -eu

export PYTHONPATH="${PYTHONPATH:-src}"
exec python -m streamlit run src/hanoi_real_estate/dashboard/app.py
