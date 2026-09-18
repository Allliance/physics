"""Top-level protocol dispatcher.

Use ``python -m eval pre-audit ...`` or ``python -m eval post-audit ...``.
For compatibility, options without a protocol still select post-audit.
"""

import sys


argv = sys.argv[1:]
if not argv or argv[0] in {"-h", "--help"}:
    print("""usage: python -m eval {pre-audit,post-audit} ...

Physics evaluation protocols:
  pre-audit   Original data with benchmark-native evaluators
  post-audit  Corrected data with the unified HLE-adapted evaluator

Run `python -m eval pre-audit --help` or
`python -m eval post-audit --help` for protocol-specific commands.
""")
    raise SystemExit(0)
if argv and argv[0] == "pre-audit":
    from .pre_audit.__main__ import main

    raise SystemExit(main(argv[1:]))
if argv and argv[0] == "post-audit":
    argv = argv[1:]

from .post_audit import main

raise SystemExit(main(argv))
