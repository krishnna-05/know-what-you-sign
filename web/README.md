# Web interface

React + Vite + Tailwind, talking to the FastAPI backend in `kwys/api/`.

## Running it

```bash
# terminal 1 — the analyser
python scripts/serve.py --dev

# terminal 2 — the interface, with hot reload
cd web && npm install && npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to the backend, so the frontend
always calls same-origin paths and nothing changes in production.

## Production

```bash
cd web && npm run build
python scripts/serve.py          # one process, one port, no CORS
```

## Notes

- **Nothing is stored.** The uploaded PDF is written to a temporary file only
  because the reader needs a path, deleted when the request ends, and its
  contents are never logged.
- **The chart is hand-drawn SVG**, not a charting library. It is six bars and
  two labels; the control over mark geometry is worth more here than the
  abstraction, and it keeps the bundle at ~74 KB gzipped.
- **Colours are design tokens** redefined for dark mode rather than flipped.
  The chart pair (context gray, yours red) was validated: they separate at
  CVD delta-E 9.1 and both clear 3:1 contrast on either surface.
