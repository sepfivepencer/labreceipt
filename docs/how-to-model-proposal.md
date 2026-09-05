# How to draft a contract with a local model

This guide connects LabReceipt to an OpenAI-compatible endpoint, saves the response as a candidate, and keeps verification behind a separate human action.

## Prerequisites

- A local model server with an OpenAI-compatible chat-completions endpoint
- A model name accepted by that server
- A UTF-8 task brief with no credentials
- LabReceipt installed

LabReceipt has not been validated against a specific model server. Check your server's request and response format before using this adapter.

## Steps

1. Start the model server according to its own documentation. Assume its endpoint is `http://127.0.0.1:8000/v1/chat/completions`.

2. Write a bounded task brief.

   ```bash
   cp examples/model-brief.txt brief.txt
   ```

3. Request a candidate contract.

   ```bash
   labreceipt propose brief.txt \
     --endpoint http://127.0.0.1:8000/v1/chat/completions \
     --model qwen2.5:7b \
     --allow-network \
     --out candidate.json
   ```

   LabReceipt sends one system message and the brief with temperature `0`. It rejects redirects and responses larger than 512 KiB. A valid response must use the OpenAI chat-completions shape and place a single JSON contract in `choices[0].message.content`.

4. Validate and inspect the candidate.

   ```bash
   labreceipt validate candidate.json
   python -m json.tool candidate.json
   ```

   Check paths, dependency edges, byte limits, and every rule. The adapter forces `status` to `candidate` and removes any reviewer that the model tried to assert.

5. Confirm the reviewed contract.

   ```bash
   labreceipt confirm candidate.json \
     --reviewed-by alice \
     --out contract.json
   ```

6. Verify the deliverables.

   ```bash
   labreceipt verify contract.json --workspace delivery --out receipt.json
   ```

## Remote HTTPS endpoint

Set a key in the environment and keep it out of command history:

```bash
export LABRECEIPT_API_KEY='replace-with-your-provider-key'
labreceipt propose brief.txt \
  --endpoint https://models.example/v1/chat/completions \
  --model approved-model \
  --allow-network \
  --out candidate.json
```

The endpoint may omit authentication. Change the environment variable name with `--api-key-env SAFE_API_KEY`; the name must use uppercase letters, digits, and underscores and end in `_API_KEY` or `_TOKEN`. LabReceipt never reads a key until you opt into network access.

## Verification

Run `labreceipt validate contract.json`. It should print `status` as `confirmed`. Running `verify` on `candidate.json` must exit `2` and leave no receipt.

## Troubleshooting

- **`model access is disabled`**: add `--allow-network` after checking the endpoint.
- **`unencrypted model endpoints are limited to loopback hosts`**: use HTTPS for a non-local host.
- **`task brief contains a recognized secret`**: remove the credential and rotate it if it was real.
- **`model response lacks chat completion content`**: point the command at a compatible chat-completions route.
- **`contract ... invalid`**: ask the model for a simpler contract, then validate it again. LabReceipt accepts only the rule types in the [reference](reference.md).
- **Output already exists**: choose a new path. LabReceipt does not overwrite candidates, contracts, or receipts.
