import os
import time

from app.services.backup.retention import KEEP, STALE_PARTIAL_SECONDS, dumps, prune


def _dump(folder, day, hour=2):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"tracker-202610{day:02d}T{hour:02d}3000Z.dump"
    path.write_bytes(b"x")
    return path


def test_keep_counts_match_the_spec():
    assert KEEP == {"nightly": 14, "pre-deploy": 5, "manual": 5}


def test_prune_keeps_the_newest_dumps_per_label(tmp_path):
    made = [_dump(tmp_path / "nightly", day) for day in range(1, 21)]
    deleted = prune(tmp_path, "nightly")
    assert deleted == made[:6]
    assert dumps(tmp_path / "nightly") == made[6:]


def test_prune_orders_by_the_timestamp_in_the_name_not_mtime(tmp_path):
    made = [_dump(tmp_path / "manual", day) for day in range(1, 8)]
    # Make the oldest file look newest on disk; it must still go.
    os.utime(made[0], (time.time() + 3600, time.time() + 3600))
    prune(tmp_path, "manual")
    assert dumps(tmp_path / "manual") == made[2:]


def test_labels_are_pruned_separately(tmp_path):
    nightly = [_dump(tmp_path / "nightly", day) for day in range(1, 4)]
    pre = [_dump(tmp_path / "pre-deploy", day) for day in range(1, 9)]
    prune(tmp_path, "pre-deploy")
    assert dumps(tmp_path / "pre-deploy") == pre[3:]
    assert dumps(tmp_path / "nightly") == nightly


def test_prune_only_touches_exact_dump_names(tmp_path):
    folder = tmp_path / "manual"
    made = [_dump(folder, day) for day in range(1, 10)]
    others = [
        folder / "tracker-20260101T000000Z.dump.enc",
        folder / "tracker-20260101T000000Z.dump.bak",
        folder / "my-copy.dump",
        folder / "tracker-2026010T000000Z.dump",
        folder / "README.txt",
    ]
    for p in others:
        p.write_bytes(b"keep")
    (folder / "tracker-20260101T000000Z.dump.d").mkdir()
    prune(tmp_path, "manual")
    assert dumps(folder) == made[4:]
    assert all(p.exists() for p in others)
    assert (folder / "tracker-20260101T000000Z.dump.d").is_dir()


def test_prune_never_follows_symlinks(tmp_path):
    folder = tmp_path / "manual"
    target = tmp_path / "elsewhere.dump"
    target.write_bytes(b"precious")
    made = [_dump(folder, day) for day in range(2, 8)]
    link = folder / "tracker-20261001T000000Z.dump"
    link.symlink_to(target)
    prune(tmp_path, "manual")
    assert target.read_bytes() == b"precious"
    assert link.is_symlink()
    assert dumps(folder) == made[1:]


def test_newest_is_kept_even_with_one_file(tmp_path):
    only = _dump(tmp_path / "pre-deploy", 1)
    assert prune(tmp_path, "pre-deploy") == []
    assert only.exists()


def test_missing_folder_is_fine(tmp_path):
    assert prune(tmp_path, "nightly") == []


def test_stale_partial_files_are_removed_fresh_ones_kept(tmp_path):
    folder = tmp_path / "nightly"
    folder.mkdir()
    stale = folder / "tracker-20261001T023000Z.dump.partial"
    fresh = folder / "tracker-20261008T023000Z.dump.partial"
    other = folder / "something.partial"
    for p in (stale, fresh, other):
        p.write_bytes(b"half")
    now = time.time()
    old = now - STALE_PARTIAL_SECONDS - 60
    os.utime(stale, (old, old))
    os.utime(other, (old, old))
    assert prune(tmp_path, "nightly", now=now) == [stale]
    assert fresh.exists() and other.exists()
