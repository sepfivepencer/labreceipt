# Why LabReceipt separates planning from acceptance

An autonomous agent may write a polished report while missing the requested dataset, schema, or conclusion. A second model can grade that report, but the same ambiguity remains: a probabilistic judge can accept plausible text without checking the exact artifact bytes. LabReceipt gives a human a deterministic acceptance boundary after the agent plans the work.

## The problem

Three failures recur in agent delivery workflows:

1. The agent invents easy criteria after seeing its own output.
2. A source file changes, but a derived report keeps a stale “passed” badge.
3. A log records enough raw output to leak data or credentials.

The project treats acceptance criteria as a separate artifact. A model may draft them, but a human must move the contract from `candidate` to `confirmed` before verification starts.

## The approach

```text
task brief
    |
    | optional, explicit network access
    v
model proposal --> candidate.json --> human review --> contract.json
                                                   |
delivery files --> no-follow reader ---------------+
                                                   v
                                     deterministic built-in rules
                                                   |
prior receipt --> digest comparison --> dependency invalidation
                                                   |
                                                   v
                                      content-free receipt.json
```

The contract graph points from an input to artifacts derived from it. LabReceipt compares current artifact state, size, and digest with a prior receipt. A changed node invalidates every dependent through a transitive closure. The receipt names each affected rule even when the rule's target bytes did not change.

The verifier still evaluates every rule. The prior receipt carries a self-digest, not a signature, so it cannot serve as an authenticated cache. Recalculation keeps the final verdict tied to current bytes.

## Determinism

Canonical JSON sorts object keys, uses compact separators, preserves Unicode, and rejects non-finite numbers. The receipt omits clocks, host names, absolute workspace paths, model prose, and artifact content. Identical contract bytes, artifact bytes, and prior-receipt input produce an identical `receipt_id` under the same LabReceipt version.

That property supports reproducible review. It does not prove who ran the command or when they ran it. A reviewer who needs authenticated provenance should sign and distribute the receipt through a separate system. A forged but self-consistent prior receipt can misstate which artifacts changed, although it cannot make current failing rules pass because the verifier recalculates them.

## Threat model

LabReceipt assumes an untrusted model response, untrusted workspace paths, and mistakes in contract metadata. It defends its own process against:

- path traversal and symbolic-link escape;
- unbounded files, contracts, responses, and network waits;
- output replacement through normal existing paths or final-component symlinks;
- redirects that could forward an authorization header;
- recognized secrets in model briefs, contracts, and evidence details;
- arbitrary command execution through acceptance rules.

Version 0.1 targets POSIX file semantics. It does not sandbox another agent, stop that agent from changing files during a run, detect every secret, authenticate reviewers, sign receipts, or protect a machine where the verifier process is already compromised. A file can change after its descriptor is opened; the receipt describes the bytes read from that descriptor.

## Trade-offs

Built-in rules reduce expressiveness. Users cannot run test commands, plugins, remote schema resolution, or schema regular expressions. This constraint makes the default verifier small enough to audit and removes a common path from an AI-authored contract to code execution.

Content-free receipts improve privacy but make a failed report less convenient to debug. Stable reason codes and counts identify the failing check; the reviewer must inspect the local artifact for details.

Artifact digests disclose equality and permit guessing attacks against small or predictable files. Reviewers must still control receipt distribution when artifact presence or content guesses are sensitive.

Human confirmation creates friction. It also prevents a model from defining success and claiming success in one step. The `reviewed_by` field records only a label because authentication would require a key and identity policy outside this local tool.

## Relationship to existing work

[JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-core) defines JSON document structure. LabReceipt embeds a restricted schema check alongside file and dependency checks.

[OpenAI Evals](https://github.com/openai/evals) and [Inspect](https://inspect.aisi.org.uk/) evaluate models or agent systems with datasets, solvers, and scorers. LabReceipt checks one concrete delivery after a human approves its contract; it does not benchmark a model.

[in-toto](https://in-toto.io/) records software supply-chain steps, and the [SLSA attestation model](https://slsa.dev/spec/v1.2/attestation-model) defines authenticated statements about software artifacts. LabReceipt borrows the idea of binding metadata to content digests. Its local receipts remain unsigned and make no SLSA claim.

The [2026 AI Hangzhou “码动未来” super-agent track](https://aichallenge.msup.com.cn/tracks) scores task understanding, planning, tool interaction, deliverable acceptance, and end-to-end value. LabReceipt implements the acceptance boundary and a model-assisted planning seam. A contest entry still needs a real model, useful tools, a complete user workflow, team eligibility, and the required submission materials.

The project claims this narrow combination as an experiment, not a proven first. Search results can miss private code, unpublished work, renamed packages, and trademarks in other jurisdictions.

## Alternatives considered

- **Let the model grade its output:** simple, but it joins criterion creation and judgment in one probabilistic step.
- **Cache unchanged rule outcomes:** faster, but unsafe without authenticated prior receipts.
- **Run user commands from the contract:** flexible, but an AI-authored file becomes a command-execution channel.
- **Store excerpts in the receipt:** easier to debug, but it raises disclosure risk and breaks the content-free boundary.

Read the [reference](reference.md) for exact limits and the [model proposal guide](how-to-model-proposal.md) for the opt-in network flow.
