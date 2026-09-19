"""Allow `python -m arh ...` when the console script is not on PATH."""

from arh.cli import main

raise SystemExit(main())
