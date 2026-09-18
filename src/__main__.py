"""Permet « python -m src » comme « python -m src.cli »."""

import sys

from src.cli import main

sys.exit(main())