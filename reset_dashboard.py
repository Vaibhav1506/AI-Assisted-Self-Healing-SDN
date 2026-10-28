"""Reset the dashboard view without deleting saved experiment evidence."""
import argparse
from datetime import datetime, timezone
import fcntl
from pathlib import Path
import re

PROJECT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore', action='store_true', help='show all saved runs again')
    args = parser.parse_args()
    lock_path = PROJECT / '.runtime' / 'network.lock'
    lock = lock_path.open('r') if lock_path.exists() else None
    try:
        if lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.exit(1, 'An experiment is running. Wait for it to finish before resetting.\n')
        path = PROJECT / 'dashboard' / 'static' / 'index.html'
        content = path.read_text()
        cutoff = '' if args.restore else datetime.now(timezone.utc).isoformat()
        updated, count = re.subn(
            r'(<meta name="dashboard-reset-at" content=")[^"]*(">)',
            lambda match: match[1] + cutoff + match[2], content)
        if count != 1:
            parser.exit(1, 'Dashboard reset setting was not found; no files changed.\n')
        path.write_text(updated)
        print('All saved runs restored.' if args.restore else 'Dashboard reset. Earlier runs are hidden; evidence files are preserved.')
        print('Refresh the website (Ctrl+Shift+R) to load the updated view.')
    finally:
        if lock:
            lock.close()


if __name__ == '__main__':
    main()
