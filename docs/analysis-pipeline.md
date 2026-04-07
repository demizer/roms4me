# Analysis Pipeline

The analysis pipeline identifies and verifies ROM files against DAT databases. It is declarative: each system's analyzer set is defined in a registry — no code changes to the pipeline itself are needed to add system-specific logic.

## Overview

```
analyze_rom(rom_path, dat, precomputed_crc="")
    │
    ├── CRC computed once (precomputed or _compute_crc)
    │     zip:  stored CRC from central directory
    │     7z:   FileInfo.crc32 from archive header
    │     chd:  crc32_of_chd() — streams all hunks
    │     other: streamed in 8 MB chunks
    │
    ├── _get_file_analyzers(dat.name)         crc= passed to all
    │     BASE_FILE_ANALYZERS        ← run for every system
    │       CrcLookupAnalyzer          uses crc — pure DAT lookup
    │       HeaderStripAnalyzer        ignores crc — reads file bytes
    │
    │     SYSTEM_FILE_ANALYZERS      ← run only for matching systems
    │       "Nintendo 64": [N64ByteOrderAnalyzer]
    │       (add entries here to extend)
    │
    ├── NAME_ANALYZERS               ← run for every system, filename only
    │     NameMatchAnalyzer            unified: region expansion + base name
    │
    └── CRC verify name-based candidates (reuses same crc)
          _compute_stripped_crcs()   ← N64 normalization only for Nintendo 64
```

## Analyzer types

| Type | Interface method | Input | When it runs |
|------|-----------------|-------|--------------|
| File-based | `analyze_file(rom_path, dat, crc="")` | ROM path + precomputed CRC | Before name-based; can confirm a match directly |
| Name-based | `analyze(rom_stem, dat)` | Filename stem | After file-based; produces candidates that are CRC-verified |

Both types return `list[Suggestion]`. A `Suggestion` with `crc_match=True` is a confirmed match and short-circuits the pipeline (no further analyzers run).

File-based analyzers receive `crc=` from the pipeline. Analyzers that need it (like `CrcLookupAnalyzer`) use it directly; others ignore it. CRC is computed once per ROM — never per-analyzer or per-DAT.

## Base analyzers (`BASE_FILE_ANALYZERS`)

Run for every system regardless of DAT name.

| Analyzer | What it does |
|----------|-------------|
| `CrcLookupAnalyzer` | Looks up the precomputed CRC directly in the DAT (no I/O) |
| `HeaderStripAnalyzer` | Tries stripping known copier headers (SNES, NES, Lynx, Atari 7800) and re-checking the CRC |

## Name matching (`NAME_ANALYZERS`)

`NameMatchAnalyzer` in `src/roms4me/analyzers/name_match.py` is the unified name matcher. It runs for every system and combines all name-matching strategies in one pass:

| Step | Confidence | What it does |
|------|-----------|-------------|
| Exact full-name match | 0.95 | Case-insensitive full name comparison |
| Region expansion | 0.85–0.90 | Expand `(U)` → `(USA)` etc., then match |
| Exact base-name match | 0.85 | Strip tags, compare base names |
| Word boundary (ROM in DAT) | ≤ 0.70 | ROM base found inside DAT name |
| Word boundary (DAT in ROM) | ≤ 0.50 | DAT base found inside ROM name |

The same module provides `find_closest_match()` used by the prescan service for unmatched ROM diagnostics, and shared utilities (`expand_regions`, `extract_base`, `normalize_name`, `extract_tags`) used across the codebase.

## System-specific analyzers (`SYSTEM_FILE_ANALYZERS`)

`SYSTEM_FILE_ANALYZERS` is a `dict[str, list]` in `src/roms4me/analyzers/pipeline.py`. Keys are substrings matched case-insensitively against the DAT name — the same convention used by `ROM_EXTENSIONS` in `handlers/registry.py`.

```python
SYSTEM_FILE_ANALYZERS: dict[str, list] = {
    "Nintendo 64": [N64ByteOrderAnalyzer()],
}
```

