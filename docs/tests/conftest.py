"""
pytest conftest.py
==================
Shared configuration for all test suites.
Automatically adds project root to sys.path.
"""

import sys
import os

# Ensure the project root is in the Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
