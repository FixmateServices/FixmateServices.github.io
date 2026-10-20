#!/usr/bin/env python3
"""Start the FixMate booking server.

    python3 server/run.py                              # 127.0.0.1:8080
    python3 server/run.py --port 8000
    python3 server/run.py --host 0.0.0.0 --secure-cookies
    python3 server/run.py --config ../my-config.json

This is only a convenience wrapper. Everything it does lives in fixmate.cli,
which is also usable directly as `python3 -m fixmate.cli serve`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixmate.cli import main  # noqa: E402

# Options that belong to the top-level parser have to be placed before the
# subcommand, so they are pulled out of argv and re-ordered rather than passed
# straight through (argparse would reject them after "serve").
GLOBAL_WITH_VALUE = ("--config", "--db", "--static")
GLOBAL_FLAGS = ("-v", "--verbose")


def split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    globals_, rest = [], []
    remaining = list(argv)
    while remaining:
        token = remaining.pop(0)
        if token in GLOBAL_FLAGS or token.startswith(tuple(f"{n}=" for n in GLOBAL_WITH_VALUE)):
            globals_.append(token)
        elif token in GLOBAL_WITH_VALUE and remaining:
            globals_.extend((token, remaining.pop(0)))
        else:
            rest.append(token)
    return globals_, rest


if __name__ == "__main__":
    front, back = split_argv(sys.argv[1:])
    sys.exit(main([*front, "serve", *back]))