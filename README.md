# Zemlya AI Agent

MVP cloud agent for discovering and qualifying investment-project leads in Moscow Oblast.

## Local run

```bash
python -m venv .venv
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Health endpoint: `/health`

## Railway

The web service start command is already defined in `railway.toml`.

Worker command for a separate Railway service:

```bash
celery -A app.worker.celery_app worker --loglevel=info
```
