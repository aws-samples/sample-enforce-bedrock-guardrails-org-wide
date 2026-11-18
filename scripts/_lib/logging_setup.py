"""Centralised logging configuration for the blog scripts.

Single entry point so every script gets the same format, level handling and
handler setup. The default level is INFO; pass --verbose on any script to
flip to DEBUG.
"""
from __future__ import annotations

import logging
import os
import sys


def configure(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose or os.environ.get("BLOG_DEBUG") else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # Quieten boto3 chatter unless asked.
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return logging.getLogger("blog")
