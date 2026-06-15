#!/usr/bin/env sh
set -eu

export PYTHONPATH="${PYTHONPATH:-src}"
exec streamlit run src/hanoi_real_estate/dashboard/app.py
