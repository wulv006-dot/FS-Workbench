# Exact protected recovery, not executed after final acceptance

1. Frontend first: `python3 /opt/fs-order-latency-front-20261010-32670a26/release_workspace.py rollback --approved-manifest-sha bc1db653dba81b469532809809a86f5fd87cd9d00102078d754368fd122d2e00 --backup /var/backups/fs-navigation-native-20261006/workspace-native-20261006-fd27b9451b44`
2. Final backend: `python3 /opt/fs-order-latency-backend-20261010-ee6db725/release_navigation.py rollback --approved-manifest-sha b716297f2bed204dbafb94e2591da14c11db8ca98b48da9a45be7d09d499ab8d --backup /var/backups/fs-navigation-20261006/nav-20261010T083955Z`
3. If returning entirely to PR53: `python3 /opt/fs-order-latency-backend-20261010-7431857f/release_navigation.py rollback --approved-manifest-sha ba5eb6c3470d25b6d6d99324137e40be70ce52593acc18c13384945b40b9b8f4 --backup /var/backups/fs-navigation-20261006/nav-20261010T083410Z`

The superseded first front package was actually rolled back using its own approved backup; see first-front-rollback.txt. Never restore its entry after final deployment. Do not remove immutable history or overwrite journal/manifest. CAS drift must stop recovery for owner review; preserve database, credentials, timer and peer service state.
