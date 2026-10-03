# Security model, why the guards live OUTSIDE the prompt

The single most important fact: **a guardrail written into SKILL.md or a system prompt is a
suggestion the model may ignore on any turn.** AWS's own baseline showed an LLM told "never
reveal secrets" leaking 3/3 times; adding one deterministic `PreToolUse` hook made it 3/3
blocked. This implementation places checks outside the model. Host enforcement still needs
deployment verification; local tests cannot establish arbitrary-host containment.

## The four gates (defense in depth, no single gate is trusted)

```
Discord msg ─▶ [0/1 entry] injection+intent (spotlighted)  ─ hit ▶ escalate
            ─▶ [2 retrieval] allowlist-only, secret-scrubbed ─ empty ▶ abstain+escalate
            ─▶ [3 grounding] retrieval-conf × faithfulness   ─ low ▶ abstain+escalate
            ─▶ [4 egress] schema+DLP+canary+citation         ─ hit ▶ block+escalate
            ─▶ draft ─▶ founder review ─▶ approve ─▶ user
```

Every gate is **fail-closed**: the only outputs to a user are a grounded, cited answer or one
neutral refusal line (`这个问题我无法确定，请联系团队进一步确认。`). The refusal never states *why*
(boundary probing defense).

## Knowledge boundary = allowlist-first, default-deny, denylist wins

We do not enumerate "what not to say" (a denylist always leaks). We define "only answer from
these public sources" and validate access against that boundary:

- `guardrails.path_verdict(path, allow, deny)` order: **denylist hit -> DENY** (a secret path
  loses even if also allowlisted); **allowlist hit -> ALLOW**; **otherwise -> DENY**.
- Retrieval and the hook bind requested and resolved paths to the selected public root.
  `Grep` and `Glob` require explicit search roots and reject mixed public/private directories.
- Both paths reject multiply linked regular documents, including aliases whose other link
  is outside the public root. Retrieval checks again on the opened descriptor before reading.
  Hook approval is a point-in-time check; it does not replace an OS sandbox.
- `retrieval.py` retains entire Markdown section subtrees, including multiline code, with the
  document preamble. Consecutive peer sections of at most 4,000 characters form one procedure
  unit regardless of their wording, language or query overlap. Markdown structure stays in
  that unit even when oversized: fenced or indented code, numbered steps, lists including
  empty items, blockquotes including tight markers and lazy continuations, nested headings,
  tables, references and inline markup. Tabs use four-column stops for classification only;
  source indentation, line endings and command arguments remain intact. Raw HTML blocks
  make the entire file one unit because embedded Markdown-looking lines are ambiguous.
  Unsupported section syntax stays in a larger intact unit; unfinished fences or comments
  are not usable evidence.
  Every selected unit and its required context must fit the total snippet and character
  budgets. A skipped matching unit makes the draft abstain, with an internal diagnostic.
  Large plain-prose peers are provisional chapter boundaries. Separating groups requires
  `semantic_scope.py` to submit the entire admitted document through installed
  `llmcall.call(prompt, schema=...)`, using its configured default judge policy. The source is
  screened for detected secrets, PII and injection before submission. Every unordered section
  pair needs a definite interpretation bound to the original document digest and each section's
  key, range and digest, with endpoint evidence and an explanation. Missing, malformed, stale,
  incomplete, uncertain or failed interpretations make matching evidence unusable.
  Local preambles and explicit same-document links remain in the source graph. Required
  relationships add directed dependencies, and extraction takes their transitive closure before
  applying the retrieval budget. Oversized required context causes abstention. Exact binding
  proves provenance and response structure; a model can still misinterpret a relationship.
  Synthetic test responses establish integration only. Real-model effectiveness and arbitrary
  implicit or external-document dependencies have not been established. Interpretations stay
  in memory and returned graphs; installed llmcall retains its private operational logging policy.
- Whole units are scanned for secrets and injection before entering answer context. Unsafe
  context invalidates the unit instead of leaving an incomplete instruction. Detector coverage
  is limited to its supported patterns. Invalid UTF-8 is rejected without replacement text.
