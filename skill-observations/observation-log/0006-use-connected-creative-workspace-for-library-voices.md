---
id: 6
title: Use connected creative workspace for restricted library voices
status: open
type: open-source
skill: [app-6a8d784b60cc81919aeafbfaeda5fbcf:creative-studio, app-6a8d784b60cc81919aeafbfaeda5fbcf:text-to-speech]
proposes_skill: []
siblings_checked: No family registry exists; both creative-studio and text-to-speech apply because the issue is the difference between connected workspace generation and direct API generation.
area: speech generation routing
date: 2026-09-30
session_context: Generating an Elvis-voice narration for a vertical CIOT explainer
parked_until:
resolved:
resolution:
reference:
---

**Issue:** A direct ElevenLabs API call returned `paid_plan_required` for a library voice even though the same explicitly requested voice remained available through the connected ElevenLabs Creative workspace.

**Suggested improvement:** When an explicitly selected library voice is rejected by the direct API, check the connected Creative workspace before declaring the voice unavailable or substituting another voice. Generate one variation per narration and preserve the resulting local assets for editing.

**Principle:** Voice availability can differ by ElevenLabs access path; honor the user's requested voice by exhausting the connected workspace route before changing creative direction.
