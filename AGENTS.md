# AGENTS.md

Guidance for AI collaborators (Claude Code, Cursor Agent, etc.) working in this repo.

## Orient yourself in this order

1. **`strategy-design-contract.md`** — the contract. Every technical decision must be tested against this. Read fully before proposing anything non-trivial.
2. **`CONTEXT.md`** — the glossary. Use these terms exactly in code, comments, and prose. If a term feels missing, invoke the domain-modeling skill before inventing one.
3. **`docs/adr/`** — decisions already made. Do not reopen these silently. If a decision needs revisiting, write a superseding ADR.
4. **`quant-research.md`** — verified primary-source reference. Prefer this over training-data recall for factor-model / quant-systems facts.
5. **`proto-v0.1-momentum/PROTOTYPE_NOTICE.md`** — the current prototype's question, answer-so-far, and scope boundaries.

## Non-negotiable discipline rules

These are stated as rules because they are the single-largest source of failure in retail quant. Follow them even when they slow you down.

### 1. The held-out set is sacred

- Held-out window: **2024-01-01 → 2026-06-30**
- **Never** compute statistics on it during research
- **Never** look at charts of it while iterating
- **Never** tune parameters against it
- **One shot only**, at Gate G3, ever

If you find yourself wanting to "just check" the held-out set, stop. That is the failure mode.

### 2. Gates gate

If a gate fails:
- Return to the previous phase
- Investigate root cause (data leak, look-ahead, regime bias, cost model, slippage)
- Fix the cause
- Re-run affected prior gates

**Never** proceed by lowering the threshold.

### 3. Contract amendments are explicit

If the design contract needs to change:
- Amend it in-file with an incremented version number (1.0 → 1.1 → 2.0)
- State the rationale in the amendment section
- Re-run any prior gate affected by the change

**Never** silently deviate. Silent deviation is how contracts stop being contracts.

### 4. Prototypes are throwaway

Files in `proto-*/` are answers to specific questions, not the shape of production code. Do not import from a `proto-*/` directory in another module. When a prototype answers its question, lift the validated pure logic into the real codebase; the prototype itself becomes a primary-source snapshot.

### 5. Attribution is first-class

Every decision the system makes in production must be traceable to which Agent contributed how much. This is not optional. When adding a new Agent, add its attribution hook at the same time.

## Coding conventions

- **Language**: Python 3.11+
- **Style**: PEP 8, type hints where useful, no aggressive type gymnastics
- **Comments**: only when the *why* is non-obvious. Don't explain *what* the code does; well-named identifiers do that.
- **Testing**: prototypes don't need tests. Production code does — write tests for the validation gates themselves (was IC computed correctly? does DSR match a known reference?).
- **Vocabulary**: use CONTEXT.md terms. `Agent` not `strategy`. `Signal` not `score`. `Regime` not `market state`.

## Tools worth knowing

- `mattpocock-skills:domain-modeling` — for sharpening CONTEXT.md when concepts change
- `mattpocock-skills:tdd` — when writing production-grade signal or gate code
- `mattpocock-skills:prototype` — when exploring a design question
- `mattpocock-skills:research` — when verifying factual claims against primary sources
- `mattpocock-skills:diagnosing-bugs` — for when backtest ≠ paper or paper ≠ live (inevitable)

## What NOT to do

- Do not add features not in the contract scope (§9 of `strategy-design-contract.md`)
- Do not fetch paid data
- Do not push to `main` without gates passing
- Do not commit `.venv/`, `data/`, `output/`, `*.sqlite`, `*.duckdb`, or secrets
- Do not silently retry the held-out set — that is contract violation
- Do not use terms not in CONTEXT.md without adding them first
- Do not "improve" code that was deliberate — check ADRs first

## When in doubt

Ask. The cost of asking is small. The cost of a silent design drift is a whole rebuild.
