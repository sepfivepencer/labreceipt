# LabReceipt reference

This page specifies the version 0.1 command line, contract format, rules, receipt fields, limits, and Python API.

## Command line

### `labreceipt init --out PATH`

Creates an offline `candidate` contract for `report.txt`. The candidate contains four rules: `exists`, `utf8`, `text_contains` for `Conclusion`, and `secret_scan`. The command creates `PATH` with mode `0600` and refuses an existing path.

### `labreceipt validate CONTRACT`

Loads and validates a candidate or confirmed contract. It prints compact JSON containing `contract_id`, `sha256`, and `status`.

### `labreceipt confirm CANDIDATE --reviewed-by ID --out PATH`

Changes a valid candidate to `confirmed` and records `ID`. The ID must match `^[a-z][a-z0-9_-]{0,63}$`. This operation records an assertion and provides no identity authentication.

### `labreceipt verify CONTRACT [--workspace PATH] [--previous RECEIPT] --out PATH`

Reads every declared artifact, evaluates every rule, calculates dependency impact, and writes a sealed receipt. `--workspace` defaults to the current directory. `--previous` must contain a self-consistent receipt from the same contract and LabReceipt version. Pin or authenticate the prior receipt outside LabReceipt before relying on its impact comparison.

### `labreceipt impact CONTRACT --workspace PATH --previous RECEIPT`

Runs current verification and prints only `changed_artifacts`, `invalidated_artifacts`, and `invalidated_rules`. It does not write a receipt.

### `labreceipt propose BRIEF --endpoint URL --model NAME --allow-network --out PATH`

Sends `BRIEF` to an OpenAI-compatible chat-completions endpoint. Options:

| Option | Type | Default | Constraint |
|---|---|---|---|
| `--endpoint` | URL | required | HTTPS, or HTTP on `localhost`, `127.0.0.1`, or `::1`; no user info, query, or fragment |
| `--model` | string | required | 1 to 128 characters matching `[A-Za-z0-9][A-Za-z0-9._:/-]*` |
| `--allow-network` | flag | off | Required for local and remote endpoints |
| `--api-key-env` | env-var name | `LABRECEIPT_API_KEY` | `^[A-Z][A-Z0-9_]{0,63}$` and suffix `_API_KEY` or `_TOKEN` |
| `--timeout` | seconds | `10.0` | `0.1` through `30.0` |
| `--out` | path | required | New file only |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Command completed; for `verify`, all rules passed |
| `1` | Verification completed and one or more rules failed |
| `2` | Contract, input, safety, network, or output error |

## Contract format

The root object accepts these fields and rejects unknown fields:

| Field | Type | Required | Constraint |
|---|---|---|---|
| `schema_version` | string | yes | Exactly `"1"` |
| `contract_id` | string | yes | Safe lowercase identifier, at most 64 characters |
| `status` | string | yes | `candidate` or `confirmed` |
| `reviewed_by` | string | confirmed only | Safe lowercase identifier |
| `proposal` | object | no | Model provenance with `kind`, `provider`, and `model` |
| `artifacts` | array | yes | 1 through 256 unique artifacts |
| `rules` | array | yes | 1 through 1024 unique rules |

A contract file may contain at most 1 MiB of UTF-8 JSON. The parser rejects duplicate keys, integers longer than 1,024 digits, non-finite numbers, more than 4,096 nested JSON nodes, and depth over 32. It combines valid UTF-16 surrogate pairs from JSON escapes and rejects every unpaired surrogate in strings and object keys. A high-confidence secret match anywhere in contract metadata rejects the contract.

### Artifact object

| Field | Type | Required | Constraint |
|---|---|---|---|
| `id` | string | yes | Unique safe identifier |
| `path` | string | yes | Unique POSIX-style relative path; no empty, `.`, `..`, backslash, or symlink component |
| `depends_on` | string array | yes | Unique known artifact IDs; graph must be acyclic |
| `max_bytes` | integer | yes | 1 through 16,777,216 |

