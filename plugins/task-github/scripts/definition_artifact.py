#!/usr/bin/env python3
"""Compatibility CLI forwarding task execution contracts to task-worker.

New task-github code must use task_worker_bridge or github_projection directly.
This path remains only so existing automation that invokes
``task-github/scripts/definition_artifact.py`` keeps working.
"""

from __future__ import annotations

import sys

from task_worker_bridge import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
