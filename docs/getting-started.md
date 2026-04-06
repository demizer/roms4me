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

### 5. Export

Select verified ROMs and click **Add to Queue**. When ready, click the **Queue** button in the toolbar, set your export destination (e.g. an SD card path), configure region priority if needed, and click **Process Queue**.

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
