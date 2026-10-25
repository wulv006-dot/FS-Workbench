# Exact live FC cost recovery archive

Two source files are exact copies of the already deployed cost reader and automation tick. deployed-manifest.json and deployed-receipt.json preserve the original two-target CAS deployment and backup provenance; baseline contains the corresponding pre-deployment source. The manifest's authorization text is historical provenance, not authorization for any new production action.

Run offline regression: `python -I -B -m unittest discover -s tests -v` from this directory. All 12 tests must run and pass; no skips, external browser, session, network, model or pricing operation is used.

This archive does not contain the manual recovery launcher, does not deploy code, and does not change pricing or schedules. Production state and formal CI/natural-cycle acceptance are recorded separately under docs/planning/fc-cost-live-ci-20261025.
