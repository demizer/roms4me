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
          N64ByteOrderFixer, ...
          
          → ExportPlan(target_name, steps=[ExportStep, ...])

execute_export(rom_path, plan, dest_dir, archive_format, rom_only,
               convert_byteorder, extract_disc_image)
    └── applies each ExportStep in order → output file/archive
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
    "Nintendo 64": [N64ByteOrderFixer()],
}
```

System fixers run **after** the base fixers, so they can build on or complement the base steps. Multiple keys can match the same DAT name; all matching fixer lists are merged in registry order.

## System-specific export options (`SYSTEM_EXPORT_OPTIONS`)

Export settings that only apply to certain systems are declared in `src/roms4me/exporters/options.py`. Each option is a boolean toggle shown in the export-settings dialog only when the target system matches.

```python
# src/roms4me/exporters/options.py
SYSTEM_EXPORT_OPTIONS: dict[str, list[ExportOption]] = {
    "Nintendo 64": [
        ExportOption(id="convert_byteorder", label="Convert ROM to DAT format ..."),
    ],
    "PlayStation 2": [
        ExportOption(id="extract_disc_image", label="Extract disc images from archives ..."),
    ],
}
```

Keys use the same case-insensitive substring matching as `SYSTEM_FIXERS` and `ROM_EXTENSIONS`. The UI, API, and config persistence all read from this registry — adding a new option here is all that's needed for it to appear in the dialog for the right systems.

### How it flows

1. **Frontend** — `GET /api/config/export-settings/{system}` returns saved settings plus an `available_options` list. The dialog renders checkboxes dynamically from that list.
2. **Config** — User choices are stored in `ExportSettings.system_options: dict[str, bool]`, keyed by option `id`. Universal settings (`rom_only`, `one_game_one_rom`, etc.) remain as top-level fields.
3. **Backend** — `POST /api/export/{system}` reads individual flags from the `system_options` dict and passes them to `execute_export()`.

### Current system options

| Option ID | Systems | What it does |
|---|---|---|
| `convert_byteorder` | Nintendo 64 | Converts ROM byte order to match the DAT format (e.g. .v64 → .z64) |
| `extract_disc_image` | PS1, PS2, PSP, Dreamcast, Saturn, Sega CD | Extracts disc images (ISO, CHD, BIN, etc.) from zip/7z as loose files instead of re-archiving |

### Adding a new system-specific option

1. Add an `ExportOption` entry to `SYSTEM_EXPORT_OPTIONS` in `exporters/options.py`.
2. Handle the option's `id` in `routes.py` (read from `system_options`) and `executor.py` (apply the behaviour).

No template, JavaScript, or config model changes are needed.

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

See [Analysis Pipeline](analysis-pipeline.md) for the full reference. The analysis pipeline uses the same declarative, registry-based pattern as the export pipeline — base analyzers run for every system; system-specific analyzers are declared in `SYSTEM_FILE_ANALYZERS` keyed by DAT name substring.
