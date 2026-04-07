# System Matching

roms4me uses fuzzy matching to connect ROM directories to DAT files. ROM directories follow a `Company - System` naming convention (e.g. `Sony - PS2`) while DAT files use full system names (e.g. `Sony - PlayStation 2`) and may carry source prefixes (`Non-Redump - Sony - PlayStation 2`). The matcher bridges these differences automatically.

## How matching works

`match_system(query, candidates)` in `src/roms4me/services/system_matcher.py` scores each candidate against the query and returns the best match above zero.

`match_all_systems(query, candidates, threshold)` returns **all** candidates that score at or above `threshold` (default: 1.0), sorted best-first. This is used when a single ROM directory maps to multiple DATs from different sources.

### Scoring (`_score`)

| Check | Score |
|-------|-------|
| Exact system-part match | 100 |
| Both sides canonicalize to the same alias (e.g. `ps2` == `playstation 2`) | 90 |
| One system part contains the other | 80 |
| Token overlap ≥ 50% of the shorter side | 0–70 |
| Manufacturer mismatch | 0 (with prefix-strip retry) |

### Source prefix stripping

Some DAT databases prefix their system names with a source label (`Non-Redump`, `Redump`, `TOSEC`, etc.). The matcher detects these via `_STRIP_PREFIXES` and retries the score without the prefix:

```
"Non-Redump - Sony - PlayStation 2"
    → manufacturer "non-redump" is in _STRIP_PREFIXES
    → retry _score(query, "Sony - PlayStation 2")
    → manufacturer "sony" matches, alias "ps2" == "playstation 2" → score 90
```

## Alias table (`_ALIASES`)

Short names commonly used in ROM directory names are mapped to canonical keys. Both sides of a match are canonicalized independently; if they resolve to the same key, the score is 90.

Examples:

| ROM dir | DAT system | Canonical key |
|---------|-----------|---------------|
| `Sony - PS2` | `Sony - PlayStation 2` | `ps2` |
| `Nintendo - N64` | `Nintendo - Nintendo 64` | `n64` |
| `Sega - Genesis` | `Sega - Mega Drive - Genesis` | `genesis` |
| `NEC - PC Engine` | `NEC - TurboGrafx-16` | `pce` |
| `Nintendo - SNES` | `Nintendo - Super Nintendo Entertainment System` | `snes` |

The full alias table is in `src/roms4me/services/system_matcher.py`.

## Multiple DATs per system

A ROM directory can be matched against more than one DAT — for example, both a Redump and a Non-Redump database for PlayStation 2. `_match_dat_paths()` in `api/routes.py` calls `match_all_systems()` and collects DAT path entries from every matching system name:

```python
def _match_dat_paths(system_name, all_dats, all_systems):
    matched = match_all_systems(system_name, dat_system_names)
    return [dp for dp in all_dats if all_systems[dp.system_id] in matched]
```

All matching DATs are used together for prescan, analysis, export planning, and the DAT header shown in the UI.

## Adding a short name

Edit `_ALIASES` in `src/roms4me/services/system_matcher.py`:

```python
_ALIASES = {
    ...
    "ps2": {"playstation 2", "ps2"},   # existing
    "vita": {"playstation vita", "vita", "psv", "ps vita"},  # add new variants here
}
```

The key is the canonical name used internally; the set contains all strings that should map to it (all lowercase).
