# Roadmap

Current: **v0.1.2**

## Current implementation

The declared release remains v0.1.2. [Unreleased changes](CHANGELOG.md#unreleased) record later
main-branch behavior; older release entries retain their historical meaning.

- Resolve a product's public documentation policy and return cited excerpts or a neutral refusal.
- Apply path, input, grounding and egress checks. Large prose sections require a bound scope
  interpretation through installed `llmcall`; missing or uncertain interpretation causes refusal.
- Keep drafting, escalation requests and confirmed delivery distinct. Uncertain sends retain
  reconciliation state and must be inspected before retrying.
- Prove PRIVATE versioned storage before persistence and keep the scheduler bridge behind its
  explicit database-initialization requirement.

Current main shares doctor/runtime companion discovery, validates declared escalation outputs
and retains operator incident records under an explicit recovery contract.

## Deployment acceptance still required

- Validate host permissions and hook coverage for the actual client. The plugin does not install
  an operating-system sandbox, and local checks cannot establish another host's boundary.
- Configure and verify a Discord listener, secret provisioning, review workflow and relay delivery
  where those integrations are needed. A generated draft does not establish any of them.
- Validate scope interpretation and answer usefulness independently on authorized public docs.
  Deterministic synthetic responses do not measure the configured model's effectiveness.
- A paraphrasing generator requires a separately verified integration; the shipped CLI accepts
  unchanged retrieved excerpts with matching citations.

No automatic-posting capability is enabled merely by completing an offline test suite.
