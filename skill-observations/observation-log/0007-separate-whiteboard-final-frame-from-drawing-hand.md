---
id: 7
title: Separate whiteboard final frames from the animated drawing hand
status: open
type: open-source
skill: []
proposes_skill: [google-flow-video-automation]
siblings_checked: No family registry exists; this concerns the project-specific Google Flow image-to-video workflow and does not apply to the installed image-generation or browser-interaction skills.
area: whiteboard frame prompting and image-to-video continuity
date: 2026-09-30
session_context: Correcting a vertical whiteboard explainer whose generated final-frame images incorrectly contained the drawing hand
parked_until:
resolved:
resolution:
reference:
---

**Issue:** In a whiteboard animation workflow, final-frame image prompts described or showed the drawing hand. This bakes the transient animation actor into the destination frame and prevents a clean completed-artwork ending.

**Suggested improvement:** Treat the drawing hand as video-only motion. Final-frame prompts must describe only the completed illustration and explicitly prohibit hands, fingers, arms, people, markers and pens. Video prompts should introduce the hand during drawing and require it to leave completely before the last frame.

**Principle:** Keep transient animation mechanisms out of keyframe assets; keyframes represent stable visual states, while motion prompts describe the actors and actions that connect them.
