"""Offsite/backup copies of finished Bernie episodes.

Copies rendered episode MP4s (and their sidecar metadata) from config.OUT into
config.BACKUP_DIR (an offsite/network/external folder set via the BERNIE_BACKUP
env var). The copy is idempotent: if the destination already exists with the
same byte size it is skipped, and after every copy the destination size is
verified against the source.

Honest scope: this is a dumb file copy, not a versioned/dedup backup system and
not encryption. It is robust to missing dirs / disconnected network drives only
in the sense that it catches errors and reports them instead of crashing -- if
the target is unreachable the backup simply does not happen. Backup is OFF by
default: with no BERNIE_BACKUP set, config.BACKUP_DIR is None and every function
here is a no-op.
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import argparse
import shutil

import config


def target():
    """Return the backup destination dir (config.BACKUP_DIR) or None if disabled."""
    return config.BACKUP_DIR


def _sidecars(name):
    """Sidecar metadata files that should travel with <name>.mp4 (those that exist)."""
    out = []
    for fn in (f"{name}_metadata.json", "metadata.json"):
        p = config.OUT / fn
        try:
            if p.exists() and p.is_file():
                out.append(p)
        except Exception:
            pass
    return out


def _copy_one(src, dest_dir):
    """Copy a single file into dest_dir, idempotently + size-verified.

    Returns the dest Path on success (or when already present + matching), or
    None on any failure. Never raises.
    """
    try:
        src = pathlib.Path(src)
        if not src.exists() or not src.is_file():
            return None
        dest_dir = pathlib.Path(dest_dir)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[backup] cannot create target dir {dest_dir}: {e}")
            return None
        dest = dest_dir / src.name
        ssize = src.stat().st_size
        # idempotent: skip if already there with the same size
        try:
            if dest.exists() and dest.stat().st_size == ssize:
                print(f"[backup] skip (up to date): {dest}")
                return dest
        except Exception:
            pass
        shutil.copy2(str(src), str(dest))
        # verify the copy
        try:
            dsize = dest.stat().st_size
        except Exception as e:
            print(f"[backup] copied but cannot stat dest {dest}: {e}")
            return None
        if dsize != ssize:
            print(f"[backup] SIZE MISMATCH {dest} ({dsize} != {ssize}) -- copy may be incomplete")
            return None
        print(f"[backup] copied {src.name} -> {dest} ({ssize} bytes)")
        return dest
    except Exception as e:
        print(f"[backup] failed to copy {src}: {e}")
        return None


def backup_episode(name=None):
    """Copy config.OUT/<name>.mp4 (+ sidecars) into target().

    name defaults to config.EPISODE_NAME. Returns the dest MP4 Path, or None if
    backup is disabled, the source mp4 is missing, or the copy failed. Never raises.
    """
    dest_dir = target()
    if dest_dir is None:
        print("[backup] disabled (no BERNIE_BACKUP set)")
        return None
    name = name or config.EPISODE_NAME
    try:
        src_mp4 = config.OUT / f"{name}.mp4"
        if not src_mp4.exists():
            print(f"[backup] nothing to back up: {src_mp4} missing")
            return None
        dest_mp4 = _copy_one(src_mp4, dest_dir)
        # sidecars are best-effort; their failure does not fail the episode backup
        for sc in _sidecars(name):
            _copy_one(sc, dest_dir)
        return dest_mp4
    except Exception as e:
        print(f"[backup] error backing up {name}: {e}")
        return None


def backup_all():
    """Back up every *.mp4 in config.OUT. Returns the list of dest Paths copied."""
    dest_dir = target()
    if dest_dir is None:
        print("[backup] disabled (no BERNIE_BACKUP set)")
        return []
    results = []
    try:
        mp4s = sorted(config.OUT.glob("*.mp4"))
    except Exception as e:
        print(f"[backup] cannot list {config.OUT}: {e}")
        return results
    if not mp4s:
        print(f"[backup] no episodes found in {config.OUT}")
        return results
    for mp4 in mp4s:
        dest = backup_episode(mp4.stem)
        if dest is not None:
            results.append(dest)
    print(f"[backup] done: {len(results)}/{len(mp4s)} episode(s) backed up to {dest_dir}")
    return results


def main():
    ap = argparse.ArgumentParser(description="Copy finished Bernie episodes to the backup/offsite folder.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="back up every *.mp4 in the output folder (default)")
    g.add_argument("--name", help="back up a single episode by name (e.g. Bernie_Ep1)")
    args = ap.parse_args()
    if target() is None:
        print("[backup] disabled -- set BERNIE_BACKUP to a folder to enable offsite backups.")
        return
    if args.name:
        backup_episode(args.name)
    else:
        backup_all()


if __name__ == "__main__":
    main()
