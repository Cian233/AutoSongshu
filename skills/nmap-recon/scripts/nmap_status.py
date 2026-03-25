from __future__ import annotations

import json
from pathlib import Path

from nmap_common import status

def main() -> None:
    print(json.dumps(status(Path(__file__).resolve().parents[1]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
