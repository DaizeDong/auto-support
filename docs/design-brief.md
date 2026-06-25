# Design Brief — auto-support

> Produced by skill-smith (research-first). Step 0 recon for this build is the seven-route study
> captured in `_skill-builds/05-auto-support/ARCHITECTURE.md` (OWASP RAG/LLM, Anthropic Claude
> Code security docs, Microsoft Spotlighting, Lakera Gandalf/D-SEC, AgentDojo, promptfoo/garak,
> Gitleaks/TruffleHog, AWS grounding/abstention). This brief is the auditable distillation.

## Best references (match-or-beat)
- OWASP RAG Security Cheat Sheet (14 controls) + OWASP LLM01/02/06 — knowledge-boundary + DLP.
- Anthropic Claude Code docs (permissions/hooks/sandboxing) — guards outside the prompt.
- Microsoft Spotlighting (arXiv 2403.14720) + Prompt Shields — untrusted-input isolation.
- Lakera D-SEC/Gandalf (AFR/SCR/APE) + AgentDojo + promptfoo/garak — adjudication + CI red-team.
- Gitleaks/Secrets-Patterns-DB vs TruffleHog — secret detection routes.
- AWS grounding/abstention blog + RAGAS faithfulness — have-evidence-or-abstain.

## Frontier ideas to incorporate
- Defense-in-depth (no single guard is complete) + codified abstention (escalate as the only
  fallback) + structured-output canary fields as policy-violation probes.

## Anti-patterns to avoid
- Prompt-only guards; `allowed-tools` as a limit; `permissions.deny` alone; full-code exposure;
  answer-from-memory on retrieval miss; keyword-only leak filters; LLM-judge as sole guard;
  committing auto-revoke keys; echoing scores/paths/refusal-reasons to users; full-channel listen.

## Proof bar (how we show it is tested-real)
- Canary red-team: AFR = 100% (zero canary leaks, independent canary adjudication) + SCR >= 95% +
  escalation recall + boundary classification + injection (base64/leet/zero-width/typoglycemia/
  role-claim). Local: **31/31 pytest pass** on the synthetic mock project. This is the self-evolve
  regression signal (Provider A: programmatic/pytest).

## Scope & focus (one job, <=3 modules)
- One job: leak-safe product Discord support answering. Three faces: (1) leak/injection guardrails,
  (2) grounded answer pipeline, (3) escalation + state via reused bases. Not a general chatbot.
