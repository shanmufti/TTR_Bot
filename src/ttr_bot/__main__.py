#!/usr/bin/env python3
"""TTR Bot – macOS entry point."""

import platform
import sys

from ttr_bot.utils.logger import log


def main() -> None:
    """Launch the TTR Bot GUI (macOS only)."""
    if platform.system() != "Darwin":
        log.error("This bot only runs on macOS.")
        sys.exit(1)

    log.info("Starting TTR Bot…")

    from ttr_bot.ui.app import App

    app = App()
    app.run()


if __name__ == "__main__":
    main()
