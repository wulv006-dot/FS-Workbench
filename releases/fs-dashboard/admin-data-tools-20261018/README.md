# Admin read-only product and discount tools

This release archives source 792071b0dc06602f1d1b59aea414d9090db3b7ca, deployed as nav-20261017T164002Z. The approved manifest maps 11 exact runtime targets; do not deploy this directory over unrelated runtime files or replay its historical CAS baseline.

The product tool resolves actual main-site model/platform IDs before paging orders. Whole-order USD is deduplicated separately from item-line original currencies. The discount tool reuses the existing ES period archive, retains original statuses, unknowns and signed USD amounts, and does not equate new-customer flags with exclusive promotion eligibility or proven retention.

Run `python -m unittest discover -s releases/fs-dashboard/admin-data-tools-20261018 -p "test_*.py" -v`, or use the existing affected `tools/pr_fast.py` dispatcher. Tests are synthetic and offline. The test import path is adapted for a clean checkout; runtime source, publisher bytes and historical manifest remain unchanged. `.gitattributes` preserves their exact bytes.

Real reports, teaching HTML, financial aggregates, original exports, customer/order identities and credentials are excluded. The current reporting skill and memory live in the approved private Hermes profile, frozen into each new task with a version and hash. Current first-order 30% promotion is business context, not a new pricing action or proof of campaign causality. Dashboard consumers remain phase two; this release adds no dashboard UI, timer or business write.
