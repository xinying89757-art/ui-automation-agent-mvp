#!/usr/bin/env python3
"""CI entry point for safe, bounded knowledge-catalog validation."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from uia_core.knowledge import validate

if __name__ == '__main__':
    result = validate()
    print('Knowledge catalog valid:', result['patterns'], 'patterns')
