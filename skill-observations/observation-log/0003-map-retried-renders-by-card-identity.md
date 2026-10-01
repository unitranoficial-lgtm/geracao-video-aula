---
id: 3
title: Map retried renders by card identity instead of gallery order
status: open
type: internal
skill: []
proposes_skill: [google-flow-video-automation]
siblings_checked: No family registry exists; this concerns the project-specific Google Flow automation and does not apply to the installed ElevenLabs or browser-interaction skills.
area: retry recovery and deterministic downloads
date: 2026-09-29
session_context: Generating a five-take vertical investment education video when one Flow render failed and was retried individually
parked_until:
resolved:
resolution:
reference:
---

**Issue:** A single failed render retried after the original batch changes the gallery order, so positional take mapping becomes invalid. A failed frame selection could also submit a render with stale frames.

**Suggested improvement:** Require positive confirmation of both start and end frames before submission, support single-take retry, and persist an explicit take-to-card identity map whenever a retry creates extra cards.

**Principle:** In asynchronous media pipelines, recovery actions change ordering; resumable downloads must use stable asset identity rather than chronology.
