# Brikit Runbook

## Prerequisites
- Docker + Docker Compose

## Quick start
```bash
docker compose up --build
```

## Codespaces
1. Open the repository in GitHub Codespaces.
2. Run `docker compose up --build` from the workspace root.
3. Access the services using forwarded ports (3000 for web, 8000 for API).

## FastAPI in Codespaces (without Docker)
If you want to run a minimal FastAPI app directly in Codespaces, use the steps below:

```bash
# (Optional) enter the project folder
# cd /workspaces/<repo-name>

# create and activate a virtualenv
python -m venv .venv
source .venv/bin/activate

# upgrade pip
python -m pip install --upgrade pip

# install FastAPI (recommended extras)
pip install "fastapi[standard]"

# create a minimal main.py
cat > main.py << 'PY'
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}
PY

# run the dev server on port 8000
fastapi dev --host 0.0.0.0 --port 8000 main.py
```

Then, in the Codespaces "PORTS" tab, open port 8000 in the browser.

## Environment variables
Copy `.env.example` to `.env` and adjust as needed.

- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`: Postgres credentials
- `DATABASE_URL`: API connection string to Postgres
- `NEXT_PUBLIC_API_URL`: Base URL used by the web app to reach the API

## Endpoints & ports
- Web UI: http://localhost:3000
- API: http://localhost:8000
  - Health check: http://localhost:8000/health
- Postgres: localhost:5432

## Running without the SuperDB
The API can start without a SuperDB file during early development. Any endpoints that
depend on SQLite data will return errors until `database/brickovery_sp.db` exists.

## Rebuilding the SuperDB
When the inputs are available, validate and rebuild:

```bash
python tools/validate_inputs.py --root .
python tools/build_superdb_all.py --root . --force
```
