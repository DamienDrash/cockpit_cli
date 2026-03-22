"""Command-line module entrypoint."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from cockpit.app import main as app_main
    except ModuleNotFoundError as exc:
        if exc.name == "textual":
            print(
                "Textual is not installed. Install project dependencies first.",
                file=sys.stderr,
            )
            return 1
        raise

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())

