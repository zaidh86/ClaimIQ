"""ClaimIQ entry point.

Run from the repository root:

    python app.py

Serves the full application (API + frontend) on http://localhost:8000
"""

import logging

import uvicorn

from claimiq import APP_NAME, __version__
from claimiq.config import settings
from claimiq.server import app


def main() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    )
    logging.getLogger(__name__).info(
        "%s v%s starting — open http://localhost:%d", APP_NAME, __version__, settings.port
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)


if __name__ == "__main__":
    main()
