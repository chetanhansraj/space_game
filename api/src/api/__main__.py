"""Run the world: ``python -m api``.

One process, one worker, always. The world lives in this process's memory
beside its database; a second worker would be a second, diverging world.
"""

from __future__ import annotations

import logging
import os

import uvicorn

from .server import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(
        create_app(),
        host=os.environ.get("SOLAR_HOST", "127.0.0.1"),
        port=int(os.environ.get("SOLAR_PORT", "8000")),
        workers=1,
        # Behind Caddy or nginx the client address arrives in a header. Only
        # trusted from the proxy itself, or anyone could spoof it past the
        # signup rate limit.
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("SOLAR_TRUSTED_PROXIES",
                                           "127.0.0.1"),
        log_level="info",
    )


if __name__ == "__main__":
    main()
