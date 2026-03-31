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

### 1. Get a DAT file

DAT files describe ROM sets. You can find them from various ROM preservation communities. They are XML files with a `.dat` extension.

### 2. Upload the DAT file

Click **Upload DAT** in the toolbar and select your `.dat` file. It will be stored in the platform-appropriate data directory:

| Platform | Location |
|----------|----------|
| Linux    | `~/.local/share/roms4me/dats/` |
| macOS    | `~/Library/Application Support/roms4me/dats/` |
| Windows  | `%APPDATA%/roms4me/dats/` |

### 3. Select the database

Click on the uploaded DAT file in the left sidebar to load its game list.

### 4. Set your ROM path

Click **Add ROM Path** and enter the directory where your ROM ZIPs are stored.

### 5. Review results

The game list shows the verification status for each game:

| Color  | Status |
|--------|--------|
| Green  | OK — all ROMs verified |
| Red    | Missing — ROM ZIP not found |
| Yellow | Bad dump — incomplete or corrupt |
| Orange | Mismatch — size or checksum mismatch |

Click on any game to see its individual ROM files in the right panel.
