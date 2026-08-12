"""Tests for the volume persistence probe."""

from __future__ import annotations

from pathlib import Path

from crp_comply.api.persistence_probe import (
    MARKER_FILENAME,
    build_status_dict,
    probe_volume,
    record_status,
)


def test_first_boot_reports_no_persistence(tmp_path: Path) -> None:
    status = probe_volume(tmp_path)
    assert status["writable"] is True
    assert status["first_boot"] is True
    assert status["persistent"] is None
    assert status["previous_boots_seen"] == 0
    assert status["current_boot_id"]
    assert (tmp_path / MARKER_FILENAME).exists()


def test_second_boot_reports_persistence(tmp_path: Path) -> None:
    first = probe_volume(tmp_path)
    second = probe_volume(tmp_path)

    assert second["first_boot"] is False
    assert second["persistent"] is True
    assert second["previous_boot_id"] == first["current_boot_id"]
    assert second["previous_boots_seen"] == 1


def test_boot_count_increments(tmp_path: Path) -> None:
    for expected in range(5):
        status = probe_volume(tmp_path)
        if expected == 0:
            assert status["first_boot"] is True
            assert status["previous_boots_seen"] == 0
        else:
            assert status["first_boot"] is False
            assert status["previous_boots_seen"] == expected


def test_ephemeral_fs_looks_like_first_boot(tmp_path: Path) -> None:
    """Simulate a redeploy wiping the data dir: marker disappears."""
    probe_volume(tmp_path)
    # Wipe everything (as an ephemeral container redeploy would)
    for p in tmp_path.iterdir():
        p.unlink()
    status = probe_volume(tmp_path)
    # Probe correctly reports first_boot again — operator must see this
    # happen on every redeploy to know the volume is not persistent.
    assert status["first_boot"] is True
    assert status["persistent"] is None


def test_build_status_dict_before_probe() -> None:
    # Clear previous state if any (test isolation)
    record_status({})
    record_status.__globals__["_last_status"] = None  # type: ignore[attr-defined]
    assert build_status_dict() == {"probed": False}


def test_build_status_dict_after_probe(tmp_path: Path) -> None:
    status = probe_volume(tmp_path)
    record_status(status)
    got = build_status_dict()
    assert got["probed"] is True
    assert got["data_dir"] == str(tmp_path)
    assert got["writable"] is True


def test_nonwritable_data_dir_marked(tmp_path: Path, monkeypatch) -> None:
    """If writing fails, the probe should surface a warning, not crash."""

    bad_path = tmp_path / "readonly"
    bad_path.mkdir()

    # Force the probe file write to fail
    real_write = Path.write_text

    def fail_write(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name == ".crp_write_probe":
            raise PermissionError("simulated read-only fs")
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_write)
    status = probe_volume(bad_path)
    assert status["writable"] is False
    assert status["warning"]
