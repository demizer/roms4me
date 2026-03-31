# ROM Directory Format

## Naming Convention

ROM directories should follow the format:

```
<Company> - <System>
```

For example:

```
/mnt/games/ROMS/
  Nintendo - NES/
  Nintendo - SNES/
  Nintendo - Game Boy/
  Nintendo - N64/
  Sega - Genesis/
  Sega - Game Gear/
  Sony - PS1/
  Sony - PSP/
```

## Accepted Abbreviations

roms4me uses the [No-Intro naming convention](https://wiki.no-intro.org/index.php?title=Systems) for system matching. The following abbreviations are recognized and mapped to their full DAT names automatically:

| Directory Name | Matches DAT System |
|---|---|
| `Nintendo - NES` | Nintendo - Nintendo Entertainment System |
| `Nintendo - SNES` | Nintendo - Super Nintendo Entertainment System |
| `Nintendo - N64` | Nintendo - Nintendo 64 |
| `Nintendo - GB` | Nintendo - Game Boy |
| `Nintendo - GBA` | Nintendo - Game Boy Advance |
| `Nintendo - GBC` | Nintendo - Game Boy Color |
| `Nintendo - DS` | Nintendo - Nintendo DS |
| `Nintendo - 3DS` | Nintendo - Nintendo 3DS |
| `Sega - Genesis` | Sega - Mega Drive - Genesis |
| `Sega - Game Gear` | Sega - Game Gear |
| `Sega - SMS` | Sega - Master System |
| `Sony - PS1` | Sony - PlayStation |
| `Sony - PS2` | Sony - PlayStation 2 |
| `Sony - PSP` | Sony - PlayStation Portable |
| `NEC - PC Engine` | NEC - PC Engine - TurboGrafx-16 |
| `Atari - 2600` | Atari - Atari 2600 |
| `Commodore - 64` | Commodore - Commodore 64 |
| `SNK - Neo Geo Pocket` | SNK - NeoGeo Pocket |

The full list of No-Intro system names and abbreviations is available at:
[https://wiki.no-intro.org/index.php?title=Systems](https://wiki.no-intro.org/index.php?title=Systems)

## DAT File Compatibility

When you add a ROM directory and run a pre-scan, roms4me will:

1. Match your directory name to the closest DAT system using fuzzy matching
2. Show a compatibility rating:
   - **GREEN** — Good extension and filename overlap
   - **YELLOW** — Compatible but low matches, CRC scan may find more
   - **RED** — Format mismatch (e.g., disc dump ROMs vs digital store DATs)

If you see RED, you likely need a different DAT file for your ROM format. For disc-based systems (PS1, PSP, Dreamcast, Saturn), use [Redump](http://redump.org/) DATs instead of No-Intro.
