# estimator-api

A standalone FastAPI service that detects tax-depreciable renovations from
property photos, decoupled from the main Flask `rpdata-ai-server`.

It is a thin wrapper around a vision model: it sends the prompt, an
authoritative `renovationItems` dataset, and the photos, then formats the
model's JSON response. It does **not** compute construction costs.

## What it does

| Endpoint | Method | Returns | Description |
|---|---|---|---|
| `/estimate` | POST | JSON | Detect renovations from photos against the dataset |
| `/health` | GET | JSON | Liveness check |

Interactive API docs: `http://localhost:8000/docs`.

## Setup

```powershell
cd estimator-api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill in values
```

The prompt lives in `estimator_prompt.txt` (override the path with
`ESTIMATOR_PROMPT_FILE`). Edit that file to change the model's instructions.

## Run

```powershell
uvicorn app.main:app --reload --port 8000
```

## Auth

Every endpoint except `/health` requires the `secret-sauce` header to match
`API_KEY` from `.env`. If `API_KEY` is unset, auth is disabled (local dev).

## Request shape

```json
{
  "photos": [{ "url": "https://...", "date": "2024-01-01" }],
  "renovationItems": [
    { "_id": "a1", "name": "Split System AC", "defaultRate": 1200, "unit": "each" }
  ],
  "config": { "exclusions": ["landscaping"] },
  "property": { "propertyType": "House", "buildYear": "2005" },
  "model": "gpt-4.1"
}
```

- `photos` — image URLs (+ optional date) sent to the vision model.
- `renovationItems` — **required** authoritative dataset; the model may only
  match against these and may not invent items or alter rates.
- `config` — optional rules (exclusions, etc.), forwarded to the model verbatim.
- `property` — optional context, forwarded verbatim.
- `model` — optional OpenAI model override (defaults to `DEFAULT_MODEL`).

## Response shape

```json
{
  "Renovations": [
    {
      "_id": "a1", "Name": "Split System AC", "Quantity": 2,
      "Unit": "each", "DefaultRate": "$1,200.00",
      "FinalCost": "$2,400.00", "Year": "2018"
    }
  ],
  "Renovations Total": "$2,400.00",
  "Summary Description": "...",
  "Disclaimer": "This assessment is based solely on visual analysis..."
}
```

The model prices each line as `FinalCost = DefaultRate × Quantity` and returns
`Totals.TotalRenovation`; we only currency-format and reshape the output.
`Disclaimer` is the model's fixed visual-analysis disclaimer sentence.
