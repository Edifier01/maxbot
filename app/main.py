"""Точка входа для серверного развёртывания.

Пока делегирует в корневой main.py. Серверные отличия — в hooks.py и здесь.
"""

from __future__ import annotations

import contextlib
import signal
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import hooks  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    hooks.before_start()

    import main as app_main  # noqa: WPS433 — intentional import of root module

    app_main._self_check_round_robin()
    app_main.init_db()

    from app.campaign_runtime import RUNTIME

    def _handle_signal(signum, _frame):
        from app.shutdown import handle_process_signal

        def _exit(code: int = 0) -> None:
            hooks.after_shutdown()
            sys.exit(code)

        handle_process_signal(
            signum,
            _frame,
            encrypt_all=app_main._encrypt_all_sessions,
            exit_fn=_exit,
            log=app_main.append_log,
        )

    with contextlib.suppress(ValueError, OSError):
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    open_browser = "--no-browser" not in args
    if open_browser:
        app_url = app_main.APP_URL

        def _open_browser_when_ready() -> None:
            for _ in range(40):
                try:
                    urlopen(app_url, timeout=1)
                    import webbrowser

                    webbrowser.open(app_url)
                    return
                except (URLError, OSError):
                    time.sleep(0.25)
            import webbrowser

            webbrowser.open(app_url)

        threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    import uvicorn

    try:
        uvicorn.run(app_main.app, host=app_main.HOST, port=app_main.PORT, log_level="info")
    finally:
        hooks.after_shutdown()


if __name__ == "__main__":
    main()
