#!/bin/zsh
export PYTHONPATH=$(pwd)
export $(grep -v '^#' text2sql_app/.env 2>/dev/null | xargs -I {} echo {})
uvicorn text2sql_app.app.main:app --host ${APP_HOST:-0.0.0.0} --port ${APP_PORT:-8010} --reload 