# Exact recovery

Apply backend first, then inspect/apply frontend against the newly installed summary SHA. Each publisher requires its exact frozen manifest SHA, root ownership, original before hashes and existing shared locks. No publication if a protected baseline differs.

Rollback frontend first using its release-manifest hash and server-private recorded backup; then rollback backend with its approved-manifest hash and recorded nav backup. Verify all protected hashes, health and unchanged Session/FC Worker/API PIDs. Only range may restart. Do not remove immutable old assets, modify collectors, roll back databases or replay the copied historical frontend approved-manifest.json. The new release preserves the previous PR54 baseline in baseline/ and the release records in evidence/.
