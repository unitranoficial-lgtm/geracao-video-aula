---
id: 2
title: Normalize domain acronyms before speech generation
status: open
type: open-source
skill: [app-6a8d784b60cc81919aeafbfaeda5fbcf:creative-studio]
proposes_skill: []
siblings_checked: No family registry exists; this applies to creative-studio speech preparation, while API implementation skills are outside this observed workflow.
area: speech prompt preparation
date: 2026-09-28
session_context: Correcting unnatural acronym pronunciation in educational transportation videos
parked_until:
resolved:
resolution:
reference:
---

**Issue:** Domain acronyms may need different spoken forms. Word-like acronyms such as CIOT need a phonetic alias, but acronyms conventionally spelled letter by letter must remain in their normal uppercase editorial form. Rewriting spelled acronyms as phonetic syllables overcorrects the source text and can create unnatural delivery.

**Suggested improvement:** Before speech generation, apply whole-term aliases only to acronyms pronounced as words (`CIOT` → `cioti`). Send spelled acronyms unchanged and uppercase (`ANTT`, `RNTRC`, `IBS`, `CBS`). Preserve the editorial script and transform only the synthesizer input, including previous/next context.

**Principle:** TTS pronunciation normalization should be opt-in and minimal: adapt only terms with a known word-like pronunciation, while preserving conventional uppercase spelling for all other acronyms.
