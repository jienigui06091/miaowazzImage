from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.image_service import ensure_thumbnail
from services.image_storage_service import image_storage_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate missing local thumbnails for stored images.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of images to process. 0 means all.")
    args = parser.parse_args()

    created = 0
    failed = 0
    items = image_storage_service.list_items("", owner_id="")
    for item in items:
        if args.limit and created + failed >= args.limit:
            break
        rel = str(item.get("path") or item.get("rel") or "")
        if not rel:
            continue
        try:
            ensure_thumbnail(rel)
            created += 1
            print(f"ok {rel}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"failed {rel}: {exc}", file=sys.stderr, flush=True)

    print(f"thumbnail warmup complete: ok={created} failed={failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
