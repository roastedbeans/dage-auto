# Combo Press Process

Short process when pressing a combo (example: **Yami no Ronin** Dodge pattern `3225225`).

---

## Architecture

Two **independent** threads run in parallel:

1. **run_auto** — presses skill 1 every auto-attack cooldown (weapon speed). Runs behind the skill loop.
2. **run_ability_combo** — loops over skills 2–6 only. Skill 1 is never in this loop.

---

## Skill Loop (2–6)

- **Different skills**: wait `delay` (1.20s), then press.
- **Same skill**: wait skill cooldown before re-press (not 1.20s).

YnR Dodge: `3` → `2` → `2` → `5` → `2` → `2` → `5` → repeat

---

## Auto Thread (1)

Presses 1 every 2.0s (YnR weapon speed). Runs independently in the background.

---

## Yami no Ronin Example (Dodge: `3225225`)

| Thread | Action |
|--------|--------|
| **Auto** | Press 1 every 2.0s |
| **Combo** | 3 → (1.20s) → 2 → (3.0s Tachi) → 2 → (1.20s) → 5 → (1.20s) → 2 → (3.0s Tachi) → 2 → (1.20s) → 5 → repeat |

---

## Summary

- **Skill 1**: Independent thread; presses every weapon speed (auto cooldown).
- **Skills 2–6**: Different skills = 1.20s; same skill = wait cooldown.
