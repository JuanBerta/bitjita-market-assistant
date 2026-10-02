# BitJita Market Assistant

A desktop market helper for **BitCraft** that uses **BitJita** data to make item searching, shopping-list planning, buy-order planning, inventory browsing, route comparison, and Claim-based distance checks easier.

> This is an unofficial community project and is not affiliated with BitCraft or BitJita.

## Current Version

**v3.10.3**

## Features

### Item Search

- Search BitJita market listings by item name
- Autocomplete while continuing to type normally
- Filter by rarity, tier, item type/category, region, and minimum quantity
- Results include price, quantity, distance, estimated TP, item details, location/Claim, region, seller, and item ID
- Default **Price + Distance** ranking considers both travel cost and requested quantity
- Click column headers to cycle through ascending, descending, and the original Price + Distance ordering
- Right-click a result to add it directly to the Shopping List
- Double-click a result to open its BitJita market page
- Cancel a search while it is running
- `Shift+Tab` provides quick switching between Shopping List and Item Search

### Shopping List

- Add individual items with rarity, tier, and quantity
- Right-click Shopping List entries to **Edit** or **Remove** them
- Edit item name, rarity, tier, and quantity without rebuilding the list
- Add equipment sets for Leather, Metal, and Cloth
- Dynamic set-piece detection from BitJita
- Partial plans are supported when some requested items are unavailable
- Responsive layout for smaller application windows

### Sell Order Purchase Planning

The default purchase mode is **Buy from Sell Orders**.

Three purchase-plan strategies are available:

- **Cheapest** — prioritizes the lowest item cost
- **Nearest** — prioritizes nearby markets from the selected starting Claim
- **Balanced** — balances item price and travel distance

Purchase plans include Claim/Region information, distance, and estimated teleport energy where applicable.

### Buy Order Planning

A separate **Plan Buy Orders** mode helps determine what price to use when creating buy orders without replacing the existing sell-order workflow.

Available price strategies:

- **Highest Current Buy Price**
- **24h Average**
- **7d Average**
- **30d Average**

The Buy Order Plan shows:

- Item
- Required quantity
- Price method
- Suggested unit price
- Estimated total cost
- Status when pricing data is unavailable

Historical averages use BitJita's market-history values. No fallback or estimated price is generated when the selected strategy has no data.

The Price Strategy control is only shown while **Plan Buy Orders** is selected.

### Items

The **Items** tab can load a selected BitJita player's:

- Inventory
- Storage / housing contents
- Bank / vault contents

Displayed information includes:

- Item name
- Quantity
- Storage type
- Container
- Claim / Settlement
- Region
- Tier
- Rarity
- Item type
- Item ID

The Items tab also includes:

- Player selection by BitJita username
- Saved player selection between sessions
- Text search
- Storage Type filter: `Inventory`, `Storage`, `Bank`
- Settlement / Region filter
- Region resolution from the shared Claim catalogue when the inventory response does not contain Region data
- Parallel API loading for faster inventory, housing, vault, item catalogue, and Claim catalogue retrieval

### Location / Optimization

- Configure up to three starting locations
- Search and select Claims from BitJita
- Region-filtered Claim selection
- Switch between saved starting locations from the Shopping List
- Starting locations and the active selection are restored when the application is reopened
- No manual X/Z entry is required

### Distance and Estimated TP

BitJita Market Assistant calculates travel distance on the **BitCraft Small Hex grid** using BitJita Claim coordinates.

BitJita's raw Claim coordinates use a different scale from the in-game Small Hex coordinates, so the application normalizes the coordinates before calculating hex distance.

Estimated teleport energy uses the current empty-inventory approximation:

```text
Estimated TP = ceil(distance / 400)
```

For routes containing multiple legs, TP is rounded up separately for each leg and then summed.

> Estimated TP assumes an empty inventory. Actual in-game cost can differ depending on game mechanics and carried inventory.

### Performance

The application reuses shared API data and short-lived caches to reduce unnecessary requests.

Examples include:

- Shared Claim catalogue cache
- Market-search and order caches
- Buy-order and price-history caches
- Parallel order fetching for Shopping List calculations
- Parallel inventory, housing, vault, item catalogue, and Claim catalogue loading in the Items tab
- Concurrent housing-detail requests

## Requirements

- Windows 10 or Windows 11
- Internet connection
- Python if running from source

The project is currently developed and tested with **Python 3.14**. Other recent Python 3 versions may also work but are not the primary development environment.

## Download

Prebuilt Windows releases are available from:

[GitHub Releases](https://github.com/xisini/bitjita-market-assistant/releases/latest)

## Running from Source

Clone the repository:

```bash
git clone https://github.com/xisini/bitjita-market-assistant.git
cd bitjita-market-assistant
```

Run the current version:

```bash
py bitjita_market_assistant_gui_v3_10_3.py
```

If your system uses `python` instead of `py`:

```bash
python bitjita_market_assistant_gui_v3_10_3.py
```

## Building a Windows EXE

Install PyInstaller:

```bash
py -m pip install pyinstaller
```

Build the current release as a single-file GUI executable:

```bash
py -m PyInstaller --onefile --windowed --name "BitJita-Market-Assistant-v3.10.3" bitjita_market_assistant_gui_v3_10_3.py
```

The executable will be created under:

```text
dist\BitJita-Market-Assistant-v3.10.3.exe
```

### Antivirus / VirusTotal Note

Single-file executables created with tools such as PyInstaller can occasionally trigger heuristic antivirus detections or Windows SmartScreen warnings even when the source code is clean.

The Windows executable is currently **unsigned**. The complete source code is available in this repository so users can inspect it or run the Python version directly if they prefer.

## Configuration

Local settings are stored under:

```text
%LOCALAPPDATA%\BitJita Market Assistant\config.json
```

The configuration can contain settings such as:

- Detected BitJita API endpoint
- Selected BitJita player
- Starting locations
- Active starting location

The application does not store BitCraft login credentials.

## Data Source

Market, Claim, item, order, player inventory, housing, vault, buy-order, and historical market information is retrieved from **BitJita**:

[https://bitjita.com/](https://bitjita.com/)

Market prices, orders, availability, inventory data, and API behavior can change at any time.

## Privacy

BitJita Market Assistant does not require a BitCraft account login.

It queries BitJita data and stores only limited local application configuration needed for convenience features such as saved player and starting-location selection.

## About

Developed by **Aron** with the help of AI.

Discord:

```text
kamarasa_
```

## Feedback / Bug Reports

If you find a bug or have a suggestion:

- Open a GitHub Issue
- Contact `kamarasa_` on Discord

When reporting an issue, please include:

- Application version
- What you were trying to do
- Item name / quantity where relevant
- Selected Region / Claim where relevant
- Error message or unexpected result
- Screenshot if possible

## License

Licensed under the **MIT License**. See [LICENSE](LICENSE) for details.
