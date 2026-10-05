"""Reconstruct reviewed HTML locally using a private, external runtime payload.

This tool never uploads, deploys, fetches data, or accepts authentication material.
"""
from pathlib import Path
import argparse
import hashlib
import json

MARKER = b"__PRIVATE_PROFIT_JSON__"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(template_path, payload_path, output_path, contract_path, repo_root):
    repo = Path(repo_root).resolve()
    payload = Path(payload_path).resolve()
    output = Path(output_path).resolve()
    if payload.is_relative_to(repo) or output.is_relative_to(repo):
        raise ValueError("private payload and output must remain outside the candidate")
    if output.exists():
        raise FileExistsError("output already exists; choose a new external path")
    contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
    template = Path(template_path).read_bytes()
    data = payload.read_bytes()
    if sha(template) != contract["templateSha256"]:
        raise ValueError("template hash mismatch")
    if sha(data) != contract["privatePayloadSha256"]:
        raise ValueError("private payload hash mismatch")
    if template.count(MARKER) != 1:
        raise ValueError("template must contain exactly one private payload marker")
    if not isinstance(json.loads(data), dict):
        raise ValueError("private payload must be a JSON object")
    result = template.replace(MARKER, data)
    if sha(result) != contract["restoredHtmlSha256"]:
        raise ValueError("reconstructed HTML differs from the reviewed release")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(result)
    return {"sha256": sha(result), "bytes": len(result), "deployed": False}


def main():
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-profit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build(repo / "共享资源/MMOEXP统一看板/dashboard.template.html",
                   args.private_profit, args.output,
                   repo / "docs/provenance/restored-v7.json", repo)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