Multiple keys can match the same DAT name; all matching lists are merged and appended after `BASE_FILE_ANALYZERS`.

### N64ByteOrderAnalyzer

Handles byte-order variants of N64 ROMs (`.z64` BigEndian, `.v64` ByteSwapped, `.n64` LittleEndian). Tries converting the ROM to each byte order and checking the resulting CRC against the DAT. Only runs when `"Nintendo 64"` appears in the DAT name.

## Adding a system-specific analyzer

1. Create a class in `src/roms4me/analyzers/` implementing the `Analyzer` protocol from `base.py`.
2. Add an entry to `SYSTEM_FILE_ANALYZERS` with a substring that identifies the target system.

```python
class PS2ChdAnalyzer:
    name = "ps2_chd"

    def analyze_file(self, rom_path: Path, dat: DatFile) -> list[Suggestion]:
        # decompress CHD, compute CRC, look up in dat
        ...

SYSTEM_FILE_ANALYZERS = {
    "Nintendo 64":   [N64ByteOrderAnalyzer()],
    "PlayStation 2": [PS2ChdAnalyzer()],
}
```

No changes to `analyze_rom()` are needed.

## CRC computation

`_compute_crc(rom_path, accepted_exts)` — computes CRC32 of the primary ROM file.

| Format | How CRC is computed |
|--------|---------------------|
| `.zip` | Reads the stored CRC from the central directory — no decompression needed |
| `.chd` | Streams all hunks via the pure-Python CHD v5 reader (see below) |
| everything else | Streams the file in 8 MB chunks — avoids loading large ISOs into memory |

`_compute_stripped_crcs(rom_path, accepted_exts, dat_name)` — computes CRC32 for header-stripped variants. N64 byte-order normalization is only attempted when `"nintendo 64"` is in `dat_name`.

## CHD support

CHD (Compressed Hunks of Data) is the disc image format used by MAME and Redump for PS1, PS2, Dreamcast, and Saturn games. `src/roms4me/analyzers/chd.py` is a self-contained, pure-Python CHD v5 reader — no external tools or packages required, works on Linux, macOS, and Windows.

### What it does

`crc32_of_chd(path)` reads the CHD header, decodes the huffman-compressed hunk map, then streams through every hunk accumulating a running `zlib.crc32`. The result is the CRC32 of the raw uncompressed disc data — which is what Redump DATs record.

### Supported codecs

| Codec | Notes |
|-------|-------|
| `zlib` | Standard deflate — most CHDs |
| `lzma` | Raw LZMA1 with 5-byte property header — newer CHDs |
| `NONE` | Uncompressed hunks |
| `SELF` | Hunk is identical to a previous hunk (resolved by re-reading) |

PARENT hunks (requiring a parent CHD file) are not supported and raise `ChdError`.

### Adding CHD support for a system

CHD analysis runs automatically for any `.chd` file processed by `_compute_crc`. To add CHD awareness to a system's analyzer, add an entry to `SYSTEM_FILE_ANALYZERS` with a `ChdAnalyzer` that calls `crc32_of_chd`:

```python
from roms4me.analyzers.chd import ChdError, crc32_of_chd

class PS2ChdAnalyzer:
    name = "ps2_chd"

    def analyze_file(self, rom_path: Path, dat: DatFile) -> list[Suggestion]:
        if rom_path.suffix.lower() != ".chd":
            return []
        try:
            crc = crc32_of_chd(rom_path)
        except ChdError:
            return []
        return dat.lookup_crc(crc)  # returns Suggestion list
```

## DAT matching

Each ROM directory may be matched against **multiple DATs** — for example a Redump and a Non-Redump database for the same system. `_match_dat_paths()` in `api/routes.py` uses `match_all_systems()` to find every DAT system name that matches the ROM system name above a score threshold. All matching DATs are loaded and their game lists are searched together during analysis.

See [System Matching](system-matching.md) for details on how DAT system names are resolved.
