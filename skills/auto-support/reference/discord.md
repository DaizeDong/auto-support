# Discord integration, minimal-intent listener, explicit trigger, human-review reply

## Minimal intents (privacy by design)
Enable only `Guilds` + `GuildMessages`. Add the privileged `MessageContent` intent ONLY if the
bot must read non-mention messages; do NOT enable `Presence`/`GuildMembers`. Set
`allowed_mentions = {parse: []}` so a reply can never @-ping a user/role. Without `MessageContent`
the bot only sees @mentions / replies-to-bot / DMs, which is the natural trigger gate anyway.

## Trigger gate (explicit first; full-channel listening is an anti-pattern)
1. **Hard gate:** respond only to @mention / reply-to-bot / a designated support channel/thread.
2. **Soft gate:** `answer_pipeline.classify_intent` -> bounded enum
   {`product_usage_question`, `chitchat`, `off_topic`, `sensitive_or_injection`, `unclear`}:
   - product_usage_question -> grounded answer flow (4 gates)
   - chitchat/off_topic -> cancel (no retrieval, no LLM exposure)
   - sensitive_or_injection/unclear -> escalate
Full-channel listening pulls every user's PII/chatter into the model and widens the injection
surface, never do it.

## Reply form = human-in-the-loop (MVP)
`reply_mode`: `relay_only` (push question+draft to founder; human answers) or
`draft_human_review` (bot drafts -> founder review channel -> 👍/approve -> bot posts). Approval
rules: verify the approver by **Discord user-ID allowlist** (never message text); use **raw
reaction events** (survive bot restart); idempotent on `message_id+user_id+emoji`; audit every
approve. **Auto-post stays off until `reference/redteam.md` passes on the real product.**

## Rate / noise control
Discord ~50 req/s global; per-route buckets; on 429 honor `Retry-After` (exp backoff + jitter).
App layer: per-user cooldown + per-channel throttle + `message_id` idempotency (gateway redelivery).
The biggest noise cut is the explicit trigger gate + intent enum, unwanted messages never enter
the answer flow.

## Tooling boundary
This bot needs exactly three capabilities: local read-only retrieval, Discord post-reply, founder
relay. Use a controlled MCP server and select only the exact relay capability needed in the
active host. `mcp__discord__post_reply` in the template is an example; verify the actual callable
name before deployment.

The product settings template uses normal permission mode and places the selected exact relay
in `permissions.ask`. Set `AUTO_SUPPORT_MCP_ALLOW` to that same exact name for the mandatory
`pretooluse_hook.py` check. The hook rejects every unlisted MCP tool; wildcard entries do not
match tool names. Do not add a wildcard MCP allow, enable bypass mode or disable the hook.
Other MCP read/write/delete/payment/arbitrary-HTTP capabilities remain outside this allowlist.

Claude Code evaluates permissions in [deny, ask, allow order](https://code.claude.com/docs/en/permissions).
A broad `mcp__*` deny also blocks the selected relay; a more specific allow or ask cannot override
it. Inspect effective project, user and managed settings before deployment. If any deny matches
the relay, leave delivery disabled until the responsible policy owner resolves that conflict.
Do not bypass the policy to make the integration work.

Hook exit 0 only lets the request continue through host permissions. The selected relay still
requires the normal permission prompt as well as the human approval described above. Verify
that the host discovers the installed hook, dispatches it for the selected tool, and blocks
unapproved tools before enabling delivery. Inert hook tests establish the local protocol and
settings consistency; they do not prove native host dispatch or actual message delivery.
