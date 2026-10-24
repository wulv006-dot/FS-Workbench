# C catalog gaps — FS-V3-G1-COMPLETE-GAPS-04

Base: `29ed99af85dc4aa7a302e63ae36c06e5da495369`. Dedicated worktree `campaign-gaps-c`, branch `codex/fs-campaign-v3-gaps-catalog`. This change modifies only catalog mapping logic, new catalog tests/read-only tools and catalog evidence artifacts. It does not modify bridge/adapters, application clients, old PR434/head/stage, shared session code or production.

## Consumable result

The single runtime-consumable artifact is [backend/catalog-mapping.json](../../../../releases/fs-dashboard/campaign-analytics-20261023/backend/catalog-mapping.json). It contains one entry per `reference_key` under `mappings`; no second large copy is stored in handoffs. All entries retain `available:false`, `authoritative:false`, `checkout_enabled:false`.

| Coverage | Result |
| --- | ---: |
| Original reference rows | 96 |
| Unique site/game/goods identities | 86 |
| Games | 6 |
| Current metadata observed and linked to model | 96 references / 86 goods / 34 models |
| Explicit empty selectable-property tables | 81 references |
| Actual `more.gold` quantity tiers mapped | 15 references / 5 goods |
| Original page status guard fails (`status=0`) | 6 references |
| Live available / checkout enabled | 0 / 0 |

Reference game counts: FC 81; NBA, Madden, Diablo, PoE and Aion 3 each. FC includes the 78 original player/SBC/bundle platform rows and 3 Seasonal coin amount rows. Goods, model, platform, server and category are kept as distinct namespaces. Every original quantity remains unchanged; `K`, `M` and empty source units are preserved without multiplying quantities, changing prices or inventing an item unit for FC's unknown backend unit.

The 6 failed original status guards are `fc-185718875-{ps,xbox,pc}` and `fc-185833159-{ps,xbox,pc}`. Their current `status` is 0; this differs from the original public FC adapter's required `status==1`. Raw `buy_status`, `attr_switch`, `sku_switch` and `auto_off` are retained independently; unknown enum meaning is not guessed from a switch name.

## Actual SKU/quantity findings

The first GET projection observed 81 empty `more.saleprop` and `more.skuTableSet` containers. The 5 currency goods had neither selected field in `more`; that first projection did **not** establish absence of purchase specifications. A second probe was limited to those 5 goods and 5 related models, with zero public reads. It located actual `more.gold` amount arrays:

| Goods | Model | Observed unit | Original selected quantities |
| --- | --- | --- | --- |
| 163329311 (FC) | 41217957 | K | 100 / 500 / 1000 |
| 165466529 (NBA) | 42278471 | K | 50 / 150 / 300 |
| 159812737 (Madden) | 39467507 | K | 100 / 300 / 600 |
| 1365865 (Diablo) | 5264 | M | 100000 / 300000 / 600000 |
| 178594601 (Aion) | 17815737 | M | 10 / 30 / 100 |

The mapping records each original amount's exact position in the **goods** amount table as `quantity.selected_tier.source_index/value/source_path`. The array index is evidence provenance, **not a fabricated SKU ID**, and is never written into `product_ref.sku_id`. No actual nonempty `saleprop` or native SKU-ID table was observed by these probes. Nonempty saleprop/skuTableSet input is now projected as bounded IDs/values/structure rather than merely counted, but unknown serialization remains unresolved.

Aion's goods and model amount arrays differ. Goods contains 10/30/100; model contains only 100 of those three original selections. Both arrays are preserved, and all three references carry `QUANTITY_TIER_PRECEDENCE_UNVERIFIED`. This change does not silently treat the model as a restriction, assume a goods override, replace the selected quantities or declare the main site unsupported.

## Server contract

`campaign_backend.catalog` exports:

- `build_reference_mappings(seed, evidence, supplement=None)` — consumes only projected GET evidence, validates scoped identities and observation consistency, returns the artifact.
- `read_reference_mapping(artifact, reference_key=None)` — checks content hash, safe schema, capability flags and summary. With no key it returns `{schema_version,mapping_version,summary,source_evidence,evidence_file_hashes,mappings,authoritative:false,checkout_enabled:false}`; with a key it returns that row or `CATALOG_REFERENCE_NOT_FOUND`.
- `validate_purchase_mapping(mapping, selection)` — validates original product/model/platform identity and unchanged reference quantity against metadata; rejects invented SKU/attributes and extra monetary fields. Its result always keeps availability/authority/checkout false. It is **not** an adapter for cart serialization or an authorization to purchase.
- `read_product_metadata(...)` remains backward compatible, adding safe observed nonempty specification structures, `quantity_observation`, `selection_schema`, goods/model quantity tiers and unresolved precedence reasons.

