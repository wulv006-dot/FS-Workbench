# Focused consistency check for the FC dashboard category contract and Hermes index.
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = Path("docs/planning/fc-dashboard-category-20261106/CONTRACT.md")
CONTRACT_ID = "fc-dashboard-category-v1-20261106"
ENTRY_ID = "fc.dashboard.category"


def normalized_sha256(path: Path) -> str:
    content = (ROOT / path).read_bytes().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def main() -> None:
    contract = (ROOT / CONTRACT).read_text(encoding="utf-8")
    required = [
        CONTRACT_ID,
        "全部商品、金币、球员卡、SBC、Packs、其他",
        "球员卡 > SBC > Packs > 其他 > 金币",
        "Order 订单号",
        "交易时间",
        "Admin 付款销售额",
        "唯一记录ID",
        "缺失成本",
        "全部商品",
        "details/summary",
        "部署和真实加载",
    ]
    missing = [token for token in required if token not in contract]
    if missing:
        raise SystemExit(f"FC dashboard contract is missing required clauses: {missing}")

    index = json.loads((ROOT / "knowledge/index.json").read_text(encoding="utf-8"))
    matches = [entry for entry in index["entries"] if entry.get("id") == ENTRY_ID]
    if len(matches) != 1:
        raise SystemExit(f"expected one {ENTRY_ID} entry, found {len(matches)}")
    entry = matches[0]
    if entry.get("revision") != CONTRACT_ID or entry.get("layer") != "candidate" or entry.get("status") != "candidate":
        raise SystemExit("Hermes knowledge entry must remain the matching candidate revision")
    source = entry.get("source", {})
    if source.get("path") != str(CONTRACT).replace("\\", "/"):
        raise SystemExit("Hermes knowledge source must point to the FC contract")
    if source.get("sha256") != normalized_sha256(CONTRACT) or source.get("hash_basis") != "utf8_lf":
        raise SystemExit("Hermes knowledge source hash does not match the UTF-8/LF contract")
    print("FC dashboard contract and Hermes candidate index are consistent.")


if __name__ == "__main__":
    main()