- The retrieval CLI reports `complete` and `snippets` in its JSON result. Incomplete matching
  evidence returns exit 2 with `complete=false` and an empty snippets list. The draft pipeline
  also refuses incomplete results; a usable match cannot hide another omitted matching source.
- The draft pipeline accepts only literal complete spans with matching structured citations,
  preserving original whitespace and source order. Omitting required context rejects the draft.
  Returned citations identify only excerpts actually used, including their line numbers.
  Query relevance is calculated from those emitted cited excerpts; unused retrieval hits
  cannot make an irrelevant answer appear relevant.
  Lexical similarity alone cannot prove units, negation or additional facts. All five answer
  fields are required: response text, escalation boolean, public citations, an empty internal
  path list, and a false secret canary. Missing fields and wrong types reject the answer.

## Deployment layers and their scope

| Layer | Mechanism | Closes |
|---|---|---|
| permissions | `settings.json` `permissions.deny` Read/Bash on secret globs + deny all write/net | built-in tools |
| hook | `pretooluse_hook.py` (exit 2, fail-closed on parse error) | the subprocess gap (`python open('.env')`, `cat .env`) that `permissions.deny` misses (+ issue #27040 where deny was skipped) |
| OS sandbox | `filesystem.denyRead` (covers ALL child processes), deferred on Win11 (no native sandbox), run under WSL2/devcontainer for full depth | residual subprocess reads |

`allowed-tools` is **not** a restriction, Anthropic states it is pre-approval; capability is
narrowed only by `deny` + hook + sandbox. Never use `--dangerously-skip-permissions`.

The hook requires the host's `permission_mode` field on every `PreToolUse` event.
It accepts `default`, `plan`, `acceptEdits`, `auto` and `dontAsk`, then applies the same
read-only tool boundary in every mode. `bypassPermissions`, missing metadata, malformed
values and unknown modes block before any tool is admitted. See the official
[hook input contract](https://code.claude.com/docs/en/hooks#common-input-fields).
If a runner defaults to permission bypass or omits this field, configure that runner
to preserve host permissions before deployment. Do not remove the check to accommodate it.
This check only runs when the host dispatches the hook. Verify discovery and dispatch in
the actual host, including a permitted public read and denied secret read, write and network
attempts. Directly piping JSON into the script verifies its protocol, not native host dispatch.

## Detection primitives (`guardrails.py`, all stdlib, all testable in CI)

- **secrets:** precise regex (OpenAI/Anthropic/AWS/Stripe/GitHub/Slack/Google/Discord token+webhook/
  JWT/PEM/DB-URL/generic assignment/canary) + Shannon-entropy pass for unknown formats. Matches are
  reported by rule name + the first 12 hexadecimal digits of unsalted SHA-256; the raw match
  is not returned. These deterministic prefixes allow correlation and guesses from likely
  inputs, and the truncated values can collide. They do not provide anonymization or encryption.
- **PII:** email/SSN/phone/credit-card(Luhn)/IPv4.
- **injection:** normalize (NFKC, strip zero-width, leetspeak, punctuation) + decode embedded
  base64/hex + anagram (typoglycemia) + fuzzy match against an injection/jailbreak/exfil phrase set
  and identity-claim set; plus markdown image/link exfil-channel detection. Runs on Discord input
  **and** on file content (indirect injection hides in README/comments/filenames).
- **spotlighting:** wrap untrusted content in random delimiters; the system prompt declares the
  delimited region is DATA, never instructions (Microsoft, arXiv 2403.14720).

## Anti-patterns (do not do these)

Guard only in the prompt · treat `allowed-tools` as a limit · rely on `permissions.deny` alone
(bypassable) · expose full code for "completeness" · answer from memory when retrieval is empty ·
keyword-only leak filters (base64/leet/entropy bypass) · let an LLM-judge be the sole guard (it is
injectable) · reveal similarity scores / internal paths / the refusal reason to users.
