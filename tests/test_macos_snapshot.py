"""Execute the actual Foundation model used by the background menu-bar client."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"), reason="macOS Swift compiler required")
def test_native_sync_snapshot_and_reconnect_reset(tmp_path):
    source = Path(__file__).resolve().parents[1] / "macos/Sources"
    main = tmp_path / "main.swift"
    main.write_text('''import Foundation
var snapshot = BandSnapshot()
snapshot.apply(state: ["connected": true, "health": ["state": "done", "last_sync": 123, "errors": []]])
assert(snapshot.connected)
assert(snapshot.healthSyncState == "done")
assert(snapshot.healthLastSync?.timeIntervalSince1970 == 123)
snapshot.applyHealth(["state": "running", "step": "HR", "last_sync": 123])
assert(snapshot.healthSyncState == "running" && snapshot.healthSyncStep == "HR")
snapshot.applyHealth(["state": "error", "errors": ["SpO2"], "last_sync": 123])
assert(snapshot.healthSyncErrors == ["SpO2"])
assert(snapshot.healthLastSync?.timeIntervalSince1970 == 123)
snapshot.applyHealth(["state": "done", "errors": [], "last_sync": 456])
assert(snapshot.healthSyncErrors.isEmpty && snapshot.healthSyncStep.isEmpty)
snapshot.apply(state: ["connected": false])
assert(!snapshot.connected && snapshot.healthSyncState == "idle")
assert(snapshot.healthLastSync == nil)
print("native sync snapshot passed")
''')
    executable = tmp_path / "snapshot-test"
    subprocess.run(["swiftc", str(source / "BandEvents.swift"), str(source / "L10n.swift"),
                    str(main), "-o", str(executable)], check=True, capture_output=True, text=True)
    assert "passed" in subprocess.check_output([str(executable)], text=True)
