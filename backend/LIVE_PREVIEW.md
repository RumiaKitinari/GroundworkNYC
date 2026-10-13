# Actual frontend with the recovered data

The frontend from the supplied GitHub ZIP runs through the FastAPI backend at `http://127.0.0.1:8000/demo` while the local server is running. This is the original dashboard, not an inline replacement.

The live `/api/dashboard` returns 19 partial tract records derived from 20 recovered Queens block groups. The original screening model computes scores from observed walkability and historical population/job density, with unavailable signals retaining its existing limited-coverage behavior. The original `/api/hex-demand` computes the concept layer from those same records. No mock API payloads or invented restaurant, property, income or subway observations are used.

The preview starts on Walkability and has a local geographic background from official NYC neighborhood boundaries. Location selection, brief editing, rankings and the concept hex layer were verified in an actual browser with no JavaScript errors. The source sample remains provisional because its archive was truncated. Geographic outlines represent sampled block groups within each tract, not complete tract boundaries. Screening scores are not survival predictions.

To restart from the repository root using the installed backend environment:

```bash
export GROUNDWORK_PREVIEW=1
export GROUNDWORK_DATA_DIR="$(pwd)/data/integrated/epa_recovered_preview"
cd backend
python -m uvicorn groundwork_backend.api:app --host 127.0.0.1 --port 8000
```

The development-only `/demo` route enters the existing guest flow and opens the populated dashboard. It is unavailable in production. `GROUNDWORK_DATA_DIR` selects the input package; the original private package remains the default when that variable is unset.
