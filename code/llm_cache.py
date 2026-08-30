"""
Disk-backed cache for LLM calls, keyed by a hash of the exact request.

Why this exists: the August Orchestrate build hit Groq's free-tier daily
token cap after roughly 19 real calls and lost hours to it near the
deadline. This dataset is ~150 cases x several evaluation re-runs, which
will blow that cap repeatedly if every re-run re-calls the API. Caching by
request hash means re-running the evaluation (to fix a bug, tune a
threshold, or just re-verify a number) costs zero additional API calls for
any case already seen with that exact prompt.

Deliberately dumb: one JSON file per cache entry, no expiry, no eviction.
The correctness property that matters here is "the same request never hits
the network twice," not cache hygiene.
"""

import hashlib
import json
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).parent.parent / ".cache" / "llm_responses"


def _key_for(payload: dict) -> str:
    """Stable hash of the exact request. `sort_keys=True` so key order in
    the payload never changes the hash, since dict key order isn't
    semantically meaningful to the request itself."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def get(self, payload: dict) -> Optional[dict]:
        """Returns the cached normalized response dict, or None on a miss."""
        path = self.dir / f"{_key_for(payload)}.json"
        if not path.exists():
            self.misses += 1
            return None
        try:
            self.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.misses += 1
            return None

    def put(self, payload: dict, response: dict) -> None:
        """Persists a normalized response dict under the request's hash."""
        path = self.dir / f"{_key_for(payload)}.json"
        path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")

    def stats(self) -> str:
        total = self.hits + self.misses
        rate = (self.hits / total * 100) if total else 0.0
        return f"cache: {self.hits}/{total} hits ({rate:.0f}%)"
