# Security model, why the guards live OUTSIDE the prompt

The single most important fact: **a guardrail written into SKILL.md or a system prompt is a
suggestion the model may ignore on any turn.** AWS's own baseline showed an LLM told "never
reveal secrets" leaking 3/3 times; adding one deterministic `PreToolUse` hook made it 3/3
blocked. So every guarantee here is a deterministic check the model cannot argue away.

## The four gates (defense in depth, no single gate is trusted)

```
Discord msg ─▶ [0/1 entry] injection+intent (spotlighted)  ─ hit ▶ escalate
            ─▶ [2 retrieval] allowlist-only, secret-scrubbed ─ empty ▶ abstain+escalate
            ─▶ [3 grounding] retrieval-conf × faithfulness   ─ low ▶ abstain+escalate
            ─▶ [4 egress] schema+DLP+canary+citation         ─ hit ▶ block+escalate
            ─▶ draft ─▶ founder review ─▶ approve ─▶ user
```

Every gate is **fail-closed**: the only outputs to a user are a grounded, cited answer or one
neutral refusal line (`这个问题我无法确定，已转交团队跟进。`). The refusal never states *why*
(boundary probing defense).

## Knowledge boundary = allowlist-first, default-deny, denylist wins

We do not enumerate "what not to say" (a denylist always leaks). We define "only answer from
these public sources" and make everything else physically unreachable:

- `guardrails.path_verdict(path, allow, deny)` order: **denylist hit -> DENY** (a secret path
  loses even if also allowlisted); **allowlist hit -> ALLOW**; **otherwise -> DENY**.
- `retrieval.py` only ever opens allowlisted files, and secret-scrubs each snippet before it can
  enter context, so a misfiled key in an "allowed" doc still never reaches the model.

## Three physical layers (the model literally cannot read a secret)

| Layer | Mechanism | Closes |
|---|---|---|
| permissions | `settings.json` `permissions.deny` Read/Bash on secret globs + deny all write/net | built-in tools |
| hook | `pretooluse_hook.py` (exit 2, fail-closed on parse error) | the subprocess gap (`python open('.env')`, `cat .env`) that `permissions.deny` misses (+ issue #27040 where deny was skipped) |
| OS sandbox | `filesystem.denyRead` (covers ALL child processes), deferred on Win11 (no native sandbox), run under WSL2/devcontainer for full depth | residual subprocess reads |

`allowed-tools` is **not** a restriction, Anthropic states it is pre-approval; capability is
narrowed only by `deny` + hook + sandbox. Never use `--dangerously-skip-permissions`.

## Detection primitives (`guardrails.py`, all stdlib, all testable in CI)

- **secrets:** precise regex (OpenAI/Anthropic/AWS/Stripe/GitHub/Slack/Google/Discord token+webhook/
  JWT/PEM/DB-URL/generic assignment/canary) + Shannon-entropy pass for unknown formats. Matches are
  reported by rule name + salted hash prefix, **the raw secret is never returned or logged.**
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
