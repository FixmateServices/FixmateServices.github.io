"""Allows `python3 -m fixmate` as a shorthand for `python3 -m fixmate.cli`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())