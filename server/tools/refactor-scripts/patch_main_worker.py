"""Replace extracted worker blocks in main.py with imports from campaign_worker."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main_path = ROOT / "main.py"
lines = main_path.read_text(encoding="utf-8").splitlines()

IMPORT_BLOCK = [
    "from app.campaign_worker import (",
    "    begin_campaign as _begin_campaign,",
    "    finish_campaign as _finish_campaign,",
    "    notify_campaign_end as _notify_campaign_end,",
    "    schedule_telegram as _schedule_telegram,",
    "    scheduler_loop as _scheduler_loop,",
    "    start_worker as _start_worker,",
    "    stop_all_workers as _stop_all_workers,",
    "    stop_worker as _stop_worker,",
    "    watchdog_loop as _watchdog_loop,",
    "    worker_shutdown as _worker_shutdown,",
    ")",
    "",
]

# Remove blocks bottom-up so line numbers stay valid
ranges = [(3700, 3817), (3264, 3677), (2754, 2979)]
for start, end in ranges:
    del lines[start - 1 : end]

insert_at = 2754 - 1
for i, row in enumerate(IMPORT_BLOCK):
    lines.insert(insert_at + i, row)

main_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("Patched main.py")
