# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Layout: multi-context

This repo uses a **multi-context** domain-docs layout:

- **`GLOSSARY-MAP.md`** at the repo root is the single entry point. It points at one `GLOSSARY.md` per context; each subproject keeps its own glossary next to the code and vocabulary it owns.
- **`docs/adr/`** holds system-wide decisions. Context-specific decisions live with their context (for example `<context>/docs/adr/`).

Neither `GLOSSARY-MAP.md` nor the per-context `GLOSSARY.md` files exist yet. They are created lazily on the first resolved term, so a missing glossary is expected, not an error — proceed silently and keep working.

## Before exploring, read these

- **`GLOSSARY-MAP.md`** at the repo root if it exists, then read each per-context `GLOSSARY.md` relevant to the topic. (There is no single root `GLOSSARY.md` in this layout.)
- **`docs/adr/`**: read ADRs that touch the area you're about to work in. Also check the owning context's `docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Multi-context repo (this repo):

```
/
├── GLOSSARY-MAP.md                    ← entry point, one line per context
├── docs/adr/                          ← system-wide decisions
└── <context>/
    ├── GLOSSARY.md                    ← context vocabulary
    └── docs/adr/                      ← context-specific decisions
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in the owning context's `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
