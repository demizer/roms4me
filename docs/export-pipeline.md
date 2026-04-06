# Export Pipeline

The export pipeline turns an analyzed ROM into a DAT-correct archive ready to be copied to your device. It is built around the same pluggable pattern as the [analysis pipeline](#analysis-pipeline).

## Overview

```
plan_export(rom_path, suggestion, dat, system_name)
    │
    ├── ALL_FIXERS          ← run for every system
    │     HeaderStripFixer
    │     RenameExtFixer
    │     RemoveEmbeddedFixer
    │     CompressPackageFixer
    │
    └── SYSTEM_FIXERS[system_name]   ← run only for matching systems
          (empty by default — add entries here to extend)
          
          → ExportPlan(target_name, steps=[ExportStep, ...])

execute_export(rom_path, plan, dest_dir, archive_format, rom_only)
    └── applies each ExportStep in order → output archive
```

## ExportFixer protocol

Every fixer — base or system-specific — implements the same interface:

```python
class ExportFixer(Protocol):
    name: str

    def suggest(
        self,
        rom_file: Path,
        rom_data: bytes,
        dat_game_name: str,
        dat_rom_name: str,
        dat_rom_ext: str,
        accepted_exts: set[str] | None = None,
    ) -> list[ExportStep]: ...
```

`suggest` returns zero or more `ExportStep` objects describing a single transformation. The planner collects all steps in order into an `ExportPlan`.

## Base fixers (`ALL_FIXERS`)

| Fixer | Step name | What it does |
|---|---|---|
| `HeaderStripFixer` | `strip_header` | Detects and strips copier headers (SNES .smc/.swc/.fig, NES .nes) |
| `RenameExtFixer` | `rename_ext` | Renames the inner ROM extension to match the DAT when they differ |
| `RemoveEmbeddedFixer` | `remove_embedded` | Flags non-ROM files inside a zip for removal |
| `CompressPackageFixer` | `compress_package` | Repackages the ROM with the DAT-correct filename |

These run for every system. They are defined in `src/roms4me/exporters/fixers.py`.

## System-specific fixers (`SYSTEM_FIXERS`)

`SYSTEM_FIXERS` is a `dict[str, list[ExportFixer]]` in `fixers.py`. Keys are substrings matched case-insensitively against the DAT system name — the same convention used by `ROM_EXTENSIONS` in `handlers/registry.py`.

```python
# src/roms4me/exporters/fixers.py
SYSTEM_FIXERS: dict[str, list] = {
    # "PlayStation": [ChdPackageFixer()],
    # "Dreamcast":   [ChdPackageFixer()],
}
```

System fixers run **after** the base fixers, so they can build on or complement the base steps. Multiple keys can match the same DAT name; all matching fixer lists are merged in registry order.

## Adding a system-specific fixer

1. Create a class implementing `ExportFixer` in `src/roms4me/exporters/fixers.py` (or a new module).
2. Add an entry to `SYSTEM_FIXERS` with a substring that identifies the target system.

```python
class ChdPackageFixer:
    name = "chd_package"

    def suggest(self, rom_file, rom_data, dat_game_name,
                dat_rom_name, dat_rom_ext, accepted_exts=None):
        # return [ExportStep(...)] or []
        ...

SYSTEM_FIXERS = {
    "PlayStation": [ChdPackageFixer()],
    "Dreamcast":   [ChdPackageFixer()],
    "Saturn":      [ChdPackageFixer()],
}
```

No changes to `planner.py` or `routes.py` are needed.

## Analysis pipeline

The analysis pipeline follows the same pattern. Analyzers are split into two ordered lists in `src/roms4me/analyzers/pipeline.py`:

| List | Analyzers | When they run |
|---|---|---|
| `FILE_ANALYZERS` | `CrcLookupAnalyzer`, `HeaderStripAnalyzer`, `N64ByteOrderAnalyzer` | First — require reading file data |
| `NAME_ANALYZERS` | `RegionMapAnalyzer`, `NameContainsAnalyzer` | After — filename only, generate candidates for CRC verification |

To add a new analyzer: implement the `Analyzer` protocol from `analyzers/base.py` and append an instance to either list in `pipeline.py`.
