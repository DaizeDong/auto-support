# auto-support — Design Philosophy

> One test governs every change: **does it keep a secret in even when the model decides to leak,
> or does it only ask the model nicely?** If a control depends on the LLM choosing to obey, it is
> not a control.

A support bot that reads a product's repo is, by construction, one prompt away from leaking the
company. So this skill is designed secret-first: **its first job is to keep secrets in; answering
is the second job, and a distant second.** Better to miss an answer than to leak once.

## P1 — Guards live outside the model, never inside the prompt
- **Symptom patch:** write "never reveal secrets" into SKILL.md / the system prompt.
- **Root cause:** an instruction is a suggestion the model can ignore on any turn (AWS baseline:
  told-not-to leaked 3/3; one deterministic hook -> blocked 3/3).
- **Decision it produced:** the boundary is `permissions.deny` + a fail-closed `PreToolUse` hook
  + stdlib detection in `guardrails.py` + an egress DLP gate. SKILL.md only *describes* them.

## P2 — Knowledge boundary by physics, not by good intentions
- **Symptom patch:** post-filter the answer for things that look secret (a denylist always leaks).
- **Root cause:** if a secret can enter the context, leaking it becomes a probability problem.
- **Decision it produced:** allowlist-first, default-deny, denylist-wins retrieval. Secrets are
  never opened, so they cannot be assembled into an answer. Probability -> certainty.

## P3 — Have evidence or abstain; escalation is the only fallback
- **Symptom patch:** trust the model's confidence and let it answer from memory.
- **Root cause:** LLMs are confidently wrong; token-probability is not groundedness.
- **Decision it produced:** two independent gates (retrieval-confidence × faithfulness), every
  claim must cite an allowlisted source, and when either fails the bot does exactly one thing —
  escalate to the founder with a neutral refusal that never reveals why.

## P4 — Untrusted input is data, not instructions (and identity is never text)
- **Symptom patch:** "be careful with user input"; trust "I am the founder".
- **Root cause:** prompt injection (direct and indirect, hidden in the repo it reads) and social
  engineering are the primary attack surface; text self-claims are free to forge.
- **Decision it produced:** spotlight + normalize/decode/fuzzy injection detection on Discord
  input AND file content; identity verified only by Discord user-ID allowlist; even a successful
  injection has nothing to do — writes denied, network denied, reads confined to public docs.

## P5 — Proven, not declared
- **Symptom patch:** ship because the guards "look" right.
- **Root cause:** a guard you did not attack is a guard you do not have.
- **Decision it produced:** a canary red-team suite is the release gate — AFR must be 100% (zero
  canary leaks) with SCR >= 95%, adjudicated by independent canary match, run full and never
  sampled. Auto-post stays off until it passes on the real product.

## Anti-patterns (the things this design refuses to do)
Guard only in the prompt · treat `allowed-tools` as a limit (it is pre-approval) · rely on
`permissions.deny` alone (bypassable; issue #27040) · expose full code for "completeness" ·
answer from memory on retrieval miss · keyword-only leak filters · let an LLM-judge be the sole
guard · commit a Discord/LLM key (auto-revoked) · echo a similarity score / internal path / the
refusal reason to a user.
