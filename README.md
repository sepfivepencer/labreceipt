# LabReceipt

LabReceipt checks whether an AI agent delivered the files a human approved. A JSON contract names the artifacts, their dependency edges, and deterministic rules. The verifier emits a content-free evidence receipt with artifact digests, rule outcomes, and the exact evidence invalidated by a later change.

The verifier runs offline and executes no shell command. An optional OpenAI-compatible adapter can draft a **candidate** contract. A person must confirm that candidate before verification accepts it.

## Five-minute offline run

Install Python 3.10 or newer, then run:

```bash
python -m pip install -e '.[dev]'
mkdir demo && cd demo
printf 'Conclusion: accepted\n' > report.txt
labreceipt init --out candidate.json
labreceipt confirm candidate.json --reviewed-by alice --out contract.json
labreceipt verify contract.json --workspace . --out receipt.json
```

The last command exits `0` and writes `receipt.json`. Remove `Conclusion` from `report.txt`, choose a new output path, and rerun the verifier to see a failed rule. LabReceipt never overwrites an existing output.

## What it contributes

- **Human-gated acceptance:** model output can only become a `candidate`; `verify` accepts `confirmed` contracts with a reviewer label.
- **Dependency-aware evidence:** changing an input invalidates its artifact and every transitive dependent, so a reviewer can see which checks lost their prior basis.
- **Deterministic receipts:** the same confirmed contract, bytes, and prior-receipt input produce the same canonical JSON and `receipt_id`. Receipts contain hashes and bounded diagnostics, not artifact contents.
- **Small, auditable rule surface:** nine built-in checks cover existence, size, hash, UTF-8, text, line count, JSON shape, JSON Pointer values, and high-confidence secret patterns.

LabReceipt recalculates every rule on each run. A prior receipt informs impact analysis but cannot authorize a pass. This prevents an unsigned, user-editable receipt from becoming a cache of trusted results.

## Safety boundaries

- Workspace paths must be portable relative paths. The reader opens each component with no-follow semantics and rejects symbolic links, traversal, directories, and oversized files.
- Receipt and contract outputs use exclusive creation with mode `0600`. Existing files and symlinked parent directories fail closed.
- Remote model calls require `--allow-network`. Plain HTTP works only on loopback; redirects, URL credentials, query strings, and fragments are rejected. API keys come from an environment variable.
- Contract metadata and model briefs pass through high-confidence secret detectors. Reports name detector classes and never include matching text.
- Inline JSON Schema uses Draft 2020-12. LabReceipt blocks schema references and regular-expression keywords in version 0.1 to bound resolution and regex risks.

The self-digest detects accidental receipt changes only when someone has pinned the expected digest. It is not a signature, timestamp, trusted execution record, or proof that `reviewed_by` names the person who performed the review. Dependency impact is trustworthy only to the extent that the prior receipt is trustworthy. See [the design explanation](docs/explanation-design.md).

Content digests reveal when two artifacts are equal, and an attacker can guess a low-entropy file and compare its digest. Treat receipts as review records, not as anonymized data.

## Example with dependency impact

```bash
labreceipt verify examples/dependency-contract.json \
  --workspace examples/workspace \
  --out first-receipt.json
```

After changing `examples/workspace/data.csv`, rerun with `--previous first-receipt.json` and a new output path. The receipt marks both `data` and its dependent `report` as invalidated, then evaluates every rule against current bytes.

## Documentation

- [Tutorial: first evidence receipt](docs/tutorial-first-receipt.md)
- [How to draft a contract with a local model](docs/how-to-model-proposal.md)
- [CLI, contract, rule, and Python reference](docs/reference.md)
- [Design, threat model, and prior-art boundary](docs/explanation-design.md)

## Competition status

The [2026 AI Hangzhou “码动未来” super-agent track](https://aichallenge.msup.com.cn/tracks) asks entrants to demonstrate task understanding, planning, tool use, and directly acceptable deliverables. Its [official schedule](https://aichallenge.msup.com.cn/) lists 19 September 2026 as the preliminary submission and team-registration deadline. LabReceipt addresses the deliverable-acceptance slice. This repository has not connected to an official contest platform, run a real model, registered a team, or submitted an entry.

The specific combination of human-gated contract proposals, transitive evidence invalidation, and deterministic content-free receipts is the project hypothesis. Nearby systems cover overlapping needs: [OpenAI Evals](https://github.com/openai/evals) and [Inspect](https://inspect.aisi.org.uk/) evaluate models and agents; [in-toto](https://in-toto.io/) and [SLSA attestations](https://slsa.dev/spec/v1.2/attestation-model) record software provenance; [JSON Schema](https://json-schema.org/draft/2020-12/json-schema-core) validates JSON structure. LabReceipt does not claim to replace them or to be the first possible implementation. A repository-name and package-name search cannot establish trademark clearance or absolute originality.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
mypy src/labreceipt
pytest --cov=labreceipt --cov-report=term-missing
python -m build
```

Version 0.1 is an alpha release for local, POSIX workspaces. Read the [reference](docs/reference.md) before using receipts in a consequential review.
