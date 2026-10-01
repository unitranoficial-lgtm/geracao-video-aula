---
id: 4
title: Preserve successful images when a generation batch partially fails
status: open
type: internal
skill: []
proposes_skill: [google-flow-video-automation]
siblings_checked: No family registry exists; this concerns the project-specific Google Flow automation and not the installed ElevenLabs or browser-interaction skills.
area: image generation retry recovery
date: 2026-09-29
session_context: Producing a two-take cinematic-realistic style test where one image repeatedly failed policy checks
parked_until:
resolved:
resolution:
reference:
---

**Issue:** The batch image wait aborted when one card failed, even though another requested frame had completed successfully. Re-running the whole batch wasted generations and obscured which take was blocked.

**Suggested improvement:** Persist every successful image immediately, identify failed take positions, and expose a single-image retry path that updates only that take in nomes_picker.json.

**Principle:** Partial batch failure should degrade into item-level recovery; never discard successful work or repeat the whole batch blindly.
