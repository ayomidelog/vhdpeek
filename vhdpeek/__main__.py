"""
Entry point for `python -m vhdpeek`.

    python -m vhdpeek <file-or-url> [--parts] [--part N]
    python -m vhdpeek <file-or-url> --tree [--max-depth N]
    python -m vhdpeek <file-or-url> --ls /var/log
    python -m vhdpeek <file-or-url> --cat /etc/os-release > os-release
    python -m vhdpeek <file-or-url> --iso /ubuntu.iso --ls /casper
    python -m vhdpeek --gui [file-or-url]

An ISO that lives inside the partition's filesystem is mounted with `--iso`
and then addressed like any other filesystem, without extracting it.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
