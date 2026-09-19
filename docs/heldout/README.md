# Held-out Verdict

**Purpose**: this directory holds the permanent record of Gate G3 evaluation on the held-out set (2024-01-01 → 2026-06-30).

**Contract discipline**: per `strategy-design-contract.md` §3, the held-out set is evaluated *exactly once*. If a verdict file (`verdict.md` / `verdict.json`) exists in this directory, the held-out set has already been used. Do not re-run.

**How the verdict gets written**: `proto-v0.1-momentum/run_held_out.py` is the only script that writes here. It refuses to run without `--confirm-final-evaluation` and refuses to overwrite an existing verdict without an override flag whose name is deliberately embarrassing.

**If the held-out fails**: the strategy is retired. Not tweaked. The verdict stands. Go back to research window and rebuild.

**If you see a `HELDOUT_OVERRIDE.md` at the workspace root**: someone bypassed the lock. Read that file first to understand why. Any verdict written after an override is not a valid G3 evaluation.
