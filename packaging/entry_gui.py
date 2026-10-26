"""Entry point for the frozen windowed build.

No console: a GUI launched from Explorer should not leave a black window
behind it. The cost is that this build cannot stream to stdout, so the
console build (`vhdpeek.exe`) remains the one for `--cat`.
"""

import sys

from vhdpeek.gui import main

if __name__ == "__main__":
    sys.exit(main())
