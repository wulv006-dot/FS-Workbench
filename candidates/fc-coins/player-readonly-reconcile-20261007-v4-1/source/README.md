# FC v4.1 source artifact — DO NOT DEPLOY

This is a local repair candidate, not production authorization or Linux acceptance.
Runtime identities, CAS digests, inodes, process evidence and one-time approval
belong in a separately controlled binding, never this source directory or Git.

Only three application files change: API, worker and automation tick. They share
the existing automation-tick inode with reconcile; no new lock or permission
change is proposed. API dedup/publication, worker claim/invalid handling, startup
recovery and follow-up queue/parent update, and timer due/retry all acquire it
nonblocking. Busy API requests return 503/retryable/accepted=false. Worker retains
durable pending intent; no queued record is dropped to manufacture an empty queue.
Claim persists running and fsyncs the job directory before unlinking the queue;
ambiguous claim is preserved and refuses replay. Business handling runs after
queue release. OFF saves and reads do not acquire the queue mutex.

Lock boundaries: acquire the common tick inode before any other recovery lock.
Reconcile then holds price-writer through both proof rounds, CAS and final job
publication. Existing timer policy/retry lock order stays intact; all its nested
flock acquisition is nonblocking. Worker claim/follow-up holds only queue and
never calls handle/subprocess while holding it. Reconcile briefly acquires the
automation then player configuration locks around each metadata publication;
busy policy locks abort rather than wait. Existing policy saves acquire only
their policy lock, never queue. No participant waits for queue while holding
price/config locks, and there is no blocking flock edge inside queue. Each API
thread opens its own descriptor; no shared process-global flock descriptor.

The approved controller invokes the exact reviewed launch.py bytes inline with
Python -I -S -B and independently approved source-manifest and runtime-binding
SHA256. Executing launch.py from a mutable artifact file is not an approved
entrypoint. Launcher walks trusted descriptors, rejects every unlisted entry,
checks all bytes, then validates the private binding and interpreter before the
first candidate execution. Runtime modules are read/hashed as one full closure
before any module import and executed from sealed byte snapshots. No live APP
path is added to sys.path. __file__/spec.origin report verified-memory, while
separate verified_origin records the original checked source. The read-only
fixed-image probe uses an independently SHA-bound sealed input bundle and -I;
immutable image stdlib/site packages are its third-party dependency boundary.

Admission requires fresh, approved evidence that the API health response and
worker heartbeat contain the v4 protocol and their actual PID/start identity;
timer's --queue-protocol read-only mode and deployed unit/source must be checked.
Disk SHA alone is insufficient for resident Python processes. Runner checks PID
continuity and the actual fresh worker heartbeat throughout recovery. Production
restarts/deployment and gathering this evidence require their own exact window.

v4.1 enforces the receipts in launch before the first candidate execution and
again through the approved inline validator at every runner context check.
The independently approved private binding SHA authenticates the controller's
actual resident GET /health response, PID/start, collection time and HTTP origin.
Candidate API functions or reconcile's own PID cannot supply that receipt.
Timer evidence must include the effective fc27-automation-tick.service command
(/usr/bin/python3 /opt/fc27-cloud-browser/automation_tick.py), loaded unit,
fragment/drop-in path hashes, matching interpreter/source hashes, and the actual
read-only protocol result using that same command plus --queue-protocol.
All these receipts require timezone-aware collection times within 300 seconds;
expiry, missing fields, old protocol, or mismatch stops recovery. The controller
must collect from actual HTTP/systemd/probe, approve the exact binding SHA, and
never synthesize receipts from strings or disk hashes. No actual receipt is
included in this source artifact. The 300-second limit is an admission proof
lifetime, not a pricing, collection, schedule, or public-readback policy change.

The original recovery/proof guard remains unchanged: original failure evidence,
bounded fresh two-round readback, all CAS/source checks, no business POST or price
replay, and unknown terminal status after uncertain final publication. Gallery
and pricing policy are untouched. Nine new native tests are prepared but skipped
on Windows; old v3 76/76 does not cover this new input. releaseReady=false.
