"""Entry point that works when started by full path (e.g. a UNC path from the ADM account).

Usage:  python run.py probe   |   python run.py unc
"""

import ctypes
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def to_unc(path: Path) -> str:
    # Mapped drive letters are per-user, so the ADM account needs the UNC form.
    drive = path.drive
    if len(drive) == 2 and drive[1] == ":":
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(len(buf))
        if ctypes.windll.mpr.WNetGetConnectionW(drive, buf, ctypes.byref(size)) == 0:
            return buf.value + str(path)[2:]
    return str(path)


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "unc":
        print(to_unc(PROJECT_ROOT))
        return 0
    if command == "probe":
        from extract import probe
        return probe.main()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
