# Mi Band 6 redesign and validation plan

Preserve all pre-existing working-tree edits. Do not reset, unpair, or overwrite device settings.
1. Capture baseline tests before refactoring; add regression tests for changed ingestion and calculations.
2. Reuse existing dashboard, health APIs, charts, localization, BLE decoder, and SQLite store.
3. Reorganize Overview into summary, goal rings, vitals, sleep, and working quick actions; Health into prioritized cards and expandable details. Label estimated and unavailable data.
4. Audit BLE replay/checkpoints and add conservative quality/provenance metadata without erasing raw readings; add a dependency-free empirical benchmark tool and tests.
5. Research upstream Mi Band 6 sources before protocol changes. Apply only verified compatible changes. Test simulator first; use a current live connection only when available without disrupting pairing.
6. Produce UI architecture, telemetry schema, and validation/sync report. Verify full tests, JS/Python checks, responsive screenshots and macOS packaging if feasible.

Acceptance: no fabricated metrics or continuous SpO2/HRV claims; replay-safe history; explicit unvalidated estimates; all existing and new regression tests pass; physical-device limitations stated honestly.
