# Included experiment evidence

- `runs/report/`: the exact eight records cited by the report and presentation.
- `runs/failback/`: three later records of automatic return to primary.
- `runs/additional/`: the separate 10 Mbps-load stress screenshot record.
- `screenshots/`: original dashboard captures and their conditions.
- `verification/`: automated-check output and environment information.
- `manifest.json`: file sizes and SHA-256 checksums for every original run file.
- `results.csv`: aggregate metrics copied from the included summaries.

Raw run files are copied byte-for-byte from the lab machine. They retain original
absolute model paths, platform information and source hashes for provenance;
those paths are not needed to replay the recordings on another machine.

For results and interpretation, see [TESTING_RESULTS.md](../docs/TESTING_RESULTS.md).
To populate the local dashboard, run `python3 tools/restore_evidence.py` from the
repository root, then `python3 reset_dashboard.py --restore` and start the dashboard.
