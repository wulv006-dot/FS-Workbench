# Exact recovery

Apply backend first, then inspect/apply frontend against the newly installed summary SHA. Each publisher requires its exact frozen manifest SHA, root ownership, original before hashes and existing shared locks. No publication if a protected baseline differs.

The profit-chart follow-up adds a further frontend layer on top of the QA follow-up. Exact full inverse, without skipping a layer:

1. Roll back the profit-chart frontend through the staged frontend `release_workspace.py`, approved manifest `e74e76b48ded8136b7c7c6f09c75d1f076c36df6841e9b059378887439719f33`, backup `/var/backups/fs-navigation-native-20261006/workspace-native-20261006-4f580f4929b8`. This restores PR56 including its business ledger. Its staged directory `/opt/fs-period-front-20261010-<archive-sha8>/` is created when this frontend package is built; it does not exist yet and no publication has been attempted.
2. Roll back the PR56 frontend through `/opt/fs-period-front-20261010-4c2a4873/release_workspace.py`, approved manifest `0692597f6fca802f4aaff2082777ae46d3bec8866f093ca09a1f7cdcc655ed87`, backup `/var/backups/fs-navigation-native-20261006/workspace-native-20261006-0a809f54cc4e`. This restores PR55, leaving its backend active.
3. To fully restore PR54, roll back the PR55 frontend through `/opt/fs-period-front-20261010-9d3ca003/release_workspace.py`, manifest `eed01ddd2e91c5895a766bc47fce65bdad7b1e6e5500dfaadfbbe74549377c71`, backup `/var/backups/fs-navigation-native-20261006/workspace-native-20261006-0a6e228c6de6`.
4. Then roll back the backend through `/opt/fs-period-backend-20261010-56fd0e34/release_navigation.py`, manifest `6e464281cfcb918f7adccf8e43e5ba1b7bf5e79fa535406cbc9d54f9fbe5a724`, backup `/var/backups/fs-navigation-20261006/nav-20261010T092800Z`.

Each is the existing `rollback --approved-manifest-sha <exact hash> --backup <exact backup>` action; it checks CAS and refuses peer drift before restoring. Verify all protected hashes, health and unchanged Session/FC Worker/API PIDs. Only range may restart. Do not remove immutable old assets, modify collectors, roll back databases or replay the copied historical frontend approved-manifest.json. PR54 baseline is in baseline/; PR55 frontend baseline is preserved in pr55-deployed/ in the local archive. Recovery has not been executed.
