from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from labreceipt.cli import main


def test_init_writes_candidate(tmp_path: Path, capsys: Any) -> None:
    output = tmp_path / "candidate.json"
    assert main(["init", "--out", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "candidate"
    assert json.loads(capsys.readouterr().out)["status"] == "candidate"


def test_init_refuses_overwrite(tmp_path: Path, capsys: Any) -> None:
    output = tmp_path / "candidate.json"
    output.write_text("old")
    assert main(["init", "--out", str(output)]) == 2
    assert "overwrite is disabled" in capsys.readouterr().err
    assert output.read_text() == "old"


def test_validate_reports_digest(tmp_path: Path, capsys: Any) -> None:
    candidate = tmp_path / "candidate.json"
    assert main(["init", "--out", str(candidate)]) == 0
    capsys.readouterr()
    assert main(["validate", str(candidate)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["sha256"].startswith("sha256:")


def test_confirm_then_verify_offline(tmp_path: Path, capsys: Any) -> None:
    candidate = tmp_path / "candidate.json"
    contract = tmp_path / "contract.json"
    receipt = tmp_path / "receipt.json"
    (tmp_path / "report.txt").write_text("Conclusion: accepted\n")
    assert main(["init", "--out", str(candidate)]) == 0
    assert main(["confirm", str(candidate), "--reviewed-by", "alice", "--out", str(contract)]) == 0
    assert (
        main(
            [
                "verify",
                str(contract),
                "--workspace",
                str(tmp_path),
                "--out",
                str(receipt),
            ]
        )
        == 0
    )
    assert json.loads(receipt.read_text())["summary"]["verdict"] == "pass"
    assert "receipt_id" in capsys.readouterr().out


def test_verify_candidate_fails_closed(tmp_path: Path, capsys: Any) -> None:
    candidate = tmp_path / "candidate.json"
    receipt = tmp_path / "receipt.json"
    assert main(["init", "--out", str(candidate)]) == 0
    assert main(["verify", str(candidate), "--out", str(receipt)]) == 2
    assert not receipt.exists()
    assert "must be reviewed" in capsys.readouterr().err


def test_verify_returns_one_for_failed_rule(tmp_path: Path, capsys: Any) -> None:
    candidate = tmp_path / "candidate.json"
    contract = tmp_path / "contract.json"
    receipt = tmp_path / "receipt.json"
    (tmp_path / "report.txt").write_text("No required heading")
    assert main(["init", "--out", str(candidate)]) == 0
    assert main(["confirm", str(candidate), "--reviewed-by", "alice", "--out", str(contract)]) == 0
    result = main(
        [
            "verify",
            str(contract),
            "--workspace",
            str(tmp_path),
            "--out",
            str(receipt),
        ]
    )
    assert result == 1
    assert json.loads(receipt.read_text())["summary"]["failed"] == 1
    capsys.readouterr()


def test_impact_uses_prior_receipt(tmp_path: Path, capsys: Any) -> None:
    candidate = tmp_path / "candidate.json"
    contract = tmp_path / "contract.json"
    receipt = tmp_path / "receipt.json"
    (tmp_path / "report.txt").write_text("Conclusion\n")
    main(["init", "--out", str(candidate)])
    main(["confirm", str(candidate), "--reviewed-by", "alice", "--out", str(contract)])
    main(
        [
            "verify",
            str(contract),
            "--workspace",
            str(tmp_path),
            "--out",
            str(receipt),
        ]
    )
    capsys.readouterr()
    assert (
        main(
            [
                "impact",
                str(contract),
                "--workspace",
                str(tmp_path),
                "--previous",
                str(receipt),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["changed_artifacts"] == []


def test_propose_requires_network_opt_in(tmp_path: Path, capsys: Any) -> None:
    brief = tmp_path / "brief.txt"
    brief.write_text("safe")
    result = main(
        [
            "propose",
            str(brief),
            "--endpoint",
            "https://example.test/v1/chat/completions",
            "--model",
            "model",
            "--out",
            str(tmp_path / "out.json"),
        ]
    )
    assert result == 2
    assert "disabled" in capsys.readouterr().err


def test_propose_checks_output_before_model_access(tmp_path: Path, capsys: Any) -> None:
    brief = tmp_path / "brief.txt"
    brief.write_text("safe")
    output = tmp_path / "out.json"
    output.write_text("old")
    result = main(
        [
            "propose",
            str(brief),
            "--endpoint",
            "https://example.test/v1/chat/completions",
            "--model",
            "model",
            "--allow-network",
            "--out",
            str(output),
        ]
    )
    assert result == 2
    assert "overwrite" in capsys.readouterr().err
    assert output.read_text() == "old"


def test_validate_invalid_json_returns_two(tmp_path: Path, capsys: Any) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not-json")
    assert main(["validate", str(bad)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_validate_oversized_integer_returns_two_without_traceback(
    tmp_path: Path, capsys: Any
) -> None:
    bad = tmp_path / "large-number.json"
    bad.write_text("1" * 5001)
    assert main(["validate", str(bad)]) == 2
    captured = capsys.readouterr()
    assert "digit limit" in captured.err
    assert "Traceback" not in captured.err
