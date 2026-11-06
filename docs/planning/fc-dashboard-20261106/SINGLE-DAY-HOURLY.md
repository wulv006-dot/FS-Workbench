# FC single-day sales trends implementation plan

**Goal:** A single selected day automatically shows hourly order/sales and category sales trends; retain the existing daily shipping margin presentation.

**Spec:** User screenshot and 2026-11-06 clarification: “利润率无需按小时精确展示，可以保留现在形式，其他两个要改”. Existing whole-order category and shipping-profit contracts remain authoritative.

**Architecture:** Reuse the complete Admin-paid dataset already held in the FC snapshot. `fc_dashboard.project` adds `hourly_trend` for a single day without another source capture, keeping the daily query, original trend and export unchanged. Three frontend entries use this field only for the two sales charts, retaining the RS chart style.

**Approaches:** Existing date-only `grain=hour` requests can share the cached dataset but require a second browser request and matching snapshot/watermark state. Adding an hourly projection in the same response keeps both charts on one snapshot and is the implementation choice. Neither approach requires 24 upstream requests or another full backlog capture.

**Constraints:** Asia/Shanghai payment hours; unique whole-order category priority; no Admin profit substitution; no future-hour zeros; incomplete/unknown amounts and time coverage remain explicit; unchanged permissions and global selection. Only `fc_dashboard.py`, three JS entries and directly related tests change.

## Tasks

- [x] Backend: Write and observe failing projection tests; add hourly sales/category rows from the same dataset; cover closed day, current cutoff, missing data and unchanged daily margin/export. Seven new tests plus 61 existing tests passed.
- [x] Frontend: Write and observe renderer failures; adapt the two charts in all three entries while daily margin, overview, rings, filters and URL retain day semantics; verify missing data and permission transitions. Twelve targeted checks per entry passed; related visual, native metric and FC flow regression checks passed. Independent review found and resolved the partial-hour tooltip mismatch.
- [ ] Integration: Run related backend and renderer suites, independent diff review and the existing latest-base `pr-fast` CI; merge only this task PR under existing authorization.
- [ ] Release: Build exact five-target proposal (three immutable JS, navigation's three JS aliases, existing `fc_dashboard.py`), preserve CSS and other protected files; use the original runtime maintenance, backup/CAS/rollback chain.
- [ ] Acceptance: Read actual single-day API hourly projection and real charts, verify daily margin retained and filters/caches consistent; record actual release and remaining limitations separately.

## Review focus

Today ends at the source collection cutoff; old cached raw datasets gain the projection without recapture. Incomplete days must not become a full zero-filled chart. The category ring remains daily while its trend becomes hourly. Specified products remain filtered and hide cross-project comparison. Changing back to a multi-day selection or losing permission must not retain an old hourly chart.
