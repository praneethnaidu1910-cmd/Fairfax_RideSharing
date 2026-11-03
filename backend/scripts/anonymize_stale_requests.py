"""Run RequestStore.anonymize_stale() once against DATABASE_URL (TASKS.md
#17's actual cleanup step).

There's no in-app scheduler wired to this -- same "no cron/background job"
posture as TASKS.md #14's expiry, except retention has to mutate stored
rows (not just compute a display value at read time), so it needs a real
external trigger. Run this periodically from outside the app -- a daily
cron entry or a hosting platform's scheduled job -- once the app is
actually deployed (TASKS.md #13/#18). See the README's "Data retention"
section.

    cd backend && python scripts/anonymize_stale_requests.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import make_session_factory  # noqa: E402
from app.store import RequestStore  # noqa: E402


def main() -> None:
    store = RequestStore(make_session_factory())
    anonymized_count = store.anonymize_stale()
    print(f"anonymized {anonymized_count} stale request(s)")


if __name__ == "__main__":
    main()
