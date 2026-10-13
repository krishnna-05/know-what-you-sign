"""Run the interface.

Development (two processes, hot reload):
    python scripts/serve.py --dev
    ... then `npm run dev` in web/ — Vite proxies /api to this process.

Production (one process, one port):
    cd web && npm run build
    python scripts/serve.py

In production the built React assets are served by the same FastAPI app, so
there is one port and no CORS. That also makes deployment a single container.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dev", action="store_true",
                    help="API only; run the Vite dev server separately. Implies --demo-data.")
    ap.add_argument("--demo-data", action="store_true",
                    help="Offer synthetic demo corpora in the interface (hidden by default)")
    args = ap.parse_args()

    # Read by kwys.api.main on every request, so set it before the app loads.
    if args.dev or args.demo_data:
        os.environ["KWYS_DEMO_DATA"] = "1"

    import uvicorn

    from kwys.api.main import app, mount_static

    if not args.dev:
        if not DIST.is_dir():
            print(
                f"No built interface at {DIST}.\n"
                "Build it first:  cd web && npm install && npm run build\n"
                "Or run the API alone with --dev and start Vite separately.",
                file=sys.stderr,
            )
            return 1
        # Mounted last so it cannot shadow /api routes.
        mount_static(DIST)
        print(f"Interface:  http://{args.host}:{args.port}")
    else:
        print(f"API only:  http://{args.host}:{args.port}/api/config")
        print("Now run:   cd web && npm run dev")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
