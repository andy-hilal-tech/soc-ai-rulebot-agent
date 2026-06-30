import os
import stat
from pathlib import Path
from datetime import datetime, timezone
import shutil


DATASETS = [
    Path("data/rules"),
    Path("data/building_blocks"),
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def remove_readonly(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        raise


def rotate_dataset(base_dir: Path, stamp: str):
    current_dir = base_dir / "current"
    previous_dir = base_dir / "previous"
    archive_dir = base_dir / "archive"

    ensure_dir(base_dir)
    ensure_dir(archive_dir)

    print(f"\n🔄 Rotating {base_dir}")

    # Archive existing previous
    if previous_dir.exists() and any(previous_dir.iterdir()):
        archive_target = archive_dir / stamp
        ensure_dir(archive_target.parent)

        if archive_target.exists():
            raise RuntimeError(f"Archive target already exists: {archive_target}")

        print(f"📦 Moving previous -> {archive_target}")
        shutil.move(str(previous_dir), str(archive_target))
    elif previous_dir.exists():
        shutil.rmtree(previous_dir)

    # Move current to previous
    if current_dir.exists() and any(current_dir.iterdir()):
        print(f"➡️ Moving current -> previous")
        shutil.move(str(current_dir), str(previous_dir))
    elif current_dir.exists():
        shutil.rmtree(current_dir)
        ensure_dir(previous_dir)
    else:
        print("⚠️ No current snapshot found; creating empty previous/current")
        ensure_dir(previous_dir)

    # Create fresh current
    ensure_dir(current_dir)

    print(f"✅ Rotation complete for {base_dir}")


def main():
    stamp = utc_stamp()
    print(f"Snapshot rotation timestamp: {stamp}")

    for dataset in DATASETS:
        rotate_dataset(dataset, stamp)

    print("\n✅ Snapshot rotation complete")


if __name__ == "__main__":
    main()