"""Frozen pre-fix flow; pure offline fixture for duplicate session reproduction."""
def collect():
    config = {}
    with sync_playwright() as playwright:
        browser = open_backend(playwright)
        if len(browser.contexts) != 1:
            raise ValueError("browser_context_ambiguous")
        tab = browser.contexts[0].new_page()
        primary_error = None
        try:
            login(tab, config)
            found = {}
            observations = []
            for number in range(1, 16):
                data = read_page(tab, number, observations)
                for raw in data["rows"]:
                    valid = valid_record(raw)
                    if not valid:
                        continue
                    traded, record = valid
                    platform = record["platform"]
                    if platform not in found or traded > found[platform][0]:
                        found[platform] = (traded, record)
                if not data["hasDataRows"] or data["empty"]:
                    break
            checked_at = datetime.now(timezone.utc).isoformat()
            records = []
            for platform in PLATFORMS:
                if platform in found:
                    records.append({**found[platform][1], "checked_at": checked_at})
                else:
                    records.append({"platform": platform, "status": "missing",
                                    "reason": "no_valid_recent_record"})
            return {"status": "valid" if all(r["status"] == "valid" for r in records) else "incomplete",
                    "checked_at": checked_at, "costs": records, "page_observations": observations}
        except Exception as exc:
            primary_error = exc
            raise
        finally:
            try:
                close_backend(tab)
            except Exception:
                if primary_error is None:
                    raise
