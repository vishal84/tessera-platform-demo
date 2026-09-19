"""
Repo-wide pytest configuration.

The guardrail hooks append to .tessera/audit.jsonl on every decision. Tests
that exercise them point the trail at a temp dir explicitly; everything else
must not write into the repository as a side effect of running the suite.
"""

import os

os.environ.setdefault("TESSERA_AUDIT_DISABLE", "1")
