# Discord integration — minimal-intent listener, explicit trigger, human-review reply

## Minimal intents (privacy by design)
Enable only `Guilds` + `GuildMessages`. Add the privileged `MessageContent` intent ONLY if the
bot must read non-mention messages; do NOT enable `Presence`/`GuildMembers`. Set
`allowed_mentions = {parse: []}` so a reply can never @-ping a user/role. Without `MessageContent`
the bot only sees @mentions / replies-to-bot / DMs — which is the natural trigger gate anyway.

## Trigger gate (explicit first; full-channel listening is an anti-pattern)
1. **Hard gate:** respond only to @mention / reply-to-bot / a designated support channel/thread.
2. **Soft gate:** `answer_pipeline.classify_intent` -> bounded enum
   {`product_usage_question`, `chitchat`, `off_topic`, `sensitive_or_injection`, `unclear`}:
   - product_usage_question -> grounded answer flow (4 gates)
   - chitchat/off_topic -> cancel (no retrieval, no LLM exposure)
   - sensitive_or_injection/unclear -> escalate
Full-channel listening pulls every user's PII/chatter into the model and widens the injection
surface — never do it.

## Reply form = human-in-the-loop (MVP)
`reply_mode`: `relay_only` (push question+draft to founder; human answers) or
`draft_human_review` (bot drafts -> founder review channel -> 👍/approve -> bot posts). Approval
rules: verify the approver by **Discord user-ID allowlist** (never message text); use **raw
reaction events** (survive bot restart); idempotent on `message_id+user_id+emoji`; audit every
approve. **Auto-post stays off until `reference/redteam.md` passes on the real product.**

## Rate / noise control
Discord ~50 req/s global; per-route buckets; on 429 honor `Retry-After` (exp backoff + jitter).
App layer: per-user cooldown + per-channel throttle + `message_id` idempotency (gateway redelivery).
The biggest noise cut is the explicit trigger gate + intent enum — unwanted messages never enter
the answer flow.

## Tooling boundary
This bot needs exactly three capabilities: local read-only retrieval, Discord post-reply, founder
relay. Expose Discord as a controlled MCP server; `deny` `mcp__*` broadly then allow only the
specific verbs (e.g. `mcp__discord__post_reply`) via `AUTO_SUPPORT_MCP_ALLOW`. No write/delete/
payment/arbitrary-HTTP tools — `pretooluse_hook.py` denies them deterministically.
