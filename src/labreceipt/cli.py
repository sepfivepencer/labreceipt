"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from labreceipt.canonical import canonical_bytes
from labreceipt.contracts import Contract, contract_from_dict, load_contract
from labreceipt.engine import verify
from labreceipt.errors import LabReceiptError
from labreceipt.model import confirm_contract, propose_contract
from labreceipt.receipts import load_receipt, receipt_bytes
from labreceipt.safeio import exclusive_write, preflight_output


def _example_contract() -> Contract:
    return contract_from_dict(
        {
            "artifacts": [
                {"depends_on": [], "id": "report", "max_bytes": 65536, "path": "report.txt"}
            ],
            "contract_id": "first_delivery",
            "rules": [
                {"artifact": "report", "config": {}, "id": "report_exists", "type": "exists"},
                {"artifact": "report", "config": {}, "id": "report_utf8", "type": "utf8"},
                {
                    "artifact": "report",
                    "config": {"needle": "Conclusion"},
                    "id": "has_conclusion",
                    "type": "text_contains",
                },
                {
                    "artifact": "report",
                    "config": {},
                    "id": "no_embedded_secret",
                    "type": "secret_scan",
                },
            ],
            "schema_version": "1",
            "status": "candidate",
        }
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labreceipt")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="write an offline candidate contract")
    init.add_argument("--out", type=Path, required=True)

    validate = subparsers.add_parser("validate", help="validate and identify a contract")
    validate.add_argument("contract", type=Path)

    confirm = subparsers.add_parser("confirm", help="record explicit human confirmation")
    confirm.add_argument("candidate", type=Path)
    confirm.add_argument("--reviewed-by", required=True)
    confirm.add_argument("--out", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify", help="verify a confirmed contract")
    verify_parser.add_argument("contract", type=Path)
    verify_parser.add_argument("--workspace", type=Path, default=Path("."))
    verify_parser.add_argument("--previous", type=Path)
    verify_parser.add_argument("--out", type=Path, required=True)

    impact = subparsers.add_parser("impact", help="show invalidated artifacts and rules")
    impact.add_argument("contract", type=Path)
    impact.add_argument("--workspace", type=Path, default=Path("."))
    impact.add_argument("--previous", type=Path, required=True)

    propose = subparsers.add_parser("propose", help="ask an opted-in model for a candidate")
    propose.add_argument("brief", type=Path)
    propose.add_argument("--endpoint", required=True)
    propose.add_argument("--model", required=True)
    propose.add_argument("--api-key-env", default="LABRECEIPT_API_KEY")
    propose.add_argument("--timeout", type=float, default=10.0)
    propose.add_argument("--allow-network", action="store_true")
    propose.add_argument("--out", type=Path, required=True)
    return parser


def _write_contract(path: Path, contract: Contract) -> None:
    exclusive_write(path, canonical_bytes(contract.to_dict()) + b"\n")


def _safe_print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def run(args: argparse.Namespace) -> int:
    """Run an already parsed command."""
    if args.command == "init":
        preflight_output(args.out)
        contract = _example_contract()
        _write_contract(args.out, contract)
        _safe_print({"contract_id": contract.contract_id, "status": contract.status})
        return 0
    if args.command == "validate":
        contract = load_contract(args.contract)
        _safe_print(
            {
                "contract_id": contract.contract_id,
                "sha256": contract.digest,
                "status": contract.status,
            }
        )
        return 0
    if args.command == "confirm":
        preflight_output(args.out)
        contract = confirm_contract(load_contract(args.candidate), args.reviewed_by)
        _write_contract(args.out, contract)
        _safe_print({"contract_id": contract.contract_id, "status": contract.status})
        return 0
    if args.command in {"verify", "impact"}:
        if args.command == "verify":
            preflight_output(args.out)
        contract = load_contract(args.contract)
        previous = load_receipt(args.previous) if args.previous is not None else None
        result = verify(contract, args.workspace, previous)
        if args.command == "impact":
            _safe_print(result.receipt["impact"])
            return 0
        exclusive_write(args.out, receipt_bytes(result.receipt))
        _safe_print(
            {
                "receipt_id": result.receipt["receipt_id"],
                "summary": result.receipt["summary"],
            }
        )
        return 0 if result.passed else 1
    if args.command == "propose":
        preflight_output(args.out)
        contract = propose_contract(
            args.brief,
            endpoint=args.endpoint,
            model=args.model,
            allow_network=args.allow_network,
            api_key_env=args.api_key_env,
            timeout=args.timeout,
        )
        _write_contract(args.out, contract)
        _safe_print({"contract_id": contract.contract_id, "status": contract.status})
        return 0
    raise AssertionError("argparse accepted an unknown command")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and return a process exit code."""
    try:
        return run(_parser().parse_args(argv))
    except LabReceiptError as exc:
        print(f"labreceipt: {exc}", file=sys.stderr)
        return 2
