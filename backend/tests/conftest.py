"""
Adds the backend root to sys.path so pytest can resolve
`world`, `agent`, `mcp_server`, and `mission` as top-level packages.
"""

from __future__ import annotations

import sys
from pathlib import Path

# backend/ directory (parent of tests/)
sys.path.insert(0, str(Path(__file__).parent.parent))