Management integration belongs to B/controller: load JSON from a **server-controlled** configured path (default adjacent to `bridge.py` as `catalog-mapping.json`), then call `read_reference_mapping`. A browser may supply only `reference_key`, never a file path or mapping data. Missing/invalid files must return an honest unavailable/mapping error, not sample data. Use the existing FS authentication/role/Origin/CSRF boundary; this module does not add routes or alter roles.

Public seed integration belongs to the controller. Only overlay observed `product_ref.model_id` and safe metadata/specification evidence for the exact `reference_key`; do not promote availability, change original quantities/prices/platforms, use a tier index as SKU ID or expose raw Admin rows.

## Evidence and repeatable tools

The generated [C-CATALOG-SEED-04.json](C-CATALOG-SEED-04.json) is the complete original 96-reference identity/quantity list with original artifact hashes. [C-CATALOG-SKU-TARGETS-04.json](C-CATALOG-SKU-TARGETS-04.json) is the 15-reference/5-goods targeted subset, derived from the first probe's `sku_switch=1` observations.

Controller-provided projected evidence (original PC SSH, not executed by C):

| Input | Actual UTC / scope | File SHA256 |
| --- | --- | --- |
| `inputs/gap-catalog-evidence-04.json` | 2026-10-24 10:30:56; 86 goods, 34 cached models; exit0 | `be8af211257f91068c21fca8423e96956d58da963a29219523ad4dcdbdf9ecbe` |
| `inputs/gap-catalog-sku-evidence-04.json` | 2026-10-24 10:34:00–10:34:07; only 5 currency goods + 5 models; exit0 | `78568c15de030b039eae4ffcdfc285fd53b4bbeef72ac0ef268c8c7ea408b235` |

The artifact also records canonical-object hashes and the seed/artifact file hashes. Evidence inputs are local sanitized receipts; this change does not commit raw HTML, JS, Admin responses or shared credentials.

```powershell
python tools/campaign_catalog_seed.py --out docs/planning/activity-center-v3/handoffs/C-CATALOG-SEED-04.json
python tools/campaign_catalog_mapping.py --evidence D:/codex/2026-10-24/task/inputs/gap-catalog-evidence-04.json --supplement D:/codex/2026-10-24/task/inputs/gap-catalog-sku-evidence-04.json --out releases/fs-dashboard/campaign-analytics-20261023/backend/catalog-mapping.json
```

`tools/campaign_catalog_probe.py` can be exec'd in memory and `run_probe(seed)` called by the controller through the existing SSH route. It reuses the shared owner session, allows only two Admin GET detail routes and fixed public GET pages/scripts, caches goods/models including failures, and spaces requests by at least 0.2 seconds (default 0.35). The targeted invocation is `run_probe(target_seed, read_public=False)`. There is no POST, login, arbitrary URL, file write, raw-response output or retry of an unknown mutation. Output is limited to identity, purchase/specification fields, field types, enums and hashes; prices/costs/customer/order/token/environment data are excluded.

## Remaining exact gaps

All 9 public purchase-page reads were unresolved and returned no projected JS evidence. The sanitized receipt did not retain the specific HTTP/network cause. Therefore this work cannot verify the current public JS/hidden controls' cart category, `attr` encoding, quantity-tier serialization, effective goods-versus-model precedence, quantity step/upper bound or enum semantics. It does not infer that those fields/features are absent. No alternative URL, public-read retry or access workaround was attempted by C.

Main-site authoritative quote, identity/cart handoff, coupon stacking and checkout remain separate unverified capabilities. The artifact provides complete **metadata coverage**, not complete live purchase mapping. Production, merge, push and apply were not executed. The prior merge refusal is known not to have executed; this task did not retry or work around it.

Validation: catalog/probe tests exercise exact 96/86/6 coverage, real committed evidence, empty/nonempty specs, tier values/indices, Aion divergence, scope drift, quantity/type conflicts, missing public evidence, safe outputs, artifact corruption, failed-read cache and persistent disabled capability flags. Full backend test command: `python -m unittest discover -s tests -p 'test_*.py' -v` from the module's `backend/` directory.
