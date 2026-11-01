"""B-side coverage of observed attachment pages, scoped to one task book.

Retains only file/version, row intervals and read-receipt times, never cells or
customer records. Coverage is not an access grant or a business freshness claim.
"""
from copy import deepcopy
from datetime import datetime, timezone
import re
import threading


class MaterialEvidence:
    def __init__(self, clock=None, *, scope="turn_bound_files"):
        if scope not in ("turn_bound_files", "material_execution_files"):
            raise ValueError("material_evidence_scope")
        self.scope = scope
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self.files = {}
        self.lock = threading.RLock()

    @staticmethod
    def merge(intervals):
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        return merged

    def observe_page(self, value, request):
        """Observe only a matching, coherent selected-sheet page from A.

Malformed/unknown results are returned as unverified, not promoted to evidence.
Existing conflicting version/dimension observations invalidate that file's union.
"""
        fid = request["file_id"]
        with self.lock:
            def reject(reason, invalidate=False):
                if invalidate and fid in self.files:
                    self.files[fid]["invalid"] = reason
                return {"status": "unverified", "file_id": fid, "reason": reason,
                        "workbook_complete": False}
            if value.get("status") not in (None, "available", "ok"):
                return reject("source_outcome_not_available")
            sha, coverage = value.get("sha256"), value.get("coverage")
            if value.get("file_id") != fid or not isinstance(sha, str) or not re.fullmatch("[a-f0-9]{64}", sha):
                return reject("file_version_unverified")
            old = self.files.get(fid)
            if old and old["sha256"] != sha:
                return reject("file_version_conflict", invalidate=True)
            if old and old.get("invalid"):
                return reject(old["invalid"])
            if not isinstance(coverage, dict) or coverage.get("scope") != "selected_sheet":
                return reject("coverage_scope_unverified")
            keys = ("sheet", "offset", "end_exclusive", "total_rows", "returned_rows", "total_sheets")
            if any(type(coverage.get(k)) is not int for k in keys):
                return reject("page_dimensions_unverified")
            sheet, start, end, total, received, sheet_count = (coverage[k] for k in keys)
            if (sheet != request["sheet"] or start != request["offset"] or sheet_count < 1
                    or not 0 <= sheet < sheet_count or not 0 <= start <= end <= total
                    or received != end-start or not 0 <= received <= request["limit"]):
                return reject("page_dimensions_unverified")
            sheets = value.get("sheets")
            if (not isinstance(sheets, list) or len(sheets) != 1 or not isinstance(sheets[0], dict)
                    or not isinstance(sheets[0].get("rows"), list) or len(sheets[0]["rows"]) != received):
                return reject("page_rows_unverified")
            expected_complete = start == 0 and end == total
            next_offset = value.get("next_offset")
            if (type(coverage.get("complete")) is not bool or coverage["complete"] != expected_complete
                    or type(value.get("complete")) is not bool or value["complete"] != expected_complete
                    or next_offset != (end if end < total else None)
                    or (next_offset is not None and type(next_offset) is not int)
                    or (received == 0 and end < total)):
                return reject("page_coverage_unverified")
            if old and (old["total_sheets"] != sheet_count or
                        (sheet in old["sheets"] and old["sheets"][sheet]["total_rows"] != total)):
                return reject("file_dimensions_conflict", invalidate=True)
            item = old or {"sha256": sha, "total_sheets": sheet_count, "sheets": {}}
            page = item["sheets"].setdefault(sheet, {"total_rows": total, "intervals": []})
            page["intervals"] = self.merge(page["intervals"] + [(start, end)])
            item["read_at"] = self.clock()
            self.files[fid] = item
            return self._summary(fid, item)

    def _summary(self, fid, item):
        if item.get("invalid"):
            return {"status": "unverified", "file_id": fid, "sha256": item["sha256"],
                    "reason": item["invalid"], "workbook_complete": False, "read_at": item["read_at"]}
        observed = []
        for sheet, page in sorted(item["sheets"].items()):
            cursor, gaps = 0, []
            for start, end in page["intervals"]:
                if start > cursor:
                    gaps.append([cursor, start])
                cursor = max(cursor, end)
            if cursor < page["total_rows"]:
                gaps.append([cursor, page["total_rows"]])
            observed.append({"sheet": sheet, "total_rows": page["total_rows"],
                             "covered_rows": sum(end-start for start, end in page["intervals"]),
                             "missing_ranges": gaps, "complete": not gaps})
        unread = item["total_sheets"] - len(observed)
        return {"status": "observed", "scope": ("this_execution_observed_pages" if self.scope == "material_execution_files"
                                                  else "this_turn_observed_pages"), "file_id": fid,
                "sha256": item["sha256"], "total_sheets": item["total_sheets"],
                "observed_sheets": observed, "unread_sheet_count": unread,
                "workbook_complete": unread == 0 and all(s["complete"] for s in observed),
                "read_at": item["read_at"], "time_basis": "tool_read_receipt_not_business_data_date"}

    def summaries(self):
        with self.lock:
            return deepcopy([self._summary(fid, item) for fid, item in sorted(self.files.items())])

    def handoff_evidence(self):
        """B1-compatible small evidence references, not table or chat copies."""
        result = []
        for item in self.summaries():
            missing = (["business_data_not_read", "long_term_goal_not_assessed"]
                       if self.scope == "material_execution_files" else [])
            if item["status"] == "unverified":
                missing.append(item["reason"])
            else:
                if item["unread_sheet_count"]:
                    missing.append("unread_sheets:" + str(item["unread_sheet_count"]))
                for sheet in item["observed_sheets"]:
                    missing.extend("sheet:%s:rows:%s:%s" % (sheet["sheet"], start, end)
                                   for start, end in sheet["missing_ranges"])
            result.append({"ref": "file:" + item["file_id"] + "@" + item["sha256"],
                           "source": ("material_execution_files" if self.scope == "material_execution_files"
                                      else "turn_file_tool_read_receipt"), "as_of": item["read_at"],
                           "version": item["sha256"], "missing": missing,
                           "coverage": "workbook_observed" if item["workbook_complete"] else "partial_or_unverified"})
        return result