An artifact dependency means: “the dependent artifact's evidence loses its prior basis when this input changes.” If `report` depends on `data`, a changed `data` artifact invalidates both nodes and every rule on either node.

### Rule object

Every rule has a unique safe `id`, a supported `type`, an `artifact` ID, and a `config` object.

| Type | Config | Pass condition |
|---|---|---|
| `exists` | `{}` | Artifact is a readable regular file within its byte limit |
| `sha256` | `{"expected":"sha256:<64 lowercase hex>"}` | Current content digest equals `expected` |
| `max_bytes` | `{"limit":N}` | Current size is at most `N` |
| `utf8` | `{}` | Bytes decode as strict UTF-8 |
| `text_contains` | `{"needle":"..."}` | UTF-8 text contains a 1 to 256 byte literal |
| `line_count` | `{"min":N,"max":N}` | `splitlines()` count lies within the inclusive bounds; either bound may be omitted |
| `json_schema` | `{"schema":{...}}` | JSON instance validates under Draft 2020-12 |
| `json_pointer_equals` | `{"pointer":"/path","expected":...}` | RFC 6901-style pointer resolves and its JSON value equals `expected` |
| `secret_scan` | `{}` | Content contains none of the built-in high-confidence patterns |

Version 0.1 rejects `$ref`, `$dynamicRef`, `pattern`, and `patternProperties` anywhere in an inline JSON Schema. It does not enable JSON Schema format checking.

`json_pointer_equals` compares arrays and objects recursively. JSON booleans remain distinct from numbers, so `true` does not equal `1` and `false` does not equal `0`. JSON numbers compare by mathematical value, so `1`, `1.0`, and `1e0` are equal.

`secret_scan` recognizes AWS access-key IDs, GitHub token prefixes, OpenAI-style `sk-` keys, and private-key headers. It returns detector names and counts, not matched text. It cannot find every credential and may produce false positives.

## Receipt format

LabReceipt encodes receipts as sorted-key, compact UTF-8 JSON followed by a newline.

| Field | Content |
|---|---|
| `receipt_id` | SHA-256 of the canonical receipt body, prefixed with `sha256:` |
| `schema_version` | `"1"` |
| `contract` | Contract ID and canonical contract digest |
| `engine` | Package name and version |
| `artifacts` | ID, relative path, state, byte count, and content digest; never content |
| `evidence` | Rule ID/type, artifact ID, pass/fail, stable code, bounded details, and execution marker |
| `impact` | Direct changes, transitive artifact invalidations, and invalidated rules |
| `summary` | Evaluated, reused, pass, and failure counts plus verdict |
| `workspace` | Digest of the public artifact metadata set |

`reused` is always zero in version 0.1. The verifier recalculates rules because a self-digest does not authenticate a prior receipt.

Artifact states are `ok`, `missing`, `too_large`, `unsafe_path`, or `unreadable`. Receipt files may contain at most 4 MiB when reused as `--previous`.

## Python API

```python
from pathlib import Path

from labreceipt import Contract, LabReceiptError, load_contract, verify

contract: Contract = load_contract(Path("contract.json"))
result = verify(contract, Path("delivery"))
print(result.passed)
print(result.receipt["receipt_id"])
```

Public names:

- `load_contract(path: Path) -> Contract`
- `verify(contract: Contract, workspace: Path, previous: dict[str, Any] | None = None) -> Verification`
- `LabReceiptError`, the safe expected-error base class
- `Contract.to_dict() -> dict[str, Any]`
- `Contract.digest -> str`

The typed `Contract`, `ArtifactSpec`, `RuleSpec`, and `Verification` values are frozen dataclasses. See the [tutorial](tutorial-first-receipt.md) for a complete command-line flow and the [design explanation](explanation-design.md) for security limits.
