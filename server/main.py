"""Granian entrypoint: `python -m server.main`, or point any ASGI server at `server.main:app`."""

from __future__ import annotations

from granian import Granian
from granian.constants import Interfaces

from finscrape.logging_config import setup_logging
from server.app import create_app
from server.settings import get_settings

setup_logging(level=get_settings().log_level, json_format=get_settings().log_json)
app = create_app()


def main() -> None:
    s = get_settings()
    Granian(
        "server.main:app", address=s.host, port=s.port, interface=Interfaces.ASGI
    ).serve()


if __name__ == "__main__":
    main()
