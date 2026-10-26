"""Entry point for the frozen command-line build.

PyInstaller needs a script, not `-m package`, so this is the thinnest possible
wrapper. The console build keeps stdout, which is what `--cat` streams to.
"""

import sys

from vhdpeek.cli import main

if __name__ == "__main__":
    sys.exit(main())
