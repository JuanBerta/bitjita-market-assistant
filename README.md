# BitJita Market Assistant

A desktop market helper for **BitCraft** that uses **BitJita** market data to make item searching, shopping-list planning, route comparison, and claim-based distance checks easier.

> This is an unofficial community project and is not affiliated with BitCraft or BitJita.

## Features

- Search BitJita market listings by item name
- Filter by rarity, tier, item type/category, and region
- Sort Item Search results by clicking column headers
- Right-click an Item Search result and add it directly to the Shopping List
- Cancel an Item Search while it is running
- Shopping List optimization:
  - Cheapest
  - Nearest
  - Balanced
- Partial shopping plans when some items are unavailable
- Claim-based starting locations
- Region-filtered Claim dropdowns
- Claim data loaded from BitJita
- BitCraft Small Hex distance calculations
- Compact distance display such as `1.1k` and `3.9k`
- Equipment set support for Leather, Metal, and Cloth
- Dynamic set-piece detection from BitJita
- Multiple configurable starting locations
- Responsive Shopping List layout
- Purchase Plan and Route views
- Dark interface
- API endpoint auto-detection and local endpoint cache

## Current Version

**v3.7.1**

## Requirements

- Windows 10 or Windows 11
- Python 3.11+ recommended
- Internet connection

The application has also been tested during development with Python 3.14.

## Running from Source

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/bitjita-market-assistant.git
cd bitjita-market-assistant
```

Run the application:

```bash
py bitjita_market_assistant_gui.py
```

If your system uses `python` instead of `py`:

```bash
python bitjita_market_assistant_gui.py
```

## Building a Windows EXE

Install PyInstaller:

```bash
py -m pip install pyinstaller
```

Build a single-file GUI executable:

```bash
py -m PyInstaller --onefile --windowed --name "BitJita Market Assistant" bitjita_market_assistant_gui.py
```

The executable will be created under:

```text
dist/
```

### Antivirus / VirusTotal Note

Single-file executables created with tools such as PyInstaller can sometimes trigger heuristic antivirus detections even when the source code is clean.

The source code is provided publicly so users can inspect it and run it directly with Python if they prefer.

## Distance Calculation

BitJita exposes Claim position data through its API.

BitJita Market Assistant uses those Claim positions and calculates distance on the **BitCraft Small Hex grid**.

This replaced an older Euclidean-distance approximation that could incorrectly rank some Claims by distance.

The calculated distance may still differ by a few hexes from the in-game UI because BitJita Claim coordinates and the exact in-game destination point may not always represent precisely the same point.

## Shopping List

The Shopping List can optimize purchases using three modes.

### Cheapest

Prioritizes the lowest total item price.

### Nearest

For each requested item, prioritizes the market closest to the selected starting Claim.

### Balanced

Balances item price, travel distance, and starting-region preference.

If one or more items cannot be found, the application can still create a partial plan for the available items and report what is missing.

## Equipment Sets

The Shopping List includes an expandable **Add Equipment Set** section.

Supported armor families:

- Leather
- Metal
- Cloth

Set families and available pieces are discovered from BitJita where possible instead of assuming every set has exactly the same equipment slots.

Only pieces detected for the selected set are added.

## Location / Optimization

Up to three starting locations can be configured.

For each location:

1. Select a Region
2. Select or search for a Claim
3. Claim-position data is loaded from BitJita automatically

The Claim list is filtered by the selected Region.

## Data Source

Market, Claim, item, region, and order information is retrieved from:

- [BitJita](https://bitjita.com/)

Availability and market prices can change at any time.

## Configuration

The application may cache the detected BitJita API endpoint locally under:

```text
%LOCALAPPDATA%\BitJita Market Assistant\config.json
```

This file is used only to avoid repeatedly rediscovering the working API endpoint.

## Privacy

The application does not require a BitCraft account login.

It queries public BitJita market/Claim data and stores only limited local application configuration.

## About

Developed by **Aron** with the help of AI.

Discord:

```text
kamarasa_
```

## Feedback / Bug Reports

If you find a bug or have a suggestion, you can:

- open a GitHub Issue
- contact `kamarasa_` on Discord

When reporting a bug, please include the application version, what you searched for, the selected Region/Claim if relevant, the error message, and a screenshot if possible.

## License

A license has not yet been selected.

Before publishing the repository, it is recommended to add a license such as the **MIT License** if you want others to be able to reuse and modify the code under clear terms.
