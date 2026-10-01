---
id: 1
title: Limit parallel ElevenLabs generations to subscription concurrency
status: open
type: open-source
skill: [app-6a8d784b60cc81919aeafbfaeda5fbcf:creative-studio]
proposes_skill: []
siblings_checked: No family registry exists; this applies specifically to creative-studio generation orchestration, not the API implementation skills.
area: generation batching and retries
date: 2026-09-28
session_context: Generating one narration in six selected voices for comparison
parked_until:
resolved:
resolution:
reference:
---

**Issue:** Six speech generations were started simultaneously, but the account allowed only two concurrent requests. One otherwise valid voice failed solely because the concurrency ceiling was exceeded. The skill warns about credit-spending retries but does not advise checking or limiting batch concurrency.

**Suggested improvement:** When creating several paid generations, submit them sequentially or in batches of at most two unless the account's concurrency allowance is known. Treat a concurrency failure as a separate user-authorized retry rather than silently starting another charged generation.

**Principle:** Credit-spending media workflows should bound concurrency to the subscription limit so transient capacity errors do not waste attempts or force ambiguous retries.
