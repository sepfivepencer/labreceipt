# Build your first evidence receipt

You will define one deliverable, confirm its acceptance criteria, and produce a receipt without a model or network connection. The exercise takes about five minutes.

## What you need

- Python 3.10 or newer on macOS or Linux
- A checkout of this repository
- A shell in the repository root

## Step 1: Install LabReceipt

```bash
python -m pip install -e '.[dev]'
```

Check the command:

```bash
labreceipt --help
```

You should see the `init`, `confirm`, `verify`, `impact`, `validate`, and `propose` commands.

## Step 2: Create a deliverable and candidate contract

```bash
mkdir tutorial-workspace
cd tutorial-workspace
printf 'Conclusion: the experiment passed.\n' > report.txt
labreceipt init --out candidate.json
```

The last command prints `{"contract_id":"first_delivery","status":"candidate"}`. The candidate requires `report.txt`, valid UTF-8, the word `Conclusion`, and no recognized high-confidence secret.

## Step 3: Review and confirm

Read `candidate.json`. If its four rules match your request, record your review:

```bash
labreceipt confirm candidate.json --reviewed-by alice --out contract.json
```

The reviewer field accepts a lowercase identifier such as a team handle. It records an assertion; it does not authenticate a person.

## Step 4: Verify the current files

```bash
labreceipt verify contract.json --workspace . --out receipt-1.json
```

The command exits `0`. Its summary reports four passed rules. Open `receipt-1.json` and note that it contains the file path, byte count, digest, and rule results. It does not contain the report text.

## Step 5: See evidence invalidation

Change the deliverable, then compare it with the first receipt:

```bash
printf 'The experiment needs another run.\n' > report.txt
labreceipt verify contract.json \
  --workspace . \
  --previous receipt-1.json \
  --out receipt-2.json
```

The command exits `1` because `has_conclusion` fails. `receipt-2.json` lists `report` under `changed_artifacts` and all four report rules under `invalidated_rules`. LabReceipt evaluates every rule again against the current file.

## What you built

You now have a human-confirmed contract and two deterministic receipts that explain why the second delivery failed. Continue with the [rule and receipt reference](reference.md), or read [how to use a local model for contract drafting](how-to-model-proposal.md).
