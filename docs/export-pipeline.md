# Export Pipeline

The export pipeline turns an analyzed ROM into a correctly named output file ready to be copied to your device. It is built around a declarative, per-system fixer registry — each system declares its own complete pipeline.

## Overview

```
plan_export(rom_path, suggestion, dat, system_name)
    │
    └── get_fixers_for_system(system_name)
          │
          ├── Cartridge systems (default):
          │     HeaderStripFixer
          │     RenameExtFixer
          │     RemoveEmbeddedFixer
          │     ZipPackageFixer
          │
          ├── Nintendo 64:
          │     HeaderStripFixer
          │     RenameExtFixer
          │     RemoveEmbeddedFixer
          │     ZipPackageFixer
          │     N64ByteOrderFixer
          │
          ├── PS2, PSP (single-file disc images):
          │     RemoveEmbeddedFixer
          │     LooseFileFixer
          │
          └── PS1, Dreamcast, Saturn, Sega CD (multi-file disc images):
                LooseFileFixer
          
          → ExportPlan(target_name, steps=[ExportStep, ...])

execute_export(rom_path, plan, dest_dir, archive_format, rom_only,
               convert_byteorder)
    └── applies each ExportStep in order → output file/archive
```

## ExportFixer protocol

Every fixer implements the same interface:

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

## Per-system fixer pipelines (`SYSTEM_FIXERS`)

Each system declares its **complete** fixer pipeline in `SYSTEM_FIXERS` (`src/roms4me/exporters/fixers.py`). Systems not listed fall back to the default cartridge pipeline.

```python
# src/roms4me/exporters/fixers.py
_DEFAULT_FIXERS = [_header_strip, _rename_ext, _remove_embedded, _zip_package]

SYSTEM_FIXERS: dict[str, list] = {
    "Nintendo 64": [_header_strip, _rename_ext, _remove_embedded, _zip_package, _n64_byteorder],
    # Single-file disc images — strip junk, export loose
    "PlayStation 2":       [_remove_embedded, _loose_file],
    "PlayStation Portable": [_remove_embedded, _loose_file],
    # Multi-file disc images — keep companions, export loose
    "PlayStation": [_loose_file],
    "Dreamcast":   [_loose_file],
    "Saturn":      [_loose_file],
    "Sega CD":     [_loose_file],
}
```

Keys are substrings matched case-insensitively against the DAT system name. The longest matching key wins (so "PlayStation 2" matches before "PlayStation").

### Available fixers

| Fixer | Step name | What it does |
|---|---|---|
| `HeaderStripFixer` | `strip_header` | Detects and strips copier headers (SNES .smc/.swc/.fig, NES .nes) |
| `RenameExtFixer` | `rename_ext` | Renames the inner ROM extension to match the DAT when they differ |
| `RemoveEmbeddedFixer` | `remove_embedded` | Flags non-ROM files inside a zip for removal |
| `ZipPackageFixer` | `compress_package` | Repackages the ROM with the DAT-correct filename in a zip/7z archive |
| `LooseFileFixer` | `loose_file` | Exports the ROM as a standalone file with the DAT-correct filename |
| `N64ByteOrderFixer` | `convert_byteorder` | Converts N64 ROM byte order to match the DAT format |

### Cartridge vs disc systems

**Cartridge systems** (SNES, N64, GBA, etc.) include `ZipPackageFixer` in their pipeline. The output is an archive containing the ROM with the DAT-correct filename.

**Disc systems** use `LooseFileFixer` instead of `ZipPackageFixer`. The output is a standalone file — the executor extracts the ROM from any source archive automatically. Systems with single-file disc images (PS2, PSP) also include `RemoveEmbeddedFixer` to strip non-ROM files from archives. Multi-file systems (PS1, Dreamcast, Saturn, Sega CD) omit it so companion files (.cue, .gdi, track data) are preserved.

## System-specific export options (`SYSTEM_EXPORT_OPTIONS`)

Export settings that only apply to certain systems are declared in `src/roms4me/exporters/options.py`. Each option is a boolean toggle shown in the export-settings dialog only when the target system matches.

```python
# src/roms4me/exporters/options.py
SYSTEM_EXPORT_OPTIONS: dict[str, list[ExportOption]] = {
    "Nintendo 64": [
        ExportOption(id="convert_byteorder", label="Convert ROM to DAT format ..."),
    ],
}
```

The `compress_7z` option is **automatically added** for any system whose fixer pipeline includes `ZipPackageFixer`. This is derived from `fixers.system_supports_archiving()` — no need to declare it per-system.

### How it flows

1. **Frontend** — `GET /api/config/export-settings/{system}` returns saved settings plus an `available_options` list. The dialog renders checkboxes dynamically from that list.
2. **Config** — User choices are stored in `ExportSettings.system_options: dict[str, bool]`, keyed by option `id`. Universal settings (`rom_only`, `one_game_one_rom`, etc.) remain as top-level fields.
3. **Backend** — `POST /api/export/{system}` reads individual flags from the `system_options` dict and passes them to `execute_export()`.

### Current system options

| Option ID | Systems | What it does |
|---|---|---|
| `compress_7z` | All cartridge systems (auto-derived) | Use 7z instead of zip for the output archive |
| `convert_byteorder` | Nintendo 64 | Converts ROM byte order to match the DAT format (e.g. .v64 → .z64) |

### Adding a new system-specific option

1. Add an `ExportOption` entry to `SYSTEM_EXPORT_OPTIONS` in `exporters/options.py`.
2. Handle the option's `id` in `routes.py` (read from `system_options`) and `executor.py` (apply the behaviour).

No template, JavaScript, or config model changes are needed.

## Region filtering

When **one game, one ROM** is enabled and a **region priority** list is provided (e.g. "USA, World, Europe"), the export filters files in two ways:

1. **Exclusion** — files whose region doesn't match any priority are excluded, even if they're the only version of that title.
2. **Deduplication** — when multiple versions of the same title exist, only the best-ranked region is kept.

This means setting region priority to "USA" will exclude Japan-only games entirely.

## Adding a system-specific fixer

1. Create a class implementing `ExportFixer` in `src/roms4me/exporters/fixers.py` (or a new module).
2. Add a complete pipeline entry to `SYSTEM_FIXERS`.

```python
class MyFixer:
    name = "my_fixer"

    def suggest(self, rom_file, rom_data, dat_game_name,
                dat_rom_name, dat_rom_ext, accepted_exts=None):
        # return [ExportStep(...)] or []
        ...

SYSTEM_FIXERS = {
    ...
    "My System": [_rename_ext, MyFixer()],
}
```

No changes to `planner.py` or `routes.py` are needed.

## Analysis pipeline

See [Analysis Pipeline](analysis-pipeline.md) for the full reference. The analysis pipeline uses the same declarative, registry-based pattern as the export pipeline — base analyzers run for every system; system-specific analyzers are declared in `SYSTEM_FILE_ANALYZERS` keyed by DAT name substring.
