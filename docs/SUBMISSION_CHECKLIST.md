# L13 + L14 Team 5 submission checklist

Filename prefix: **L13_L14_Team5**. Course: **BCSE308P Computer Networks Lab**.
Report author: **Vaibhav Bakshi (24BCE2052)**, from the existing documents.

| Assignment | Required upload | Remaining user action |
| --- | --- | --- |
| 8 | `Deliverables/L13_L14_Team5_Report.pdf` | Supply the certificate signature on page 3, update the PDF, then upload to VTOP. |
| 9 | `Deliverables/L13_L14_Team5_PPT.pptx` | Review and upload to VTOP. |
| 10 | Public GitHub repository URL | Verify signed-out access and submit the URL to VTOP. |

## Repository contents to verify

- Source: `main.py`, `src/selfheal/`, `dashboard/`, `reset_dashboard.py`.
- Required detector: `src/selfheal/assets/detector.joblib`.
- Setup: `README.md`, `requirements.txt`, `docs/INSTALLATION.md`.
- Topology/configuration: `network.py`, `topology.py`, `config.py`.
- Testing: `tests/`, `docs/TESTING_RESULTS.md`, `evidence/verification/`.
- Eight original report runs: `evidence/runs/report/`.
- Later failback examples: `evidence/runs/failback/`.
- Dashboard screenshots with provenance: `evidence/screenshots/`.
- PDF, editable report and PPTX: `Deliverables/`.
- Virtual environments, transient runs and old deliverables remain ignored.

The screenshot stress example uses 10 Mbps load and is separate from the
4 Mbps report conditions. Report/slide runs predate automatic failback; the
repository documents the extension separately.

## Before evaluation

Run automated checks and `python3 main.py doctor`, then rehearse
`sudo python3 main.py smoke` on the demonstration machine. Be ready to explain
topology, measurements, detector/guard differences, forwarding updates,
healthy-path requirements, recovery verification and limits of the results.

Confirm successful uploads for all three VTOP assignments. A local file or
GitHub commit does not complete the VTOP submission.
