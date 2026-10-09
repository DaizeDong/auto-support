# auto-support, Design Philosophy

## Restrict the material used to answer

A product support assistant can expose private implementation details if answering a question
also grants access to the whole repository. The selected public documentation therefore defines
the knowledge boundary. Retrieval and the host hook check the requested path and its resolved
target; deny rules take precedence. This reduces available material before an answer is composed.

Path checks, input detection and egress checks run outside the model. They enforce concrete
contracts that a prompt instruction cannot enforce. They still depend on host hook coverage and
correct policy configuration; the plugin is not an operating-system sandbox or a general proof
that every possible secret will be detected.

## Require attributable evidence and accept refusal

The shipped CLI accepts unchanged retrieved excerpts and matching citations. That limits answer
coverage and phrasing, but permits a direct check against the selected public source. Retrieval
misses and uncertain document scope produce neutral refusals instead of answers from memory.
Large prose sections use a bound interpretation from installed `llmcall`; exact source ranges
establish provenance, while interpretation quality still needs independent evaluation.

## Treat dispatch as a stateful operation

A request to escalate is not a send receipt. Confirmed relay success starts cooldown; an uncertain
response retains private reconciliation state so a retry cannot silently duplicate a delivery.
The state belongs in a PRIVATE versioned companion, and storage prerequisites are checked before
dispatch. Storage admission requires a unique source-owned artifact declaration. Configuration
and runtime discovery select the same companion, keeping policy inspection and output aligned
when a higher-priority selector is set. The reminder bridge requires an explicitly initialized
scheduler database.

## Keep evidence appropriate to the claim

Generated canaries and synthetic regression cases exercise local paths, DLP and receipt handling.
They cannot establish a deployment's listener, host permissions, live relay or model effectiveness.
Those integrations require separate checks on the intended setup before enabling non-draft use.
Public documentation describes the reusable controls and their limits; private product policy
and operational observations remain in the companion.
