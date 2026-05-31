# estimator-api

A standalone FastAPI service that detects tax-depreciable renovations from
property photos, decoupled from the main Flask `rpdata-ai-server`.

It is a thin wrapper around a vision model: given an `rpId`, it fetches the
property's photos from **calc.duo.tax** and the renovation-items catalog from
**megamind**, sends them with the prompt, then formats the model's JSON
response. It does **not** compute construction costs.

## What it does

| Endpoint | Method | Returns | Description |
|---|---|---|---|
| `/estimate` | POST | JSON | Detect renovations for an rp_id against the megamind catalog |
| `/health` | GET | JSON | Liveness check |

Interactive API docs: `http://localhost:8000/docs`.

## Setup

```powershell
cd estimator-api
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt          # add -r requirements-dev.txt to run tests
copy .env.example .env.local             # then fill in your real values
```

Put real secrets in `.env.local` — it overrides `.env` and is git-ignored, so
live keys never get committed. At minimum set `OPENAI_API_KEY` and
`MEGAMIND_API_KEY`. The default model is `gpt-5.4-mini` (a vision-capable
reasoning model); `PHOTOS_API_URL` and `MEGAMIND_API_URL` already point at the
right endpoints.

The prompt lives in `estimator_prompt.txt` (override the path with
`ESTIMATOR_PROMPT_FILE`).

## Run

```powershell
uvicorn app.main:app --reload --port 8000
```

## Auth

Every endpoint except `/health` requires the `secret-sauce` header to match
`API_KEY` from `.env`. If `API_KEY` is unset, auth is disabled (local dev).

## Request shape

The caller supplies just an `rpId`. The service fetches that property's photos
(calc.duo.tax) **and** the renovation-items catalog (megamind) itself — neither
is passed in the request.

```json
{
  "rpId": "48819125",
  "config": { "exclusions": ["landscaping"] },
  "property": { "propertyType": "House", "yearBuilt": 2008 },
  "model": "gpt-5.4-mini"
}
```

- `rpId` — **required**. Property id; photos come from
  `https://calc.duo.tax/property/{rpId}/photos`.
- `config` — optional rules (exclusions, etc.), forwarded to the model verbatim.
- `property` — optional context, forwarded verbatim (the prompt currently treats
  it as a soft hint only — see the handoff notes).
- `model` — optional OpenAI model override (defaults to `DEFAULT_MODEL`,
  `gpt-5.4-mini`). Reasoning models (gpt-5.x, o-series) automatically use
  `reasoning_effort`; classic models use `temperature=0`.

## Response shape

```json
{
  "Renovations": [
    {
      "_id": "69b23274e04bd0417e472b18", "Name": "Driveway", "Quantity": 1,
      "Unit": "sqm", "DefaultRate": "$200.00",
      "FinalCost": "$200.00", "Year": "2018"
    }
  ],
  "Renovations Total": "$200.00",
  "Summary Description": "...",
  "Disclaimer": "This assessment is based solely on visual analysis..."
}
```

The model prices each line as `FinalCost = DefaultRate × Quantity` and returns
`Totals.TotalRenovation`; we only currency-format and reshape the output. `_id`
is the megamind item id, so callers can map results back to the catalog.
`Disclaimer` is the model's fixed visual-analysis disclaimer sentence.

### Error responses

| Status | When |
|---|---|
| `422` | `rpId` missing/invalid, or the rp_id yields no usable photos |
| `502` | megamind or calc.duo.tax unreachable / bad response, or the vision model call failed |

## Renovation items (megamind)

`GET https://api.megamind.duo.tax/api/external/estimator-items` (header
`X-API-KEY: <MEGAMIND_API_KEY>`) returns a bare JSON array of catalog items.
`app/megamind_client.py`:

- maps each item to the `{_id, name, defaultRate, unit}` shape the prompt
  expects (megamind's `id` → `_id`);
- drops soft-deleted items (`isDeleted`) and any missing an id, name, or rate;
- drops the audit/`sections` fields to keep the model input compact;
- is fetched **fresh on every estimate** (no caching).

Smoke-test it (no OpenAI call):

```powershell
python scripts/check_items.py
```

## Photos (calc.duo.tax)

`GET https://calc.duo.tax/property/{rp_id}/photos` returns a bare JSON array of
CoreLogic-style assets. `app/photos_client.py`:

- keeps only `digitalAssetType == "Image"` that aren't `noPhotoAvailable`;
- drops Google street-view / satellite shots (`maps.googleapis.com`);
- prefers `largePhotoUrl → mediumPhotoUrl → basePhotoUrl`;
- uses `scanDate` as the photo date and sorts **newest-first**;
- the vision model receives at most `MAX_PHOTOS` (60) images.

Smoke-test the photos integration **without** calling OpenAI:

```powershell
python scripts/check_photos.py 48819125
```

End-to-end (megamind items + calc photos + the paid OpenAI call):

```powershell
python scripts/check_estimate.py 48819125
```

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```
