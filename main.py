#!/usr/bin/env python3
"""TTR Fishing Bot – macOS entry point."""

import sys
import platform

from utils.logger import log


def main() -> None:
    if platform.system() != "Darwin":
        log.error("This bot only runs on macOS.")
        sys.exit(1)

    log.info("Starting TTR Fishing Bot…")

    from ui.app import App
    app = App()
    app.run()


if __name__ == "__main__":
    main()
