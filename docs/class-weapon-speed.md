# AQW Class Weapon Speed Reference

In AQW, **weapon speed** is the global cooldown between skill uses. It equals the auto-attack (skill 1) cooldown in seconds.

**Dage Auto delay formula:** `weapon_speed + 0.15` seconds (buffer to avoid overlapping).

**Source:** [AQW Wiki](https://aqwwiki.wikidot.com/) class pages — "Weapon Damage: X%, Y speed"

---

## Dage Auto Supported Classes

| Class | Weapon Speed | Delay (speed + 0.15) |
|-------|--------------|----------------------|
| ArchMage | 1.5 | 1.65 |
| ArchPaladin | 2.0 | 2.15 |
| Blaze Binder | 2.0 | 2.15 |
| Cavalier Guard | 2.0 | 2.15 |
| Chaos Avenger | **3.0** | 3.15 |
| Chrono ShadowHunter | **0.15** | 0.3 (gun class) |
| Dragon of Time | 2.0 | 2.15 |
| Legion Revenant | 1.5 | 1.65 |
| LightCaster | 2.0 | 2.15 |
| Lord of Order | 2.0 | 2.15 |
| Scarlet Sorceress | 2.3 | 2.45 |
| Timeless Chronomancer | 2.0 | 2.15 |
| Void Highlord | 2.3 | 2.45 |
| Yami no Ronin | 2.0 | 2.15 |

---

## Common Weapon Speeds (AQW)

| Speed | Typical Classes |
|-------|-----------------|
| 0.15 | Chrono ShadowHunter (gun class) |
| 1.5 | Legion Revenant, ArchMage |
| 2.0 | Most classes (Blaze Binder, DoT, LightCaster, TCM, Lord of Order, Yami no Ronin) |
| 2.3 | Void Highlord, Scarlet Sorceress |
| 3.0 | Chaos Avenger |

---

## Notes for dage-auto

1. All delays use `weapon_speed + 0.15` to avoid overlapping.
2. **Chaos Avenger** has 3.0 speed — the slowest; delay is 3.15s.
3. **Chrono ShadowHunter** is a special case: 0.15 speed (gun class); delay is 0.3s. Per-skill cooldowns (Reload 6s, FMJ 1.5s, Silver Bullet 6s) still apply.
