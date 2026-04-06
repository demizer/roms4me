# Getting Started

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [just](https://github.com/casey/just) (task runner)

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/youruser/roms4me.git
cd roms4me
uv sync
```

## Running the server

Start the development server with auto-reload:

```bash
just dev
```

Or start in production mode:

```bash
just serve
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

## Quick start

### 1. Add your paths

Click **Settings** and configure your paths:

- **ROMs** — Add the root directories where your ROM files are stored. Each directory should follow the `Company - System` naming convention (e.g. `Nintendo - SNES`). See [ROM Directory Format](rom-directory-format.md).
- **DATs** — Add the directories containing your No-Intro DAT files (`.dat` XML format).

### 2. Sync all systems

From the home view (click **roms4me** in the toolbar to return here if needed), click **Sync**. This pre-scans all configured ROM directories against your DATs and populates the sidebar with all detected systems and their compatibility ratings.

### 3. Select a system

Click a system in the sidebar to view its ROM list, pre-scan rating, and matched DAT.

### 4. Analyze

Select ROMs in the list and click **Analyze** to run CRC verification against the DAT database. Matched ROMs are confirmed good dumps; unmatched ROMs may be fan translations, hacks, or bad dumps.

Right-click any row in the grid and choose **View analysis** to inspect the details for that file — archive contents, DAT match candidates, the raw analysis log, and the planned export steps.

### 5. Export

Select verified ROMs and click **Add to Queue**. An export settings dialog will open — configure it once per system and the settings are saved automatically:

| Setting | Description |
|---------|-------------|
| **Export to** | Destination directory (e.g. an SD card path) |
| **ROM only** | Strip embedded non-ROM files (readmes, etc.) from archives |
| **One game, one ROM** | When multiple versions of the same game are queued, keep only the best region match |
| **Region priority** | Comma-separated region preference order used by *One game, one ROM* (e.g. `USA, World, Europe, Japan`) |
| **Compress with 7z** | Use 7z instead of zip — smaller files, same ROM data |

If **One game, one ROM** causes a conflict (e.g. you selected both a USA and a Europe version), the dialog will report which version was kept and which was dropped before you close it.

When ready, click the **Queue** button in the toolbar and then **Process Queue**. Each system uses its own saved settings — no need to re-enter them each time.

---

## Syncing

**Sync** re-runs the pre-scan and updates the ROM list.

| Scenario | How to sync |
|----------|-------------|
| Sync all systems | Click the **roms4me** link in the toolbar to return to the home view (no system selected), then click **Sync** |
| Sync one system | Select the system in the sidebar, then click **Sync** — only that system's data is cleared and re-scanned |

Use single-system sync when you've added or changed ROMs for one platform and don't want to wait for a full rescan.

---

## ROM status reference

| Status | Meaning |
|--------|---------|
| `matched` | CRC verified against DAT — confirmed good dump |
| `unmatched` | File analyzed but no CRC match in DAT (fan translation, hack, or bad dump) |
| `duplicate` | Same CRC already matched by another file |
| `unverified` | Not yet analyzed — run Analyze |
