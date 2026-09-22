#!/usr/bin/env python3
"""Bounded localhost-only panel benchmark helper for audit fixtures."""

from __future__ import annotations

import argparse
import json
from time import monotonic
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/api/health")
    parser.add_argument("--requests", type=int, default=1)
    args = parser.parse_args()
    if args.requests < 1 or args.requests > 100:
        parser.error("--requests must be between 1 and 100")
    if not args.url.startswith("http://127.0.0.1:"):
        parser.error("benchmark is restricted to localhost HTTP fixtures")

    timings: list[float] = []
    for _ in range(args.requests):
        started = monotonic()
        with urlopen(Request(args.url, method="GET"), timeout=5) as response:
            response.read()
        timings.append((monotonic() - started) * 1000)
    print(
        json.dumps(
            {
                "url": args.url,
                "requests": len(timings),
                "min_ms": round(min(timings), 3),
                "max_ms": round(max(timings), 3),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
