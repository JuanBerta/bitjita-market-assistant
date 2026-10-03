#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BitJita Market Assistant - GUI v3.10.3

Features
--------
1) Item Search
   - Item-name autocomplete while typing
   - Item Type, Region, Rarity and Tier filters
   - Active SELL orders
   - Sort by price, distance from the selected starting location,
     or price + distance

2) Shopping List
   - Add multiple items with rarity, tier and quantity
   - Sell-order purchase planning plus Buy Order Planning Mode
   - Buy Order pricing by highest active buy price or BitJita 24h/7d/30d VWAP
   - Cheapest, Nearest and Balanced purchase plans
   - Up to three selectable starting locations
   - Area filters:
       * Everywhere
       * Current region only
       * Within a maximum distance from the starting location
   - Purchase plan and route summary

Installation
------------
    python -m pip install requests

Run
---
    python bitjita_market_assistant_gui.py
"""

from __future__ import annotations

import math
import threading
import time
import webbrowser
import json
import os
import re
from urllib.parse import urljoin, urlparse
from collections import defaultdict
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
import tkinter as tk
from tkinter import ttk, messagebox

import requests


# ---------------------------------------------------------------------------
# Ayarlar
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://bitjita.com/api"
SITE_URL = "https://bitjita.com"

DISCORD_ICON_PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAABwAAAAcCAYAAAByDd+UAAAABmJLR0QA/wD/AP+gvaeTAAAC2UlEQVRIie2UTWhdVRSFv7Xv1YAmrRIrITRSHLShOrBG0Vkrjkuh8MhNQbA/L6UFJY7sIEogTkpBrD9U8jIKtk1aOqgTJ8V26KBikaLRQilI0x+1aV6q1uTdsx3kJfTd3ltSyZt1zc7e66xv38M9Bx5phaUHNZOdf3cR1950eB3X4YnRtp/zfKW9sxujEN6R9F3N4jMnv3zi6rKBpf5bq82jt4W9Bd5zT+t0wI9EUocHtQDI/N/U/bqhfcC2us+B8y4fi1tqY0c/a68WAks7Z9dEsV8Enn3Qly9bzvXHW3hx7ItVfy6W7N5+FPmhFYMBiI65OQ42lupKdk9vwqLz2SFWQMGwnmOV1gs0hFs01AQYgAXC0OJCAKVd1Q1RxE9NAgK4Q/dEZdWvBmBGuYkwAJnYwwLEJZE0EQaA4wm41Nt/+2W5fV/gu+XSoMOkuW8FBrj/7rrQpzhfu1iP+0eI9rwwwzbFQpuLpgpY74mR1jP15dmkXAV4r3FyfT5eaRuoL79N9sxOgp/Ny0tJNxvBXingTZ2oLMEWJxzLmmRpQ218tO0c8t/yAoV6DNGdz1MtW3EnZGsW4vt8uNL8TNYb+Nr8nj+X9M+8lskpZV1BoaHWW555FVhXAOxSUq7OAY8VGK66613kFxHb5QwDccaTCj4IcErwAvLDuLoK8v5RUq56QbMZSg0oOu9mqGbATG5LXAYuPWyixC/AlYJ21cAH8qBy7rrrAK43XPrE8QvAfE7IPPIfBB8LbfGgQeBu1uRwG/mAAJJdf3Vi4RDyPrIvifTh+EjbMMCWIY/XTE13RqnaPZIC4Y/fO5+eOje0cIWS8swwaDDDCsDRWNH7X408ea0hfEf5zktB6QFc21n4c29aHLqPHXlquuCIGtTXX33GA5P1p20e10mhg8dHW39cmj9vY2n/nY6olva5MzlRWf3NcmBL0N3VrcH8efNo/Pho642H2ftI/0v/AVF4ACLLinHWAAAAAElFTkSuQmCC"

# API endpoint cache. The app keeps using the known-good endpoint and only
# tries discovery if that endpoint stops working.
CONFIG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "BitJita Market Assistant",
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

_api_lock = threading.Lock()
_api_discovery_attempted = False

def _is_allowed_api_url(url: str) -> bool:
    """Only accept HTTPS endpoints on bitjita.com or its subdomains."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (host == "bitjita.com" or host.endswith(".bitjita.com"))
    except Exception:
        return False

def _normalize_base_url(url: str) -> str | None:
    if not url:
        return None
    url = str(url).strip().replace("\\/", "/").rstrip("/")
    if not _is_allowed_api_url(url):
        return None
    return url

def _load_config_data() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_config_data(data: dict) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        # Config failures must never stop the application.
        pass


def _load_cached_api_url() -> str | None:
    data = _load_config_data()
    return _normalize_base_url(data.get("api_base_url"))


def _save_cached_api_url(url: str) -> None:
    data = _load_config_data()
    data["api_base_url"] = url
    _save_config_data(data)


def _load_cached_player() -> tuple[str | None, str | None]:
    data = _load_config_data()
    player_id = data.get("player_entity_id")
    player_name = data.get("player_name")

    player_id = str(player_id).strip() if player_id not in (None, "") else None
    player_name = str(player_name).strip() if player_name not in (None, "") else None
    return player_id, player_name


def _save_cached_player(player_id: str, player_name: str) -> None:
    data = _load_config_data()
    data["player_entity_id"] = str(player_id).strip()
    data["player_name"] = str(player_name).strip()
    _save_config_data(data)


def _load_cached_start_locations():
    data = _load_config_data()

    locations = data.get("start_locations")
    active = data.get("active_start_location", 0)

    if not isinstance(locations, list):
        return None, 0

    cleaned = []
    for raw in locations[:3]:
        if not isinstance(raw, dict):
            raw = {}
        cleaned.append({
            "claim": str(raw.get("claim") or "").strip(),
            "region": str(raw.get("region") or "").strip(),
            "x": str(raw.get("x") or "").strip(),
            "z": str(raw.get("z") or "").strip(),
        })

    while len(cleaned) < 3:
        cleaned.append({"claim": "", "region": "", "x": "", "z": ""})

    try:
        active = int(active)
    except (TypeError, ValueError):
        active = 0

    active = min(2, max(0, active))
    return cleaned, active


def _save_cached_start_locations(locations, active_index):
    data = _load_config_data()
    data["start_locations"] = locations
    data["active_start_location"] = int(active_index)
    _save_config_data(data)


BASE_URL = _load_cached_api_url() or DEFAULT_BASE_URL

RARITIES = ["Any", "Common", "Uncommon", "Rare", "Epic", "Legendary"]
TIERS = ["Any"] + [f"T{i}" for i in range(1, 11)]

ARMOR_PIECE_SUFFIXES = [
    # Leather / cloth-like pieces
    "Belt",
    "Cap",
    "Leggings",
    "Gloves",
    "Shirt",
    "Boots",
    "Shorts",

    # Metal armor pieces seen on BitJita
    "Bracers",
    "Legguards",

    # Extra common armor suffixes for forward compatibility
    "Helmet",
    "Helm",
    "Chestplate",
    "Greaves",
    "Gauntlets",
    "Cuirass",
    "Hood",
    "Robe",
    "Trousers",
    "Pants",
    "Shoes",
]

ARMOR_CATEGORY_BY_TYPE = {
    "Leather": "Leather Clothing",
    "Metal": "Metal Armor",
    "Cloth": "Cloth Clothing",
}

ARMOR_CATEGORY_KEYWORDS = {
    "Leather": ("leather", "clothing"),
    "Metal": ("metal", "armor"),
    "Cloth": ("cloth", "clothing"),
}

LEATHER_SETS = {
    "Rough Leather Set": {"prefix": "Rough Leather", "tier": "T1"},
    "Simple Leather Set": {"prefix": "Simple Leather", "tier": "T2"},
    "Sturdy Leather Set": {"prefix": "Sturdy Leather", "tier": "T3"},
    "Fine Leather Set": {"prefix": "Fine Leather", "tier": "T4"},
    "Exquisite Leather Set": {"prefix": "Exquisite Leather", "tier": "T5"},
    "Peerless Leather Set": {"prefix": "Peerless Leather", "tier": "T6"},
    "Ornate Leather Set": {"prefix": "Ornate Leather", "tier": "T7"},
    "Pristine Leather Set": {"prefix": "Pristine Leather", "tier": "T8"},
    "Magnificent Leather Set": {"prefix": "Magnificent Leather", "tier": "T9"},
    "Flawless Leather Set": {"prefix": "Flawless Leather", "tier": "T10"},
}

DEFAULT_START = {
    "claim": "Ba Sing Se",
    "region": "Zephra",
    # BitJita: N 8018, E 9422
    # API koordinat düzeni: X = East (E), Z = North (N)
    "x": 9422.0,
    "z": 8018.0,
}

# Shopping-list optimizasyonunda her item için bütün marketi taşımak yerine
# hem en ucuz hem en yakın seçeneklerin birleşimini tutuyoruz.
MAX_CANDIDATES_PER_ITEM = 16

# DP state sayısı aşırı büyürse en umut verici state'leri tut.
MAX_OPTIMIZER_STATES = 50000

# BitJita Claim locationX/locationZ values map to BitCraft Small Hex positions,
# but use a 3x coordinate scale. Normalize by 3, then measure on the hex grid.

session = requests.Session()
session.headers.update({
    "User-Agent": "BitJita-Market-Assistant/3.7",
    "Accept": "application/json",
})


# ---------------------------------------------------------------------------
# Performance caches
# ---------------------------------------------------------------------------

CLAIM_CATALOG_TTL = 300.0       # 5 minutes
MARKET_SEARCH_TTL = 20.0        # short-lived, prices/listings change often
ORDER_CACHE_TTL = 15.0          # active sell orders
BUY_ORDER_CACHE_TTL = 15.0      # active buy orders
PRICE_HISTORY_CACHE_TTL = 60.0  # historical market statistics
MAX_API_WORKERS = 8

_perf_lock = threading.RLock()

_claim_catalog_cache = {
    "timestamp": 0.0,
    "claims": [],
    "by_id": {},
}

_market_search_cache = {}
_order_cache = {}
_buy_order_cache = {}
_price_history_cache = {}


def _cache_get(cache, key, ttl):
    now = time.monotonic()
    with _perf_lock:
        entry = cache.get(key)
        if not entry:
            return None
        timestamp, value = entry
        if now - timestamp > ttl:
            cache.pop(key, None)
            return None
        return value


def _cache_set(cache, key, value):
    with _perf_lock:
        cache[key] = (time.monotonic(), value)


def _index_claims(claims):
    by_id = {}
    for claim in claims:
        claim_id = first_value(claim, "entityId", "id")
        if claim_id not in (None, ""):
            by_id[str(claim_id)] = claim
    return by_id


def get_claim_catalog(force_refresh=False):
    """
    Download the full BitJita Claim catalogue once and reuse it.

    Region dropdowns, Claim autocomplete, starting-location resolution and
    order normalization all share this catalogue instead of independently
    paging through /claims.
    """
    now = time.monotonic()

    with _perf_lock:
        cached_claims = _claim_catalog_cache["claims"]
        age = now - _claim_catalog_cache["timestamp"]
        if cached_claims and not force_refresh and age < CLAIM_CATALOG_TTL:
            return cached_claims

    claims = []
    seen = set()
    page = 1
    limit = 100

    while page <= 500:
        data = api_get(
            "/claims",
            params={
                "page": page,
                "limit": limit,
                "sort": "name",
                "order": "asc",
            },
        )

        rows = data.get("claims") or []
        if not rows:
            break

        added = 0
        for claim in rows:
            claim_id = first_value(claim, "entityId", "id")
            dedupe_key = (
                str(claim_id)
                if claim_id not in (None, "")
                else (
                    str(claim.get("name") or "").casefold(),
                    str(claim.get("regionName") or "").casefold(),
                )
            )

            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            claims.append(claim)
            added += 1

        if len(rows) < limit:
            break

        # Defensive protection in case an API deployment ignores page=.
        if added == 0:
            break

        page += 1

    claims.sort(
        key=lambda claim: str(claim.get("name") or "").casefold()
    )

    with _perf_lock:
        _claim_catalog_cache["timestamp"] = time.monotonic()
        _claim_catalog_cache["claims"] = claims
        _claim_catalog_cache["by_id"] = _index_claims(claims)

    return claims


def get_cached_claim_by_id(claim_id):
    if not claim_id:
        return None

    with _perf_lock:
        claim = _claim_catalog_cache["by_id"].get(str(claim_id))
        timestamp = _claim_catalog_cache["timestamp"]

    if claim is not None and time.monotonic() - timestamp < CLAIM_CATALOG_TTL:
        return claim

    return None


# ---------------------------------------------------------------------------
# API yardımcıları
# ---------------------------------------------------------------------------

def _request_json(base_url: str, path: str, params=None):
    url = f"{base_url.rstrip('/')}{path}"
    response = session.get(url, params=params, timeout=25)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            "BitJita returned a non-JSON response.\n"
            f"URL: {response.url}\n"
            f"HTTP: {response.status_code}\n"
            f"Response start: {response.text[:500]}"
        ) from exc


def _api_candidate_works(base_url: str) -> bool:
    """Verify a candidate with a lightweight endpoint the app already uses."""
    try:
        data = _request_json(
            base_url,
            "/claims",
            params={"q": "Ba Sing Se", "page": 1, "limit": 1},
        )
        return isinstance(data, dict) and "claims" in data
    except Exception:
        return False


def _extract_api_candidates(text: str, source_url: str):
    """Extract plausible BitJita API base URLs from HTML/JavaScript text."""
    if not text:
        return []

    cleaned = (
        text.replace("\\/", "/")
            .replace("\u002F", "/")
            .replace("\u003A", ":")
    )
    found = []

    # Absolute BitJita URLs, including a possible dedicated api subdomain.
    for match in re.findall(r'https://(?:[A-Za-z0-9-]+\.)*bitjita\.com[^\"\'\s<>)]*', cleaned, flags=re.I):
        candidate = match.rstrip("/;,\\")
        for marker in ("/claims", "/market"):
            if marker in candidate:
                candidate = candidate.split(marker, 1)[0]
                break
        parsed = urlparse(candidate)
        if parsed.hostname and parsed.hostname.lower().startswith("api."):
            found.append(f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/"))
        elif "/api" in parsed.path:
            api_path = parsed.path.split("/api", 1)[0] + "/api"
            found.append(f"{parsed.scheme}://{parsed.netloc}{api_path}")

    # Relative /api/... references in BitJita's own frontend bundles.
    if re.search(r'[\"\']?/api/(?:claims|market)', cleaned, flags=re.I):
        found.append(urljoin(source_url, "/api"))

    # Keep order and remove invalid/duplicate candidates.
    unique = []
    seen = set()
    for value in found:
        value = _normalize_base_url(value)
        if value and value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def discover_api_base_url() -> str | None:
    """Try known official endpoints, then inspect BitJita's frontend for API references."""
    candidates = []

    def add(value):
        value = _normalize_base_url(value)
        if value and value not in candidates:
            candidates.append(value)

    add(BASE_URL)
    add(DEFAULT_BASE_URL)
    add("https://api.bitjita.com")

    # First test the obvious official candidates.
    for candidate in list(candidates):
        if _api_candidate_works(candidate):
            return candidate

    # If those fail, inspect the official site and a limited number of its JS bundles.
    try:
        homepage = session.get(SITE_URL, timeout=15)
        homepage.raise_for_status()
        for candidate in _extract_api_candidates(homepage.text, homepage.url):
            add(candidate)

        script_urls = []
        for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', homepage.text, flags=re.I):
            script_url = urljoin(homepage.url, src)
            parsed = urlparse(script_url)
            if parsed.hostname and (parsed.hostname == "bitjita.com" or parsed.hostname.endswith(".bitjita.com")):
                if script_url not in script_urls:
                    script_urls.append(script_url)
            if len(script_urls) >= 12:
                break

        for script_url in script_urls:
            try:
                js = session.get(script_url, timeout=12)
                js.raise_for_status()
                for candidate in _extract_api_candidates(js.text, script_url):
                    add(candidate)
            except Exception:
                continue
    except Exception:
        pass

    for candidate in candidates:
        if _api_candidate_works(candidate):
            return candidate
    return None


def api_get(path: str, params=None):
    global BASE_URL, _api_discovery_attempted

    try:
        return _request_json(BASE_URL, path, params=params)
    except Exception as first_error:
        # Only one thread performs discovery; other API callers reuse the result.
        with _api_lock:
            # Another thread may already have repaired BASE_URL while we were waiting.
            try:
                return _request_json(BASE_URL, path, params=params)
            except Exception:
                pass

            if not _api_discovery_attempted:
                _api_discovery_attempted = True
                discovered = discover_api_base_url()
                if discovered:
                    BASE_URL = discovered
                    _save_cached_api_url(BASE_URL)
                    return _request_json(BASE_URL, path, params=params)

        raise RuntimeError(
            "BitJita API could not be reached, and a working official API endpoint "
            "could not be detected automatically."
        ) from first_error


def first_value(data, *keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).replace(",", "").strip()
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return None


def normalize_item(raw):
    raw_market_type = first_value(
        raw,
        "itemOrCargo", "marketType", "itemType", "item_type",
    )
    market_type = "item"
    if isinstance(raw_market_type, str):
        raw_cf = raw_market_type.strip().casefold()
        if "cargo" in raw_cf or raw_cf == "1":
            market_type = "cargo"
    elif raw_market_type == 1:
        market_type = "cargo"

    return {
        "id": first_value(raw, "id", "itemId"),
        "name": first_value(raw, "name", "itemName") or "",
        "tier": to_number(first_value(raw, "tier", "itemTier")),
        "rarity": first_value(raw, "rarityStr", "itemRarityStr") or "",
        "category": first_value(
            raw,
            "tag", "itemTag", "category", "categoryName"
        ) or "",
        "market_type": market_type,
        "raw": raw,
    }


@lru_cache(maxsize=4096)
def get_claim(claim_id: str):
    if not claim_id:
        return {}

    cached = get_cached_claim_by_id(claim_id)
    if cached is not None:
        return cached

    # If the catalogue has not been loaded yet, prefer one shared catalogue
    # request over potentially dozens/hundreds of per-order Claim requests.
    with _perf_lock:
        catalogue_loaded = bool(_claim_catalog_cache["claims"])

    if not catalogue_loaded:
        try:
            get_claim_catalog()
            cached = get_cached_claim_by_id(claim_id)
            if cached is not None:
                return cached
        except Exception:
            pass

    # Fallback for newly-created claims not present in the cached catalogue.
    try:
        data = api_get(f"/claims/{claim_id}")
        claim = data.get("claim") or {}
        return claim
    except Exception:
        return {}


def claim_coordinates(claim):
    x = to_number(first_value(
        claim,
        "locationX", "x", "centerX", "coordinateX", "posX"
    ))
    z = to_number(first_value(
        claim,
        "locationZ", "z", "centerZ", "coordinateZ", "posZ", "y"
    ))
    return x, z


def normalize_order(order, item):
    nested_claim = order.get("claim") if isinstance(order, dict) else None

    claim_id = first_value(
        order,
        "claimEntityId",
        "claimId",
        "marketClaimEntityId",
    )
    if not claim_id and isinstance(nested_claim, dict):
        claim_id = first_value(nested_claim, "entityId", "id")

    # Read the Claim identity exposed by the market order first.
    # This is important because a stale/mismatched claim-id cache entry must
    # never make (for example) a Solvenar order inherit another Claim's coords.
    order_claim_name = first_value(order, "claimName", "marketName")
    if not order_claim_name and isinstance(nested_claim, dict):
        order_claim_name = first_value(nested_claim, "name")

    order_region = first_value(order, "regionName", "region")
    if not order_region and isinstance(nested_claim, dict):
        order_region = first_value(nested_claim, "regionName", "region")

    order_region_id = first_value(order, "regionId", "regionID")
    if order_region_id in (None, "") and isinstance(nested_claim, dict):
        order_region_id = first_value(nested_claim, "regionId", "regionID")

    claim_data = get_claim(str(claim_id)) if claim_id else {}

    # Validate that the ID-resolved Claim is actually the Claim named by the
    # market order. If not, resolve by Claim name + Region from the shared
    # BitJita catalogue and use that position instead.
    claim_data_name = str(
        first_value(claim_data, "name") or ""
    ).strip()

    resolved_by_name = None
    if order_claim_name:
        names_match = (
            claim_data_name
            and claim_data_name.casefold()
            == str(order_claim_name).strip().casefold()
        )

        if not names_match:
            preferred_region = str(order_region or "").strip()

            rid = normalize_region_id(order_region_id)
            if preferred_region and rid:
                preferred_region = f"{preferred_region} {rid}"

            try:
                resolved_by_name = resolve_claim_by_name(
                    str(order_claim_name).strip(),
                    preferred_region or None,
                )
            except Exception:
                resolved_by_name = None

    if resolved_by_name:
        claim_name = resolved_by_name.get("claim") or order_claim_name
        region = resolved_by_name.get("region") or order_region or "?"
        region_id = resolved_by_name.get("region_id")
        x = resolved_by_name.get("x")
        z = resolved_by_name.get("z")

        # Keep the resolved Claim ID when available; it is more trustworthy
        # than an inconsistent order-side ID.
        resolved_claim_id = resolved_by_name.get("claim_id")
        if resolved_claim_id:
            claim_id = resolved_claim_id
    else:
        claim_name = (
            order_claim_name
            or first_value(claim_data, "name")
            or "?"
        )
        region = (
            order_region
            or first_value(claim_data, "regionName", "region")
            or "?"
        )

        region_id = order_region_id
        if region_id in (None, ""):
            region_id = first_value(claim_data, "regionId", "regionID")

        # Claim endpoint/catalogue coordinates remain authoritative when
        # the Claim identity has been validated.
        x, z = claim_coordinates(claim_data)

    region_id = (
        str(region_id).strip()
        if region_id not in (None, "")
        else None
    )

    shard = first_value(
        order,
        "shardName", "shard", "realmName", "realm",
        "serverName", "server"
    )
    if not shard:
        shard = first_value(
            claim_data,
            "shardName", "shard", "realmName", "realm",
            "serverName", "server"
        )
    shard = str(shard) if shard not in (None, "") else "?"

    seller = first_value(
        order,
        "ownerUsername",
        "sellerUsername",
        "sellerName",
        "seller",
        "username",
    ) or "?"

    price = to_number(first_value(
        order,
        "price",
        "unitPrice",
        "priceThreshold",
    ))

    quantity = to_number(first_value(
        order,
        "quantity",
        "count",
        "remainingQuantity",
        "amount",
    )) or 1

    # If validated Claim coordinates are unavailable, use order coordinates
    # only as a last-resort fallback.
    if x is None or z is None:
        ox = to_number(first_value(
            order,
            "locationX", "x", "centerX", "coordinateX", "posX"
        ))
        oz = to_number(first_value(
            order,
            "locationZ", "z", "centerZ", "coordinateZ", "posZ", "y"
        ))
        if x is None:
            x = ox
        if z is None:
            z = oz

    return {
        "item_id": item["id"],
        "item": item["name"],
        "tier": item["tier"],
        "rarity": item["rarity"],
        "price": price,
        "quantity": int(quantity),
        "claim_id": str(claim_id) if claim_id else None,
        "claim": claim_name,
        "region": region,
        "region_id": region_id,
        "shard": shard,
        "seller": seller,
        "x": x,
        "z": z,
    }


@lru_cache(maxsize=1)
def _exact_market_categories():
    """Return the exact category names advertised by BitJita."""
    data = api_get(
        "/market",
        params={"hasSellOrders": "true"},
    )

    raw_categories = (data.get("data") or {}).get("categories") or []
    categories = []
    seen = set()

    for raw in raw_categories:
        if isinstance(raw, str):
            name = raw.strip()
        elif isinstance(raw, dict):
            name = str(
                first_value(
                    raw,
                    "name", "category", "label", "tag", "itemTag"
                ) or ""
            ).strip()
        else:
            name = str(raw).strip()

        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            categories.append(name)

    categories.sort(key=str.casefold)
    return tuple(categories)


def market_categories():
    """
    Return Item Type choices.

    BitJita categories are often specific tags such as "Basic Food" or
    "Animal Food". We also expose useful family choices such as "Food" so a
    single selection can search all matching Food categories.
    """
    exact = list(_exact_market_categories())
    synthetic = set()

    # "Food" is a user-friendly family selector. BitJita classifies many
    # prepared foods under "Meal", so expose Food when either kind exists.
    if any(
        ("food" in c.casefold().split()) or ("meal" in c.casefold().split())
        for c in exact
    ):
        synthetic.add("Food")

    # A similar family selector is useful for the many profession-specific tools.
    tool_matches = [c for c in exact if "tool" in c.casefold().split()]
    if len(tool_matches) >= 2:
        synthetic.add("Tool")

    # Put broad family choices first, then the exact API categories.
    broad = sorted(synthetic, key=str.casefold)
    remaining = [
        c for c in exact
        if c.casefold() not in {b.casefold() for b in broad}
    ]
    return broad + remaining


def _category_matches(selected, exact_category):
    """
    Family-aware category match.

    "Food" matches "Basic Food", "Animal Food", etc.
    Exact choices such as "Basic Food" remain exact.
    """
    selected_cf = str(selected or "").strip().casefold()
    exact_cf = str(exact_category or "").strip().casefold()

    if not selected_cf or selected_cf == "any":
        return True

    if selected_cf == exact_cf:
        return True

    # Friendly family aliases.
    # BitJita uses "Meal" for many cooked/finished food items, while other
    # categories may literally contain "Food". Treat both as Food.
    if selected_cf == "food":
        words = set(exact_cf.split())
        return "food" in words or "meal" in words

    # Single-word family choices match a whole word in the exact category.
    if " " not in selected_cf:
        return selected_cf in exact_cf.split()

    return False


def market_search(
    query="",
    rarity="Any",
    tier="Any",
    category="Any",
    exact_preferred=True,
):
    cache_key = (
        str(query or "").strip().casefold(),
        str(rarity or "Any").casefold(),
        str(tier or "Any").casefold(),
        str(category or "Any").casefold(),
        bool(exact_preferred),
    )
    cached = _cache_get(_market_search_cache, cache_key, MARKET_SEARCH_TTL)
    if cached is not None:
        return [dict(item) for item in cached]

    query = (query or "").strip()
    category = (category or "Any").strip()

    base_params = {
        "hasSellOrders": "true",
    }
    if query:
        base_params["q"] = query

    raw_items = []

    if category == "Any":
        data = api_get("/market", params=base_params)
        raw_items.extend((data.get("data") or {}).get("items") or [])
    else:
        # Resolve a broad UI choice (e.g. Food) into the exact BitJita
        # categories accepted by /api/market.
        exact_categories = list(_exact_market_categories())
        matching_categories = [
            cat for cat in exact_categories
            if _category_matches(category, cat)
        ]

        # If the API ever returns a category not present in the category list,
        # preserve the user's exact selection as a safe fallback.
        if not matching_categories:
            matching_categories = [category]

        for exact_category in matching_categories:
            params = dict(base_params)
            params["category"] = exact_category

            data = api_get("/market", params=params)
            raw_items.extend((data.get("data") or {}).get("items") or [])

    items = [normalize_item(raw) for raw in raw_items]

    if rarity != "Any":
        items = [
            item for item in items
            if str(item["rarity"]).casefold() == rarity.casefold()
        ]

    if tier != "Any":
        wanted_tier = int(tier[1:])
        items = [item for item in items if item["tier"] == wanted_tier]

    if exact_preferred and query:
        exact = [
            item for item in items
            if item["name"].strip().casefold() == query.casefold()
        ]
        if exact:
            items = exact
        else:
            q = query.casefold()
            items = [
                item for item in items
                if q in item["name"].casefold()
            ]

    unique = {}
    for item in items:
        if item["id"] is not None:
            unique[str(item["id"])] = item

    result = list(unique.values())
    _cache_set(
        _market_search_cache,
        cache_key,
        [dict(item) for item in result],
    )
    return result


def _armor_piece_suffix(name):
    """Return the matching armor-piece suffix for an item name."""
    name_cf = str(name or "").strip().casefold()

    # Longest suffix first so future multi-word suffixes can be added safely.
    for suffix in sorted(ARMOR_PIECE_SUFFIXES, key=len, reverse=True):
        suffix_cf = suffix.casefold()
        if name_cf.endswith(" " + suffix_cf):
            return suffix
    return None


def _armor_set_prefix_from_item(name):
    suffix = _armor_piece_suffix(name)
    if not suffix:
        return None

    prefix = str(name).strip()[: -(len(suffix) + 1)].strip()
    return prefix or None


@lru_cache(maxsize=16)
def resolve_armor_category(armor_type):
    """
    Resolve the current BitJita market category for an armor family.

    BitJita currently uses names such as "Leather Clothing",
    "Cloth Clothing" and "Metal Armor". If those labels ever change,
    fall back to keyword matching against the categories advertised
    by /market.
    """
    preferred = ARMOR_CATEGORY_BY_TYPE.get(armor_type)
    if not preferred:
        return None

    try:
        exact_categories = list(_exact_market_categories())
    except Exception:
        exact_categories = []

    # Prefer an exact match.
    for category in exact_categories:
        if category.casefold() == preferred.casefold():
            return category

    # Otherwise look for a category containing the family keywords.
    keywords = ARMOR_CATEGORY_KEYWORDS.get(armor_type, ())
    for category in exact_categories:
        words = category.casefold()
        if all(keyword.casefold() in words for keyword in keywords):
            return category

    # Last fallback keeps the known current label.
    return preferred


@lru_cache(maxsize=16)
def discover_armor_sets(armor_type):
    """
    Discover set families from BitJita's real armor items.

    Returns tuples:
        (display_name, prefix, tier, category)

    Leather keeps the known tier progression as a reliable baseline.
    Metal and Cloth are discovered from their actual BitJita category data,
    so names such as Plated, Duelist, Woven, etc. do not need to be guessed.
    """
    armor_type = str(armor_type or "").strip()

    if armor_type == "Leather":
        return tuple(
            (
                set_name,
                definition["prefix"],
                definition["tier"],
                resolve_armor_category("Leather"),
            )
            for set_name, definition in LEATHER_SETS.items()
        )

    category = resolve_armor_category(armor_type)
    if not category:
        return tuple()

    data = api_get(
        "/market",
        params={
            "category": category,
        },
    )
    raw_items = (data.get("data") or {}).get("items") or []

    grouped = {}

    for raw in raw_items:
        item = normalize_item(raw)
        name = str(item.get("name") or "").strip()
        tier_num = item.get("tier")

        if not name or tier_num is None:
            continue

        prefix = _armor_set_prefix_from_item(name)
        if not prefix:
            continue

        # A set family is uniquely identified by prefix + tier + armor category.
        key = (prefix.casefold(), int(tier_num))
        record = grouped.setdefault(
            key,
            {
                "prefix": prefix,
                "tier": f"T{int(tier_num)}",
                "pieces": set(),
            },
        )
        suffix = _armor_piece_suffix(name)
        if suffix:
            record["pieces"].add(suffix)

    result = []
    for record in grouped.values():
        # Require at least 2 recognizable pieces to avoid treating a stray item
        # as a complete equipment-set family.
        if len(record["pieces"]) < 2:
            continue

        display_name = f"{record['prefix']} Set"
        result.append(
            (
                display_name,
                record["prefix"],
                record["tier"],
                category,
            )
        )

    result.sort(
        key=lambda row: (
            int(row[2][1:]) if row[2].startswith("T") and row[2][1:].isdigit() else 999,
            row[0].casefold(),
        )
    )
    return tuple(result)


@lru_cache(maxsize=128)
def discover_armor_set_pieces(prefix, tier, category):
    """
    Discover the actual pieces belonging to one armor set.

    BitJita's category labels are not always consistent across endpoints, so
    category is used only as a first-pass hint. If that returns nothing, the
    lookup automatically falls back to prefix-only and then exact piece-name
    searches. Tier + exact item-name matching remain authoritative.
    """
    wanted_tier = None
    if isinstance(tier, str) and tier.upper().startswith('T'):
        try:
            wanted_tier = int(tier[1:])
        except ValueError:
            wanted_tier = None

    prefix_cf = prefix.casefold()
    found = {}

    def consider(raw_items):
        for raw in raw_items:
            item = normalize_item(raw)
            name = str(item.get('name') or '').strip()
            if not name:
                continue

            if wanted_tier is not None and item.get('tier') != wanted_tier:
                continue

            name_cf = name.casefold()
            if not name_cf.startswith(prefix_cf + ' '):
                continue

            suffix = _armor_piece_suffix(name)
            if not suffix:
                continue

            expected = f'{prefix} {suffix}'
            if name_cf == expected.casefold():
                found[suffix] = name

    # 1) Fast path: prefix + category.
    if category:
        try:
            data = api_get(
                '/market',
                params={
                    'q': prefix,
                    'category': category,
                },
            )
            consider((data.get('data') or {}).get('items') or [])
        except Exception:
            pass

    # 2) Important fallback: category names can differ between BitJita
    # endpoints, so search the prefix without a category restriction.
    if not found:
        data = api_get(
            '/market',
            params={
                'q': prefix,
            },
        )
        consider((data.get('data') or {}).get('items') or [])

    # 3) Last-resort exact probing. This also protects against /market search
    # returning only a limited subset for a broad prefix query.
    missing = [suffix for suffix in ARMOR_PIECE_SUFFIXES if suffix not in found]
    for suffix in missing:
        expected = f'{prefix} {suffix}'
        try:
            data = api_get(
                '/market',
                params={
                    'q': expected,
                },
            )
        except Exception:
            continue

        raw_items = (data.get('data') or {}).get('items') or []
        for raw in raw_items:
            item = normalize_item(raw)
            name = str(item.get('name') or '').strip()
            if name.casefold() != expected.casefold():
                continue
            if wanted_tier is not None and item.get('tier') != wanted_tier:
                continue
            found[suffix] = name
            break

    return tuple(
        found[suffix]
        for suffix in ARMOR_PIECE_SUFFIXES
        if suffix in found
    )

def market_regions():
    """Return all known BitJita regions from the shared Claim catalogue."""
    found = {}

    for claim in get_claim_catalog():
        region = str(
            first_value(claim, "regionName", "region") or ""
        ).strip()
        region_id = first_value(claim, "regionId", "regionID")

        if not region:
            continue

        rid = normalize_region_id(region_id)
        label = f"{region} {rid}" if rid else region
        found[label.casefold()] = label

    return sorted(found.values(), key=str.casefold)

def resolve_claim_by_name(name, preferred_region=None):
    """Resolve a Claim from the shared BitJita Claim catalogue."""
    if not name or len(name.strip()) < 2:
        return None

    wanted_name = name.strip().casefold()

    claims = [
        claim for claim in get_claim_catalog()
        if str(claim.get("name") or "").strip().casefold() == wanted_name
    ]

    if preferred_region:
        wanted_region, wanted_rid = parse_region_selection(preferred_region)

        same_region = []
        for claim in claims:
            claim_region = str(claim.get("regionName") or "").strip()
            claim_rid = normalize_region_id(claim.get("regionId"))

            if wanted_region and claim_region.casefold() != wanted_region.casefold():
                continue
            if wanted_rid and claim_rid and claim_rid != wanted_rid:
                continue

            same_region.append(claim)

        if same_region:
            claims = same_region

    if not claims:
        return None

    claim = claims[0]
    return {
        "claim": claim.get("name") or name,
        "region": claim.get("regionName") or preferred_region or "?",
        "region_id": claim.get("regionId"),
        "x": to_number(claim.get("locationX")),
        "z": to_number(claim.get("locationZ")),
        "claim_id": str(claim.get("entityId")) if claim.get("entityId") else None,
    }



def _claim_display_label(claim):
    name = str(claim.get("name") or "").strip()
    region = str(claim.get("regionName") or "").strip()
    rid = normalize_region_id(claim.get("regionId"))

    region_part = region
    if rid:
        region_part = f"{region} {rid}" if region else rid

    return f"{name} — {region_part}" if region_part else name


def _claim_name_from_display(value):
    return str(value or "").split(" — ", 1)[0].strip()


@lru_cache(maxsize=2048)
def claim_autocomplete_names(query, region_filter=""):
    """
    Filter the shared Claim catalogue locally.

    This avoids re-downloading every /claims page on every autocomplete
    keystroke or Region change.
    """
    query = str(query or "").strip().casefold()
    region_filter = str(region_filter or "").strip()

    wanted_region, wanted_rid = parse_region_selection(region_filter)

    labels = []
    seen = set()

    for claim in get_claim_catalog():
        claim_name = str(claim.get("name") or "").strip()
        if not claim_name:
            continue

        if query and query not in claim_name.casefold():
            continue

        if region_filter:
            claim_region = str(claim.get("regionName") or "").strip()
            claim_rid = normalize_region_id(claim.get("regionId"))

            if wanted_region and claim_region.casefold() != wanted_region.casefold():
                continue

            if wanted_rid and claim_rid and claim_rid != wanted_rid:
                continue

        label = _claim_display_label(claim)
        if not label:
            continue

        key = label.casefold()
        if key in seen:
            continue

        seen.add(key)
        labels.append(label)

    labels.sort(
        key=lambda value: (
            not _claim_name_from_display(value).casefold().startswith(query)
            if query else False,
            value.casefold(),
        )
    )
    return labels


def autocomplete_names(query):
    if len(query.strip()) < 2:
        return []

    data = api_get(
        "/market",
        params={
            "q": query.strip(),
            "hasSellOrders": "true",
        },
    )

    raw_items = (data.get("data") or {}).get("items") or []
    names = []
    seen = set()

    for raw in raw_items:
        name = str(first_value(raw, "name", "itemName") or "").strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)

    names.sort(key=lambda s: (not s.casefold().startswith(query.casefold()), s.casefold()))
    return names[:30]


def fetch_orders_for_item(item):
    item_id = str(item["id"])
    cached = _cache_get(_order_cache, item_id, ORDER_CACHE_TTL)
    if cached is not None:
        return [dict(order) for order in cached]

    data = api_get(f"/market/item/{item_id}")
    raw_orders = data.get("sellOrders") or []

    result = []
    for raw in raw_orders:
        order = normalize_order(raw, item)
        if order["price"] is not None:
            result.append(order)

    _cache_set(
        _order_cache,
        item_id,
        [dict(order) for order in result],
    )
    return result


def fetch_orders_for_items_parallel(items, cancel_check=None):
    """
    Fetch multiple item order books concurrently while respecting the short
    order cache. Returns one flattened list of normalized sell orders.
    """
    items = list(items or [])
    if not items:
        return []

    if len(items) == 1:
        if cancel_check and cancel_check():
            return []
        return fetch_orders_for_item(items[0])

    results = []
    workers = min(MAX_API_WORKERS, len(items))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_orders_for_item, item): item
            for item in items
        }

        for future in as_completed(futures):
            if cancel_check and cancel_check():
                for pending in futures:
                    pending.cancel()
                return []

            try:
                results.extend(future.result())
            except Exception:
                continue

    return results


BUY_ORDER_STRATEGIES = (
    "Highest Current Buy Price",
    "24h Average",
    "7d Average",
    "30d Average",
)


def _market_type_paths(item):
    market_type = str(item.get("market_type") or "item").casefold()
    if market_type == "cargo":
        return "cargo", "cargo"
    return "item", "items"


def market_search_for_buy_plan(query, rarity="Any", tier="Any"):
    """Resolve a Shopping List row without requiring an active sell order."""
    query = str(query or "").strip()
    cache_key = (
        "buy-plan-item-lookup",
        query.casefold(),
        str(rarity or "Any").casefold(),
        str(tier or "Any").casefold(),
    )
    cached = _cache_get(_market_search_cache, cache_key, MARKET_SEARCH_TTL)
    if cached is not None:
        return [dict(item) for item in cached]

    if not query:
        return []

    data = api_get("/market", params={"q": query})
    raw_items = (data.get("data") or {}).get("items") or []
    items = [normalize_item(raw) for raw in raw_items]

    if rarity != "Any":
        items = [
            item for item in items
            if str(item.get("rarity") or "").casefold() == rarity.casefold()
        ]

    if tier != "Any":
        wanted_tier = int(tier[1:])
        items = [item for item in items if item.get("tier") == wanted_tier]

    exact = [
        item for item in items
        if str(item.get("name") or "").strip().casefold() == query.casefold()
    ]
    if exact:
        items = exact

    unique = {}
    for item in items:
        if item.get("id") is None:
            continue
        key = (item.get("market_type", "item"), str(item["id"]))
        unique[key] = item

    result = list(unique.values())
    _cache_set(_market_search_cache, cache_key, [dict(item) for item in result])
    return result


def _decimal_price(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def get_active_buy_orders(item):
    """Return valid active buy orders from BitJita's item/cargo market detail."""
    singular_type, _history_type = _market_type_paths(item)
    cache_key = (singular_type, str(item.get("id")))
    cached = _cache_get(_buy_order_cache, cache_key, BUY_ORDER_CACHE_TTL)
    if cached is not None:
        return [dict(order) for order in cached]

    data = api_get(f"/market/{singular_type}/{item['id']}")
    raw_orders = data.get("buyOrders") or []
    valid = []

    for raw in raw_orders:
        if not isinstance(raw, dict):
            continue

        status = str(first_value(raw, "status", "orderStatus") or "").strip().upper()
        if status and status not in {"OPEN", "PARTIALLY_COMPLETED", "ACTIVE"}:
            continue

        remaining = to_number(first_value(
            raw,
            "remainingQuantity", "remainingStock", "remaining",
            "quantity", "count", "amount",
        ))
        if remaining is not None and remaining <= 0:
            continue

        price = _decimal_price(first_value(
            raw,
            "unitPrice", "price", "priceThreshold",
        ))
        if price is None or price <= 0:
            continue

        valid.append({
            "price": price,
            "remaining_quantity": remaining,
            "raw": raw,
        })

    _cache_set(_buy_order_cache, cache_key, [dict(order) for order in valid])
    return valid


def get_highest_buy_price(item):
    orders = get_active_buy_orders(item)
    if not orders:
        return None
    return max(order["price"] for order in orders)


def get_market_price_history(item):
    """
    Fetch BitJita's historical market statistics.

    BitJita exposes avg24h/avg7d/avg30d directly. Those site/API averages are
    VWAP values (volume-weighted average prices), with BitJita's own trade
    filtering applied. We therefore use them directly rather than recomputing
    an arithmetic mean locally.
    """
    _singular_type, history_type = _market_type_paths(item)
    cache_key = (history_type, str(item.get("id")))
    cached = _cache_get(_price_history_cache, cache_key, PRICE_HISTORY_CACHE_TTL)
    if cached is not None:
        return dict(cached)

    data = api_get(
        f"/market/{history_type}/{item['id']}/price-history",
        params={"bucket": "1 day", "limit": 30},
    )
    result = {
        "priceStats": dict(data.get("priceStats") or {}),
        "priceData": list(data.get("priceData") or []),
        "recentTrades": list(data.get("recentTrades") or []),
    }
    _cache_set(_price_history_cache, cache_key, result)
    return dict(result)


def get_historical_average_price(item, strategy):
    field_by_strategy = {
        "24h Average": ("avg24h", "24h"),
        "7d Average": ("avg7d", "7d"),
        "30d Average": ("avg30d", "30d"),
    }
    field_info = field_by_strategy.get(strategy)
    if not field_info:
        return None, None

    field, period = field_info
    history = get_market_price_history(item)
    value = _decimal_price((history.get("priceStats") or {}).get(field))
    return value, period


def build_buy_order_plan_item(shopping_row, strategy):
    """Build one buy-order planning row without falling back to another method."""
    result = {
        "item_id": None,
        "item_name": shopping_row.get("item") or "",
        "required_quantity": int(shopping_row.get("qty") or 1),
        "pricing_strategy": strategy,
        "suggested_unit_price": None,
        "estimated_total_cost": None,
        "data_source": None,
        "source_period": None,
        "status": "",
        "market_type": "item",
    }

    matches = market_search_for_buy_plan(
        shopping_row.get("item") or "",
        shopping_row.get("rarity") or "Any",
        shopping_row.get("tier") or "Any",
    )
    if not matches:
        result["status"] = "No matching item variant found"
        return result

    # Shopping List identifies variants by name/rarity/tier rather than ID.
    # Exact filtered matches are normally unique; prefer normal items if the
    # API ever returns an item/cargo naming collision.
    matches.sort(key=lambda x: x.get("market_type") == "cargo")
    item = matches[0]
    result["item_id"] = item.get("id")
    result["item_name"] = item.get("name") or result["item_name"]
    result["market_type"] = item.get("market_type") or "item"

    if strategy == "Highest Current Buy Price":
        price = get_highest_buy_price(item)
        result["data_source"] = "Active buy orders"
        result["source_period"] = "Current"
        if price is None:
            result["status"] = "No active buy orders found"
            return result
    else:
        price, period = get_historical_average_price(item, strategy)
        result["data_source"] = "BitJita priceStats VWAP"
        result["source_period"] = period
        if price is None:
            result["status"] = f"No {period or strategy} price data available"
            return result

    result["suggested_unit_price"] = price
    result["estimated_total_cost"] = price * Decimal(result["required_quantity"])
    result["status"] = "Ready"
    return result


# ---------------------------------------------------------------------------
# Distance ve market hesapları
# ---------------------------------------------------------------------------

BITJITA_COORD_SCALE = 3.0


def _normalize_bitjita_hex_coord(value):
    """
    BitJita Claim locationX/locationZ are stored at 3x the in-game Small Hex
    coordinate scale. Convert them back before hex-distance calculations.
    """
    if value is None:
        return None
    return float(value) / BITJITA_COORD_SCALE


def _small_hex_to_cube(x, z):
    """
    Convert BitJita Claim coordinates to BitCraft Small Hex cube coordinates.

    BitJita locationX/locationZ values use a 3x coordinate scale compared with
    the in-game Small Hex coordinates, so normalize by 3 before conversion.
    """
    col = int(round(_normalize_bitjita_hex_coord(x)))
    row = int(round(_normalize_bitjita_hex_coord(z)))

    cube_x = col - ((row - (row & 1)) // 2)
    cube_z = row
    cube_y = -cube_x - cube_z
    return cube_x, cube_y, cube_z


def format_distance(value):
    """
    Compact display formatter for hex distances.

    Examples:
        872  -> 872
        1100 -> 1.1k
        3945 -> 3.9k
    """
    if value is None:
        return "-"

    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)

    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k"

    return f"{value:.0f}"


def estimate_tp(distance):
    """
    Estimated teleport energy for an empty inventory.

    Observed in-game behavior:
        TP = ceil(distance / 400)
    """
    if distance is None:
        return None

    try:
        distance = float(distance)
    except (TypeError, ValueError):
        return None

    if distance <= 0:
        return 0

    return int(math.ceil(distance / 400.0))


def format_estimated_tp(distance):
    tp = estimate_tp(distance)
    return "-" if tp is None else str(tp)


def straight_distance(a, b):
    """
    Hex-grid distance between two BitCraft Small Hex positions.

    This replaces the old Euclidean hypot()*scale approximation, which could
    incorrectly rank claims (for example Stormhollow ahead of Shardvale from
    Ba Sing Se).
    """
    ax, az = a.get("x"), a.get("z")
    bx, bz = b.get("x"), b.get("z")

    if None in (ax, az, bx, bz):
        return None

    ac = _small_hex_to_cube(ax, az)
    bc = _small_hex_to_cube(bx, bz)

    return max(
        abs(ac[0] - bc[0]),
        abs(ac[1] - bc[1]),
        abs(ac[2] - bc[2]),
    )


def location_key(row):
    return row.get("claim_id") or (
        row.get("claim"),
        row.get("region"),
        row.get("x"),
        row.get("z"),
    )


def normalize_region_id(value):
    """Normalize 19 / R19 / r19 to R19."""
    if value in (None, "", "?"):
        return None

    text = str(value).strip()
    if text.isdigit():
        return f"R{text}"

    match = re.fullmatch(r"[Rr](\d+)", text)
    if match:
        return f"R{match.group(1)}"

    return text


def region_label(row):
    """Display a region as 'Zephyra R19' whenever regionId is available."""
    region = str(row.get("region") or "?").strip()
    region_id = normalize_region_id(row.get("region_id"))

    if not region_id:
        return region

    # Do not append the same code twice.
    if re.search(rf"(?:^|\s){re.escape(region_id)}(?:$|\s)", region, flags=re.I):
        return region

    return f"{region} {region_id}"


def parse_region_selection(value):
    """Split dropdown labels such as 'Zephyra R19' into name + normalized region ID."""
    value = str(value or "").strip()
    if not value or value == "Any":
        return None, None

    match = re.match(r"^(.*?)(?:\s+([Rr]\d+))$", value)
    if not match:
        return value, None

    return match.group(1).strip(), normalize_region_id(match.group(2))


def order_matches_region(order, selected_region):
    """
    Match market orders by the actual region name.

    The dropdown may show labels such as "Zephra R19", but the Rxx suffix is
    presentation metadata and is deliberately not required for matching.
    This avoids dropping valid orders when different BitJita endpoints expose
    the region identifier in different forms.
    """
    wanted_name, _wanted_id = parse_region_selection(selected_region)
    if wanted_name is None:
        return True

    order_name = str(order.get("region") or "").strip()
    return order_name.casefold() == wanted_name.casefold()


def group_purchase_options(orders, wanted_quantity):
    """
    Aynı claim içindeki sell order'ları fiyat sırasına dizer.
    İstenen adedi TEK BİR claim'den tamamlayabiliyorsa toplam maliyet çıkarır.

    Bu sayede shopping list optimizer, bir item için tek durakta alışveriş yapar;
    yolculuk sayısını gereksiz yere artırmaz.
    """
    by_location = defaultdict(list)

    for order in orders:
        by_location[location_key(order)].append(order)

    options = []

    for _, group in by_location.items():
        group = sorted(group, key=lambda x: x["price"])
        remaining = wanted_quantity
        total_cost = 0.0
        sellers = []

        for order in group:
            take = min(remaining, order["quantity"])
            if take <= 0:
                continue

            total_cost += take * order["price"]
            sellers.append({
                "seller": order["seller"],
                "qty": take,
                "unit_price": order["price"],
            })
            remaining -= take

            if remaining <= 0:
                break

        if remaining > 0:
            continue

        base = dict(group[0])
        base.update({
            "wanted_quantity": wanted_quantity,
            "total_cost": total_cost,
            "avg_unit_price": total_cost / wanted_quantity,
            "sellers_breakdown": sellers,
        })
        options.append(base)

    return options


def apply_location_filter(options, start, filter_mode, region_name, max_distance):
    result = []

    for option in options:
        d = straight_distance(start, option)
        option = dict(option)
        option["distance_from_start"] = d

        if filter_mode == "region":
            if str(option.get("region", "")).casefold() != region_name.casefold():
                continue

        elif filter_mode == "distance":
            if d is None or d > max_distance:
                continue

        result.append(option)

    return result


def prune_candidates(options, max_count=MAX_CANDIDATES_PER_ITEM):
    if len(options) <= max_count:
        return options

    cheapest = sorted(options, key=lambda x: x["total_cost"])[: max_count // 2]

    nearest = sorted(
        options,
        key=lambda x: (
            float("inf") if x["distance_from_start"] is None
            else x["distance_from_start"]
        ),
    )[: max_count // 2]

    merged = {}
    for option in cheapest + nearest:
        merged[location_key(option)] = option

    result = list(merged.values())
    result.sort(key=lambda x: x["total_cost"])
    return result[:max_count]


# ---------------------------------------------------------------------------
# En kısa açık rota (start -> tüm marketler, başlangıca geri dönmek yok)
# ---------------------------------------------------------------------------

def shortest_open_route(start, locations):
    unique = {}
    for loc in locations:
        unique[location_key(loc)] = loc
    locs = list(unique.values())

    if not locs:
        return 0.0, []

    if any(straight_distance(start, loc) is None for loc in locs):
        return None, locs

    n = len(locs)

    # Çok fazla durakta Held-Karp patlamasın.
    # Böyle bir durumda nearest-neighbour rotası kullan.
    if n > 14:
        remaining = locs[:]
        current = start
        route = []
        total = 0.0

        while remaining:
            nxt = min(remaining, key=lambda loc: straight_distance(current, loc))
            total += straight_distance(current, nxt)
            route.append(nxt)
            current = nxt
            remaining.remove(nxt)

        return total, route

    # Held-Karp DP
    dp = {}
    parent = {}

    for i, loc in enumerate(locs):
        mask = 1 << i
        dp[(mask, i)] = straight_distance(start, loc)
        parent[(mask, i)] = None

    for mask in range(1, 1 << n):
        for last in range(n):
            state = (mask, last)
            if state not in dp:
                continue

            current_cost = dp[state]

            for nxt in range(n):
                bit = 1 << nxt
                if mask & bit:
                    continue

                d = straight_distance(locs[last], locs[nxt])
                if d is None:
                    continue

                new_mask = mask | bit
                new_state = (new_mask, nxt)
                new_cost = current_cost + d

                if new_state not in dp or new_cost < dp[new_state]:
                    dp[new_state] = new_cost
                    parent[new_state] = state

    full_mask = (1 << n) - 1
    endings = [
        (cost, last)
        for (mask, last), cost in dp.items()
        if mask == full_mask
    ]

    if not endings:
        return None, locs

    best_cost, best_last = min(endings)
    state = (full_mask, best_last)
    reversed_route = []

    while state is not None:
        mask, last = state
        reversed_route.append(locs[last])
        state = parent[state]

    reversed_route.reverse()
    return best_cost, reversed_route


# ---------------------------------------------------------------------------
# Shopping list optimizer
# ---------------------------------------------------------------------------

def route_penalty_without_coords(choices):
    claims = {location_key(c) for c in choices}
    regions = {c.get("region") for c in choices}
    # Only fallback; gerçek koordinat varsa kullanılmaz.
    return max(0, len(claims) - 1) * 50 + max(0, len(regions) - 1) * 200


def optimize_shopping_list(item_candidates, start, distance_weight):
    """
    Her shopping-list satırı için bir satın alma lokasyonu seçer.

    State anahtarı = kullanılan lokasyon seti.
    Aynı lokasyon setine ulaşan iki çözümden item toplamı düşük olan diğerini
    domine eder. Böylece product(*candidates) kadar patlamadan çok daha küçük
    bir state uzayıyla çalışır.
    """
    states = {
        frozenset(): {
            "item_total": 0.0,
            "choices": [],
        }
    }

    for candidates in item_candidates:
        new_states = {}

        for state_locations, state in states.items():
            for candidate in candidates:
                key = location_key(candidate)
                new_locations = frozenset(set(state_locations) | {key})
                new_total = state["item_total"] + candidate["total_cost"]

                old = new_states.get(new_locations)
                if old is None or new_total < old["item_total"]:
                    new_states[new_locations] = {
                        "item_total": new_total,
                        "choices": state["choices"] + [candidate],
                    }

        states = new_states

        if len(states) > MAX_OPTIMIZER_STATES:
            # Ön eleme: item fiyatı + başlangıca en yakın durak için hafif alt sınır.
            def rough_score(state):
                choices = state["choices"]
                distances = [
                    c["distance_from_start"]
                    for c in choices
                    if c["distance_from_start"] is not None
                ]
                lower_travel = min(distances) if distances else 0.0
                return state["item_total"] + distance_weight * lower_travel

            best_states = sorted(
                states.items(),
                key=lambda pair: rough_score(pair[1]),
            )[:MAX_OPTIMIZER_STATES]

            states = dict(best_states)

    best = None

    for state in states.values():
        choices = state["choices"]
        route_distance, route = shortest_open_route(start, choices)

        if route_distance is None:
            travel_component = route_penalty_without_coords(choices)
            score = state["item_total"] + distance_weight * travel_component
        else:
            score = state["item_total"] + distance_weight * route_distance

        candidate_solution = {
            "item_total": state["item_total"],
            "route_distance": route_distance,
            "route": route,
            "score": score,
            "choices": choices,
        }

        if best is None or candidate_solution["score"] < best["score"]:
            best = candidate_solution

    return best


def choose_shopping_solution(item_candidates, start, mode, distance_weight=2.0):
    """
    Aynı aday havuzundan farklı hedeflerle çözüm üretir.

    mode:
      - cheapest: yalnız item toplamını minimize eder; eşitlikte rota kısalır.
      - nearest: HER ITEM için başlangıca en yakın marketi seçer; eşitlikte
        fiyat düşer. Sonrasında sadece seçilmiş marketler için rota oluşturulur.
      - balanced: önce Pareto-dominant olmayan planları tutar, sonra fiyat,
        rota mesafesi ve item bazlı başlangıç-region fiyat avantajını dengeler.

    Balanced modda sabit "mesafe birimi = X Hex" dönüşümü kullanılmaz. Böylece
    büyük mesafe değerleri fiyat farkını ezmez. Ayrıca başka bir plan hem daha
    ucuz hem de daha kısa/eşit rotalıysa o plan dengeli adaylardan elenir.
    Starting point region'ındaki fiyat global minimumun %10 içindeyse güçlü, %25
    içindeyse hafif yerel-region tercihi uygulanır.

    Distance hesabının kendisine dokunulmaz; mevcut shortest_open_route /
    straight_distance fonksiyonları aynen kullanılır.
    """

    # "Nearest" kullanıcı açısından item bazında davranmalı. Önceki sürüm
    # toplam rota mesafesini minimize ettiği için, iki item aynı uzak markette
    # bulunuyorsa tek durak uğruna başlangıç region'ındaki çok daha yakın bir
    # satışı atlayabiliyordu. Burada her shopping-list satırı için doğrudan
    # başlangıca en yakın claim seçilir; fiyat yalnızca eşitlik bozucudur.
    if mode == "nearest":
        choices = []
        for candidates in item_candidates:
            best_candidate = min(
                candidates,
                key=lambda c: (
                    float("inf")
                    if c.get("distance_from_start") is None
                    else c["distance_from_start"],
                    c["total_cost"],
                ),
            )
            choices.append(best_candidate)

        item_total = sum(c["total_cost"] for c in choices)
        route_distance, route = shortest_open_route(start, choices)
        return {
            "item_total": item_total,
            "route_distance": route_distance,
            "route": route,
            "choices": choices,
            "score": sum(
                c["distance_from_start"]
                if c.get("distance_from_start") is not None
                else 10**12
                for c in choices
            ),
            "mode": mode,
        }

    states = {
        frozenset(): {
            "item_total": 0.0,
            "choices": [],
        }
    }

    for candidates in item_candidates:
        new_states = {}
        for state_locations, state in states.items():
            for candidate in candidates:
                key = location_key(candidate)
                new_locations = frozenset(set(state_locations) | {key})
                new_total = state["item_total"] + candidate["total_cost"]
                old = new_states.get(new_locations)
                if old is None or new_total < old["item_total"]:
                    new_states[new_locations] = {
                        "item_total": new_total,
                        "choices": state["choices"] + [candidate],
                    }
        states = new_states

        if len(states) > MAX_OPTIMIZER_STATES:
            # Ön elemede çalışan mantığı koru. Balanced mod için kaba anahtar
            # sadece state patlamasını önlemek içindir; nihai seçim aşağıda
            # gerçek rota + Pareto/normalize hesabıyla yapılır.
            def rough_key(pair):
                state = pair[1]
                choices = state["choices"]
                distances = [
                    c["distance_from_start"] for c in choices
                    if c.get("distance_from_start") is not None
                ]
                nearest = min(distances) if distances else 0.0
                if mode == "nearest":
                    return (nearest, state["item_total"])
                if mode == "cheapest":
                    return (state["item_total"], nearest)
                return (state["item_total"], nearest)

            states = dict(sorted(states.items(), key=rough_key)[:MAX_OPTIMIZER_STATES])

    evaluated = []
    for state in states.values():
        choices = state["choices"]
        route_distance, route = shortest_open_route(start, choices)
        if route_distance is None:
            travel_component = route_penalty_without_coords(choices)
        else:
            travel_component = route_distance

        evaluated.append({
            "item_total": state["item_total"],
            "route_distance": route_distance,
            "travel_component": travel_component,
            "route": route,
            "choices": choices,
        })

    if not evaluated:
        return None

    if mode == "cheapest":
        best = min(
            evaluated,
            key=lambda s: (s["item_total"], s["travel_component"]),
        )
        score = best["item_total"]

    elif mode == "nearest":
        best = min(
            evaluated,
            key=lambda s: (s["travel_component"], s["item_total"]),
        )
        score = best["travel_component"]

    else:
        # Her item için başlangıç region'ındaki en iyi fiyatı global en iyi
        # fiyatla kıyasla. Region içi fiyat zaten çok iyiyse dengeli modda
        # o item'ı gereksiz yere başka region'dan almaya ceza verilir.
        #
        # 0-10% fark: güçlü region tercihi
        # 10-25% fark: hafif region tercihi
        # 25%+ fark: region bonusu uygulanmaz
        start_region = str(start.get("region") or "").strip().casefold()
        region_preferences = []
        for candidates in item_candidates:
            global_min = min(c["total_cost"] for c in candidates)
            regional = [
                c for c in candidates
                if str(c.get("region") or "").strip().casefold() == start_region
            ]

            strength = 0.0
            if regional and global_min > 0:
                regional_min = min(c["total_cost"] for c in regional)
                ratio = regional_min / global_min
                if ratio <= 1.10:
                    strength = 1.0
                elif ratio <= 1.25:
                    strength = 0.40

            region_preferences.append(strength)

        # Pareto filtresi: başka bir plan hem daha ucuz (veya eşit) hem de
        # daha kısa (veya eşit) ise, pahalı/uzak plan dengeli sayılamaz.
        pareto = []
        for candidate in evaluated:
            dominated = False
            for other in evaluated:
                if other is candidate:
                    continue
                no_worse_cost = other["item_total"] <= candidate["item_total"]
                no_worse_travel = other["travel_component"] <= candidate["travel_component"]
                strictly_better = (
                    other["item_total"] < candidate["item_total"]
                    or other["travel_component"] < candidate["travel_component"]
                )
                if no_worse_cost and no_worse_travel and strictly_better:
                    dominated = True
                    break
            if not dominated:
                pareto.append(candidate)

        if not pareto:
            pareto = evaluated

        min_cost = min(s["item_total"] for s in pareto)
        max_cost = max(s["item_total"] for s in pareto)
        min_travel = min(s["travel_component"] for s in pareto)
        max_travel = max(s["travel_component"] for s in pareto)

        cost_span = max_cost - min_cost
        travel_span = max_travel - min_travel

        # Balanced plan: fiyat ana etken, rota ikinci etken. Buna ek olarak,
        # bir item başlangıç region'ında global en iyi fiyata zaten çok yakınsa
        # onu başka region'dan alma davranışına item bazlı bir ceza uygulanır.
        # Böylece örneğin Jar of Dirt bulunduğun region'da 200 Hex iken aynı
        # item için uzak/pahalı bir markete gitmek dengeli sayılmaz.
        COST_WEIGHT = 0.50
        TRAVEL_WEIGHT = 0.30
        REGION_WEIGHT = 0.20

        def balanced_key(s):
            cost_norm = 0.0 if cost_span <= 0 else (
                (s["item_total"] - min_cost) / cost_span
            )
            travel_norm = 0.0 if travel_span <= 0 else (
                (s["travel_component"] - min_travel) / travel_span
            )

            region_penalty_total = 0.0
            region_penalty_weight = 0.0
            for idx, choice in enumerate(s["choices"]):
                strength = region_preferences[idx] if idx < len(region_preferences) else 0.0
                if strength <= 0:
                    continue
                region_penalty_weight += strength
                choice_region = str(choice.get("region") or "").strip().casefold()
                if choice_region != start_region:
                    region_penalty_total += strength

            region_penalty = (
                0.0
                if region_penalty_weight <= 0
                else region_penalty_total / region_penalty_weight
            )

            balanced_score = (
                COST_WEIGHT * cost_norm
                + TRAVEL_WEIGHT * travel_norm
                + REGION_WEIGHT * region_penalty
            )
            return (
                balanced_score,
                s["item_total"],
                s["travel_component"],
            )

        best = min(pareto, key=balanced_key)
        score = balanced_key(best)[0]

    result = dict(best)
    result.pop("travel_component", None)
    result["score"] = score
    result["mode"] = mode
    return result


# ---------------------------------------------------------------------------
# Autocomplete ComboBox
# ---------------------------------------------------------------------------

class AutoCompleteCombobox(ttk.Combobox):
    """
    Gerçek zamanlı autocomplete:
    - Kullanıcı yazmaya devam edebilir.
    - Öneri dropdown'u otomatik açık kalır.
    - Öneriler güncellenirken yazılan metin ve cursor korunur.

    ttk.Combobox'ın native dropdown'u Windows'ta açıldığında klavye odağını
    popup listeye taşıdığı için burada ayrı bir Toplevel öneri penceresi
    kullanılıyor. Görünüş olarak dropdown gibi davranır fakat Entry odağı
    kaybolmaz.
    """
    def __init__(self, master=None, **kwargs):
        self._lookup_func = kwargs.pop("lookup_func", autocomplete_names)
        self._min_chars = int(kwargs.pop("min_chars", 2))
        self._show_existing_when_empty = bool(
            kwargs.pop("show_existing_when_empty", False)
        )

        kwargs.setdefault("state", "normal")
        super().__init__(master, **kwargs)

        self._after_id = None
        self._generation = 0
        self._popup = None
        self._listbox = None
        self._scrollbar = None
        self._suggestions = []

        self.bind("<KeyRelease>", self._on_key_release, add="+")
        self.bind("<Down>", self._focus_suggestions, add="+")
        self.bind("<Escape>", self._hide_popup, add="+")
        self.bind("<FocusOut>", self._on_focus_out, add="+")
        self.bind("<Configure>", lambda _e: self._reposition_popup(), add="+")
        self.bind("<Button-1>", self._on_mouse_click, add="+")

    def _on_mouse_click(self, event):
        # ttk.Combobox identify() tells us when the arrow itself was clicked.
        # Clicking the arrow a second time closes the custom popup.
        try:
            element = self.identify(event.x, event.y)
        except tk.TclError:
            element = ""

        if "arrow" in str(element).lower():
            if (
                self._popup is not None
                and self._popup.winfo_exists()
                and self._popup.winfo_viewable()
            ):
                self._hide_popup()
                return "break"

            if self._suggestions:
                self._show_popup(self._suggestions)
            else:
                current = self.get().strip()
                if len(current) >= self._min_chars:
                    self._start_lookup()
            return "break"

        self.after(1, self._maybe_show_existing)

    def _on_key_release(self, event):
        # Navigasyon tuşlarında yeni API araması başlatma.
        if event.keysym in {
            "Up", "Down", "Left", "Right",
            "Return", "Escape", "Tab",
            "Home", "End", "Prior", "Next",
        }:
            return

        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass

        text = self.get().strip()

        if len(text) < self._min_chars:
            if not self._show_existing_when_empty:
                self._suggestions = []
            self._hide_popup()
            return

        self._after_id = self.after(250, self._start_lookup)

    def _start_lookup(self):
        self._after_id = None
        text = self.get().strip()

        if len(text) < self._min_chars:
            self._hide_popup()
            return

        self._generation += 1
        generation = self._generation

        threading.Thread(
            target=self._lookup_worker,
            args=(text, generation),
            daemon=True,
        ).start()

    def _lookup_worker(self, text, generation):
        try:
            names = self._lookup_func(text)
        except Exception:
            names = []

        self.after(
            0,
            lambda: self._apply_suggestions(text, generation, names)
        )

    def _apply_suggestions(self, requested_text, generation, names):
        if generation != self._generation:
            return

        # Kullanıcı bu sırada başka karakterler yazdıysa eski cevabı gösterme.
        if self.get().strip() != requested_text:
            return

        self._suggestions = list(names)
        try:
            self.configure(values=self._suggestions)
        except tk.TclError:
            pass

        if not names:
            self._hide_popup()
            return

        self._show_popup(names)

        # Kritik nokta: focus tekrar yazı alanında kalıyor.
        self.focus_set()
        try:
            self.icursor(tk.END)
        except tk.TclError:
            pass

    def _create_popup(self):
        if self._popup and self._popup.winfo_exists():
            return

        self._popup = tk.Toplevel(self)
        self._popup.withdraw()
        self._popup.overrideredirect(True)
        self._popup.attributes("-topmost", True)

        frame = ttk.Frame(self._popup, relief="solid", borderwidth=1)
        frame.pack(fill="both", expand=True)

        self._listbox = tk.Listbox(
            frame,
            activestyle="dotbox",
            exportselection=False,
            height=8,
            borderwidth=0,
            highlightthickness=0,
            bg="#3a3a3a",
            fg="#f0f0f0",
            selectbackground="#555555",
            selectforeground="#f0f0f0",
        )
        self._scrollbar = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=self._listbox.yview,
        )
        self._listbox.configure(yscrollcommand=self._scrollbar.set)

        self._listbox.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")

        self._listbox.bind("<ButtonRelease-1>", self._choose_mouse)
        self._listbox.bind("<Return>", self._choose_keyboard)
        self._listbox.bind("<Escape>", self._return_to_entry)
        self._listbox.bind("<Up>", self._list_up)
        self._listbox.bind("<Down>", self._list_down)

    def _show_popup(self, names):
        self._create_popup()

        self._listbox.delete(0, tk.END)
        for name in names:
            self._listbox.insert(tk.END, name)

        visible_rows = min(8, max(1, len(names)))
        self._listbox.configure(height=visible_rows)

        self._reposition_popup()
        self._popup.deiconify()
        self._popup.lift()

        # Native dropdown'un aksine burada popup açıldıktan sonra da
        # klavye odağı Entry'de tutulur.
        self.focus_set()

    def _reposition_popup(self):
        if not self._popup or not self._popup.winfo_exists():
            return

        try:
            # Popup ilk kez açılırken hâlâ withdrawn durumda olabilir.
            # Bu nedenle winfo_viewable() kontrolü yapmıyoruz; aksi halde
            # ilk açılışta geometry ayarlanmadan ekranın sol üstünde (0,0) belirir.
            self.update_idletasks()
            x = self.winfo_rootx()
            y = self.winfo_rooty() + self.winfo_height()
            width = max(self.winfo_width(), 320)

            # Listbox satır yüksekliği yaklaşık 22 px + çerçeve.
            rows = min(8, max(1, len(self._suggestions)))
            height = rows * 22 + 4

            self._popup.geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:
            pass

    def _maybe_show_existing(self):
        text = self.get().strip()
        if self._suggestions and (
            len(text) >= self._min_chars or self._show_existing_when_empty
        ):
            self._show_popup(self._suggestions)
            self.focus_set()

    def set_suggestions(self, values):
        self._suggestions = list(values or [])
        try:
            self.configure(values=self._suggestions)
        except tk.TclError:
            pass

    def _focus_suggestions(self, event=None):
        if not self._suggestions:
            return None

        self._show_popup(self._suggestions)
        self._listbox.focus_set()
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(0)
        self._listbox.activate(0)
        return "break"

    def _choose_mouse(self, event=None):
        selection = self._listbox.curselection()
        if not selection:
            index = self._listbox.nearest(event.y)
        else:
            index = selection[0]
        self._select_index(index)
        return "break"

    def _choose_keyboard(self, event=None):
        selection = self._listbox.curselection()
        if selection:
            self._select_index(selection[0])
        return "break"

    def _select_index(self, index):
        if index < 0 or index >= len(self._suggestions):
            return

        value = self._suggestions[index]
        self.set(value)
        self.icursor(tk.END)
        self._hide_popup()
        self.focus_set()

        # ComboboxSelected benzeri davranış isteyen kodlar için.
        self.event_generate("<<ComboboxSelected>>")

    def _return_to_entry(self, event=None):
        self._hide_popup()
        self.focus_set()
        self.icursor(tk.END)
        return "break"

    def _list_up(self, event=None):
        current = self._listbox.curselection()
        idx = current[0] if current else 0
        idx = max(0, idx - 1)
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(idx)
        self._listbox.activate(idx)
        self._listbox.see(idx)
        return "break"

    def _list_down(self, event=None):
        current = self._listbox.curselection()
        idx = current[0] if current else -1
        idx = min(len(self._suggestions) - 1, idx + 1)
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(idx)
        self._listbox.activate(idx)
        self._listbox.see(idx)
        return "break"

    def _on_focus_out(self, event=None):
        # Popup'a tıklanırken hemen kapanmaması için küçük gecikme.
        self.after(120, self._hide_if_focus_elsewhere)

    def _widget_is_inside_popup(self, widget):
        if widget is None:
            return False
        if self._popup is None or not self._popup.winfo_exists():
            return False

        try:
            widget_path = str(widget)
            popup_path = str(self._popup)
            return (
                widget is self._popup
                or widget_path == popup_path
                or widget_path.startswith(popup_path + ".")
            )
        except Exception:
            return False

    def _hide_if_focus_elsewhere(self):
        try:
            focused = self.focus_get()
        except Exception:
            focused = None

        if focused is self:
            return

        # The listbox, its frame and especially the scrollbar all belong to
        # the same dropdown. Dragging the scrollbar must not close the popup.
        if self._widget_is_inside_popup(focused):
            return

        self._hide_popup()

    def _hide_popup(self, event=None):
        if self._popup and self._popup.winfo_exists():
            self._popup.withdraw()
        return None


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class BitJitaMarketAssistant(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("BitJita Market Assistant")
        self.geometry("1260x820")
        self.minsize(1000, 650)

        self.search_results = []
        self.search_default_results = []
        self.items_rows = []
        self.items_loaded = False
        self.player_entity_id, self.player_name = _load_cached_player()
        self.shopping_rows = []
        self.shopping_solution = None
        self.buy_order_plan_results = []

        self._apply_dark_theme()
        self._build_ui()
        self.after(0, self._install_dropdown_behavior)

    def _install_dropdown_behavior(self):
        # Native ttk.Comboboxes: clicking the arrow while already open closes
        # the list. Clicking elsewhere closes all open dropdowns.
        self._install_native_combobox_bindings_recursive(self)

        # Toplevel binding runs for ordinary blank-area clicks.
        self.bind("<Button-1>", self._close_dropdowns_from_global_click, add="+")

    def _install_native_combobox_bindings_recursive(self, widget):
        try:
            children = widget.winfo_children()
        except tk.TclError:
            return

        for child in children:
            if isinstance(child, ttk.Combobox) and not isinstance(
                child, AutoCompleteCombobox
            ):
                child.bind(
                    "<Button-1>",
                    lambda e, combo=child: self._native_combobox_arrow_toggle(
                        combo, e
                    ),
                    add="+",
                )
            self._install_native_combobox_bindings_recursive(child)

    def _native_combobox_arrow_toggle(self, combo, event):
        try:
            element = combo.identify(event.x, event.y)
        except tk.TclError:
            return None

        if "arrow" not in str(element).lower():
            return None

        try:
            popdown = self.tk.call(
                "ttk::combobox::PopdownWindow",
                str(combo),
            )
            is_mapped = int(self.tk.call("winfo", "ismapped", popdown))
        except (tk.TclError, ValueError):
            is_mapped = 0

        if is_mapped:
            try:
                self.tk.call("ttk::combobox::Unpost", str(combo))
            except tk.TclError:
                pass
            return "break"

        return None

    def _click_is_inside_custom_dropdown(self, clicked):
        if clicked is None:
            return False

        for combo in self._iter_comboboxes_recursive(self):
            if isinstance(combo, AutoCompleteCombobox):
                if combo._widget_is_inside_popup(clicked):
                    return True

        return False

    def _click_is_inside_native_dropdown(self, clicked):
        if clicked is None:
            return False

        clicked_path = str(clicked)

        for combo in self._iter_comboboxes_recursive(self):
            if (
                isinstance(combo, ttk.Combobox)
                and not isinstance(combo, AutoCompleteCombobox)
            ):
                try:
                    popdown = str(
                        self.tk.call(
                            "ttk::combobox::PopdownWindow",
                            str(combo),
                        )
                    )
                except tk.TclError:
                    continue

                if (
                    clicked_path == popdown
                    or clicked_path.startswith(popdown + ".")
                ):
                    return True

        return False

    def _iter_comboboxes_recursive(self, widget):
        try:
            children = widget.winfo_children()
        except tk.TclError:
            return []

        result = []
        for child in children:
            if isinstance(child, ttk.Combobox):
                result.append(child)
            result.extend(self._iter_comboboxes_recursive(child))
        return result

    def _close_dropdowns_from_global_click(self, event):
        clicked = getattr(event, "widget", None)

        # Clicking or dragging inside a dropdown (including its scrollbar)
        # is interaction with the dropdown, not an outside click.
        if self._click_is_inside_custom_dropdown(clicked):
            return
        if self._click_is_inside_native_dropdown(clicked):
            return

        # Custom autocomplete popups.
        self._close_custom_dropdowns_recursive(self, except_widget=clicked)

        # Native ttk combobox popdowns. Do not instantly close the combobox
        # that was just clicked; its normal class binding may be opening it.
        self._close_native_dropdowns_recursive(self, except_widget=clicked)

    def _close_custom_dropdowns_recursive(self, widget, except_widget=None):
        try:
            children = widget.winfo_children()
        except tk.TclError:
            return

        for child in children:
            if isinstance(child, AutoCompleteCombobox):
                if child is not except_widget:
                    child._hide_popup()
            self._close_custom_dropdowns_recursive(
                child,
                except_widget=except_widget,
            )

    def _close_native_dropdowns_recursive(self, widget, except_widget=None):
        try:
            children = widget.winfo_children()
        except tk.TclError:
            return

        for child in children:
            if (
                isinstance(child, ttk.Combobox)
                and not isinstance(child, AutoCompleteCombobox)
                and child is not except_widget
            ):
                try:
                    self.tk.call("ttk::combobox::Unpost", str(child))
                except tk.TclError:
                    pass

            self._close_native_dropdowns_recursive(
                child,
                except_widget=except_widget,
            )

    # ---------------------------- tema ----------------------------

    def _apply_dark_theme(self):
        """Koyu gri ttk teması."""
        self.configure(bg="#2b2b2b")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = "#2b2b2b"
        panel = "#333333"
        field = "#3a3a3a"
        border = "#4a4a4a"
        fg = "#f0f0f0"
        muted = "#c8c8c8"
        select = "#555555"

        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TLabelframe", background=bg, foreground=fg)
        style.configure("TLabelframe.Label", background=bg, foreground=fg)

        style.configure("TButton", background=panel, foreground=fg, bordercolor=border)
        style.map("TButton", background=[("active", "#444444"), ("pressed", "#222222")])

        style.configure(
            "SetToggle.TButton",
            background=panel,
            foreground=fg,
            bordercolor=border,
            font=("Segoe UI", 8),
            padding=(3, 1),
        )
        style.map(
            "SetToggle.TButton",
            background=[("active", "#444444"), ("pressed", "#222222")],
        )

        style.configure("TEntry", fieldbackground=field, foreground=fg, insertcolor=fg, bordercolor=border)
        style.configure("TCombobox", fieldbackground=field, foreground=fg, background=panel, arrowcolor=fg, bordercolor=border, insertcolor="#ffffff")
        style.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", fg)])

        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.map("TRadiobutton", background=[("active", bg)])
        style.configure("TCheckbutton", background=bg, foreground=fg)

        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", background=panel, foreground=muted, padding=(12, 7))
        style.map("TNotebook.Tab", background=[("selected", "#454545")], foreground=[("selected", fg)])

        style.configure("Treeview", background=field, fieldbackground=field, foreground=fg, bordercolor=border, rowheight=24)
        style.map("Treeview", background=[("selected", select)], foreground=[("selected", fg)])
        style.configure("Treeview.Heading", background=panel, foreground=fg, relief="flat")
        style.map("Treeview.Heading", background=[("active", "#444444")])

        style.configure("Vertical.TScrollbar", background=panel, troughcolor=bg, bordercolor=bg, arrowcolor=fg)
        style.configure("Horizontal.TScrollbar", background=panel, troughcolor=bg, bordercolor=bg, arrowcolor=fg)

        # ttk Spinbox desteği mevcutsa koyu alan kullan.
        style.configure("TSpinbox", fieldbackground=field, foreground=fg, insertcolor=fg, arrowsize=14)

        # Combobox açılır listesinin native Tk renkleri.
        self.option_add("*TCombobox*Listbox.background", field)
        self.option_add("*TCombobox*Listbox.foreground", fg)
        self.option_add("*TCombobox*Listbox.selectBackground", select)
        self.option_add("*TCombobox*Listbox.selectForeground", fg)

    # ---------------------------- genel UI ----------------------------

    def _build_ui(self):
        notebook = ttk.Notebook(self)
        self.main_notebook = notebook
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.search_tab = ttk.Frame(notebook, padding=12)
        self.shopping_tab = ttk.Frame(notebook, padding=(12, 5, 12, 12))
        self.items_tab = ttk.Frame(notebook, padding=12)
        self.settings_tab = ttk.Frame(notebook, padding=12)
        self.about_tab = ttk.Frame(notebook, padding=28)

        notebook.add(self.shopping_tab, text="Shopping List")
        notebook.add(self.search_tab, text="Item Search")
        notebook.add(self.items_tab, text="Items")
        notebook.add(self.settings_tab, text="Location / Optimization")
        notebook.add(self.about_tab, text="About")

        self._build_settings_tab()
        self._build_search_tab()
        self._build_items_tab()
        self._build_shopping_tab()
        self._build_about_tab()

        # Shift+Tab is a dedicated quick switch between the two primary tabs.
        # Bind both common Tk event names so it works consistently on Windows
        # and other platforms.
        self.bind_all("<Shift-Tab>", self._toggle_primary_tabs, add="+")
        self.bind_all("<ISO_Left_Tab>", self._toggle_primary_tabs, add="+")

    def _toggle_primary_tabs(self, _event=None):
        current = self.main_notebook.select()

        if current == str(self.shopping_tab):
            self.main_notebook.select(self.search_tab)
        else:
            # From Item Search (or any secondary tab), return to Shopping List.
            self.main_notebook.select(self.shopping_tab)

        return "break"

    def _build_about_tab(self):
        profile_url = "https://bitjita.com/players/1369094290262440373/overview"

        content = ttk.Frame(self.about_tab)
        content.pack(anchor="nw", fill="x", padx=24, pady=18)

        ttk.Label(
            content,
            text="About BitJita Market Assistant",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w", pady=(0, 22))

        intro = ttk.Frame(content)
        intro.pack(anchor="w", fill="x")

        ttk.Label(
            intro,
            text="Hi, I’m ",
            font=("Segoe UI", 11),
        ).pack(side="left")

        aron_link = tk.Label(
            intro,
            text="Aron",
            font=("Segoe UI", 11, "underline"),
            fg="#69aef8",
            bg="#2b2b2b",
            cursor="hand2",
        )
        aron_link.pack(side="left")
        aron_link.bind("<Button-1>", lambda _event: webbrowser.open(profile_url))

        ttk.Label(
            intro,
            text=".",
            font=("Segoe UI", 11),
        ).pack(side="left")

        ttk.Label(
            content,
            text=(
                "These days, I’m usually hanging out at Ba Sing Se in Zephyra (R19). "
                "If you happen to stop by, I might buy you a Deluxe Fish :)"
            ),
            font=("Segoe UI", 11),
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(10, 18))

        ttk.Label(
            content,
            text=(
                "I developed this application with the help of AI — to be fair, "
                "AI did most of the heavy lifting."
            ),
            font=("Segoe UI", 11),
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(0, 18))

        ttk.Label(
            content,
            text=(
                "If you have any feedback, suggestions, or bug reports about the app, "
                "feel free to reach out to me on Discord."
            ),
            font=("Segoe UI", 11),
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(0, 16))

        discord_row = ttk.Frame(content)
        discord_row.pack(anchor="w", pady=(2, 0))

        # Embedded Discord/Clyde icon; no external file is required at runtime.
        self.discord_icon_image = tk.PhotoImage(
            data=DISCORD_ICON_PNG_BASE64
        )
        ttk.Label(
            discord_row,
            image=self.discord_icon_image,
        ).pack(side="left", padx=(0, 8))

        self.discord_username_var = tk.StringVar(value="kamarasa_")
        self.discord_username_entry = tk.Entry(
            discord_row,
            textvariable=self.discord_username_var,
            width=12,
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            bd=0,
            bg="#2b2b2b",
            fg="#f0f0f0",
            readonlybackground="#2b2b2b",
            selectbackground="#5865F2",
            selectforeground="#ffffff",
            exportselection=False,
        )
        self.discord_username_entry.pack(side="left")
        self.discord_username_entry.configure(state="readonly")
        self.discord_username_entry.bind(
            "<Control-a>",
            lambda _e: (
                self.discord_username_entry.selection_range(0, tk.END),
                "break",
            )[-1],
        )

        self.discord_copy_menu = tk.Menu(
            self.discord_username_entry,
            tearoff=False,
        )
        self.discord_copy_menu.add_command(
            label="Copy",
            command=self._copy_discord_username,
        )
        self.discord_username_entry.bind(
            "<Button-3>",
            self._show_discord_copy_menu,
        )

    def _copy_discord_username(self):
        value = self.discord_username_var.get()
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update_idletasks()

    def _show_discord_copy_menu(self, event):
        try:
            self.discord_copy_menu.tk_popup(
                event.x_root,
                event.y_root,
            )
        finally:
            self.discord_copy_menu.grab_release()

    # ---------------------------- Items ----------------------------

    def _build_items_tab(self):
        header = ttk.Frame(self.items_tab)
        header.pack(fill="x", pady=(0, 10))

        ttk.Label(
            header,
            text="My Items",
            font=("Segoe UI", 15, "bold"),
        ).pack(side="left")

        ttk.Button(
            header,
            text="Refresh",
            command=self._refresh_items_tab,
        ).pack(side="right")

        player_frame = ttk.Frame(self.items_tab)
        player_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(player_frame, text="Player:").pack(side="left")

        self.items_player_var = tk.StringVar(
            value=self.player_name or ""
        )
        self.items_player_entry = ttk.Entry(
            player_frame,
            textvariable=self.items_player_var,
            width=28,
        )
        self.items_player_entry.pack(side="left", padx=(6, 8))
        self.items_player_entry.bind(
            "<Return>",
            lambda _event: self._set_items_player(),
        )

        self.items_set_player_button = ttk.Button(
            player_frame,
            text="Set Player",
            command=self._set_items_player,
        )
        self.items_set_player_button.pack(side="left")

        self.items_current_player_var = tk.StringVar()
        ttk.Label(
            player_frame,
            textvariable=self.items_current_player_var,
        ).pack(side="left", padx=(12, 0))

        if self.player_entity_id and self.player_name:
            self.items_current_player_var.set(
                f"Using: {self.player_name}"
            )
        else:
            self.items_current_player_var.set(
                "Choose your BitJita player name."
            )

        filters = ttk.Frame(self.items_tab)
        filters.pack(fill="x", pady=(0, 10))

        ttk.Label(filters, text="Search:").pack(side="left")
        self.items_search_var = tk.StringVar()
        items_search_entry = ttk.Entry(
            filters,
            textvariable=self.items_search_var,
            width=34,
        )
        items_search_entry.pack(side="left", padx=(6, 14))
        self.items_search_var.trace_add(
            "write",
            lambda *_args: self._render_items_tree(),
        )

        ttk.Label(filters, text="Storage Type:").pack(side="left")
        self.items_location_var = tk.StringVar(value="All")
        location_combo = ttk.Combobox(
            filters,
            textvariable=self.items_location_var,
            values=("All", "Inventory", "Storage", "Bank"),
            state="readonly",
            width=12,
        )
        location_combo.pack(side="left", padx=(6, 14))
        location_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._render_items_tree(),
        )

        ttk.Label(filters, text="Settlement / Region:").pack(side="left")
        self.items_geo_var = tk.StringVar(value="All")
        self.items_geo_combo = ttk.Combobox(
            filters,
            textvariable=self.items_geo_var,
            values=("All",),
            state="readonly",
            width=24,
        )
        self.items_geo_combo.pack(side="left", padx=(6, 0))
        self.items_geo_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._render_items_tree(),
        )

        self.items_status_var = tk.StringVar(value="Ready." if self.player_entity_id else "Set a player to load items.")
        ttk.Label(
            self.items_tab,
            textvariable=self.items_status_var,
        ).pack(fill="x", pady=(0, 7))

        table_frame = ttk.Frame(self.items_tab)
        table_frame.pack(fill="both", expand=True)

        columns = (
            "item", "quantity", "location", "container",
            "claim", "region", "tier", "rarity", "type", "id"
        )
        self.items_tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
        )

        defs = [
            ("item", "Item", 230),
            ("quantity", "Quantity", 80),
            ("location", "Location", 90),
            ("container", "Container", 170),
            ("claim", "Claim", 170),
            ("region", "Region", 110),
            ("tier", "Tier", 55),
            ("rarity", "Rarity", 95),
            ("type", "Type", 75),
            ("id", "Item ID", 110),
        ]

        for col, title, width in defs:
            self.items_tree.heading(col, text=title)
            self.items_tree.column(
                col,
                width=width,
                anchor="w" if col == "item" else "center",
            )

        ybar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.items_tree.yview,
        )
        xbar = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.items_tree.xview,
        )
        self.items_tree.configure(
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
        )

        self.items_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        # Load automatically only when a player has already been selected.
        if self.player_entity_id:
            self.after(50, self._refresh_items_tab)

    @staticmethod
    def _inventory_source_text(data):
        if not isinstance(data, dict):
            return ""

        keys = (
            "inventoryType", "inventory_type", "type", "name",
            "inventoryName", "inventory_name", "pocketName", "pocket_name",
            "buildingName", "buildingNickname", "containerName",
            "locationName", "label",
        )
        parts = []
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                parts.append(str(value))
        return " ".join(parts).strip()

    @classmethod
    def _classify_inventory_location(cls, data, inherited_text=""):
        text = " ".join(
            part for part in (
                inherited_text,
                cls._inventory_source_text(data),
            )
            if part
        ).casefold()

        if any(word in text for word in ("bank", "vault")):
            return "Bank"
        if any(
            word in text
            for word in (
                "storage", "chest", "warehouse", "house",
                "housing", "building", "container",
            )
        ):
            return "Storage"
        return "Inventory"

    @staticmethod
    def _inventory_container_name(data, fallback):
        if not isinstance(data, dict):
            return fallback

        for key in (
            "buildingNickname", "buildingName", "inventoryName",
            "inventory_name", "pocketName", "pocket_name",
            "containerName", "name", "label", "inventoryType", "type",
        ):
            value = data.get(key)
            if value not in (None, ""):
                return str(value)
        return fallback

    def _set_items_player(self):
        username = self.items_player_var.get().strip()

        if len(username) < 2:
            messagebox.showwarning(
                "Player name required",
                "Enter at least two characters of the BitJita player name.",
            )
            return

        self.items_set_player_button.config(state="disabled")
        self.items_status_var.set(f"Searching for player {username}...")

        threading.Thread(
            target=self._resolve_items_player_worker,
            args=(username,),
            daemon=True,
        ).start()

    def _resolve_items_player_worker(self, username):
        try:
            data = api_get("/players", params={"q": username})
            players = []

            if isinstance(data, dict):
                players = data.get("players") or data.get("data") or []
            elif isinstance(data, list):
                players = data

            if isinstance(players, dict):
                players = list(players.values())

            players = [
                player for player in players
                if isinstance(player, dict)
            ]

            def player_name(player):
                return str(
                    first_value(
                        player,
                        "username", "name", "playerName", "displayName",
                    )
                    or ""
                ).strip()

            def player_id(player):
                value = first_value(
                    player,
                    "entityId", "id", "playerEntityId", "playerId",
                )
                return (
                    str(value).strip()
                    if value not in (None, "")
                    else None
                )

            exact = [
                player for player in players
                if player_name(player).casefold() == username.casefold()
                and player_id(player)
            ]

            if len(exact) == 1:
                selected = exact[0]
            else:
                usable = [
                    player for player in players
                    if player_name(player) and player_id(player)
                ]

                if len(usable) == 1:
                    selected = usable[0]
                elif not usable:
                    self.after(
                        0,
                        lambda: self._player_resolution_failed(
                            f'No BitJita player found for "{username}".'
                        ),
                    )
                    return
                else:
                    suggestions = ", ".join(
                        player_name(player)
                        for player in usable[:8]
                    )
                    self.after(
                        0,
                        lambda s=suggestions: self._player_resolution_failed(
                            "Multiple players matched. Enter the exact username."
                            + (f" Matches: {s}" if s else "")
                        ),
                    )
                    return

            resolved_name = player_name(selected)
            resolved_id = player_id(selected)

            self.after(
                0,
                lambda n=resolved_name, pid=resolved_id:
                self._player_resolved(n, pid),
            )

        except Exception as exc:
            self.after(
                0,
                lambda msg=str(exc): self._player_resolution_failed(msg),
            )

    def _player_resolution_failed(self, message):
        self.items_set_player_button.config(state="normal")
        self.items_status_var.set("Player lookup failed.")
        messagebox.showerror("Player lookup", message)

    def _player_resolved(self, player_name, player_id):
        self.player_name = player_name
        self.player_entity_id = player_id

        self.items_player_var.set(player_name)
        self.items_current_player_var.set(f"Using: {player_name}")
        self.items_set_player_button.config(state="normal")

        _save_cached_player(player_id, player_name)

        self.items_rows = []
        self.items_loaded = False
        self._render_items_tree()
        self._refresh_items_tab()

    @staticmethod
    def _metadata_lookup(raw_list, kind):
        result = {}

        def add(raw):
            if not isinstance(raw, dict):
                return

            item_id = first_value(
                raw,
                "id", "itemId", "item_id",
                "cargoId", "cargo_id",
                "itemDescriptionId", "cargoDescriptionId",
            )
            if item_id in (None, ""):
                return

            name = first_value(
                raw,
                "name", "itemName", "cargoName", "displayName",
            )
            if not name:
                return

            result[str(item_id)] = {
                "id": item_id,
                "name": str(name),
                "tier": to_number(first_value(raw, "tier", "itemTier")),
                "rarity": (
                    first_value(
                        raw,
                        "rarityStr", "itemRarityStr",
                        "rarityName", "rarity",
                    )
                    or ""
                ),
                "type": kind,
            }

        if isinstance(raw_list, dict):
            # Some BitJita payloads expose catalog entries as id -> object.
            for key, value in raw_list.items():
                if isinstance(value, dict):
                    if not any(
                        k in value
                        for k in (
                            "id", "itemId", "item_id",
                            "cargoId", "cargo_id",
                        )
                    ):
                        value = dict(value)
                        value["id"] = key
                    add(value)
        else:
            for raw in raw_list or []:
                add(raw)

        return result

    def _load_global_item_catalog(self):
        """Fallback catalog for IDs not described by inventory responses."""
        items = {}
        cargos = {}

        def fetch_catalog(path, key, kind):
            try:
                data = api_get(path)
                payload = data.get(key) if isinstance(data, dict) else data
                return self._metadata_lookup(payload, kind)
            except Exception:
                return {}

        # /items and /cargo are independent, so fetch them in parallel.
        with ThreadPoolExecutor(max_workers=2) as executor:
            item_future = executor.submit(
                fetch_catalog, "/items", "items", "Item"
            )
            cargo_future = executor.submit(
                fetch_catalog, "/cargo", "cargos", "Cargo"
            )
            items.update(item_future.result())
            cargos.update(cargo_future.result())

        return items, cargos

    @staticmethod
    def _merge_metadata(target, source):
        for key, value in (source or {}).items():
            if key not in target:
                target[key] = value

    def _extract_inventory_rows(
        self,
        payload,
        default_location="Inventory",
        default_container="Inventory",
        default_claim="",
        default_region="",
        shared_item_meta=None,
        shared_cargo_meta=None,
    ):
        if not isinstance(payload, dict):
            return []

        item_meta = {}
        cargo_meta = {}

        self._merge_metadata(
            item_meta,
            self._metadata_lookup(payload.get("items"), "Item"),
        )
        self._merge_metadata(
            cargo_meta,
            self._metadata_lookup(payload.get("cargos"), "Cargo"),
        )

        if shared_item_meta:
            self._merge_metadata(item_meta, shared_item_meta)
        if shared_cargo_meta:
            self._merge_metadata(cargo_meta, shared_cargo_meta)

        rows = []

        def resolve_meta(item_id, raw_type):
            key = str(item_id)
            raw_type = str(raw_type or "").casefold()

            if "cargo" in raw_type:
                return cargo_meta.get(key) or item_meta.get(key)
            if "item" in raw_type:
                return item_meta.get(key) or cargo_meta.get(key)

            return item_meta.get(key) or cargo_meta.get(key)

        def add_content(content, location, container, claim, region):
            if not isinstance(content, dict):
                return

            item_id = first_value(
                content,
                "item_id", "itemId",
                "cargo_id", "cargoId",
                "itemDescriptionId", "cargoDescriptionId",
            )
            quantity = to_number(
                first_value(content, "quantity", "count", "amount", "qty")
            )

            if item_id in (None, "") or quantity in (None, 0):
                return

            raw_type = first_value(
                content,
                "item_type", "itemType", "type",
            )

            meta = resolve_meta(item_id, raw_type)

            if meta is None:
                meta = {
                    "id": item_id,
                    "name": f"Unknown item {item_id}",
                    "tier": None,
                    "rarity": "",
                    "type": (
                        "Cargo"
                        if "cargo" in str(raw_type or "").casefold()
                        else "Item"
                    ),
                }

            rows.append({
                "item": meta["name"],
                "quantity": int(quantity),
                "location": location,
                "container": container,
                "claim": claim or "",
                "region": region or "",
                "tier": meta["tier"],
                "rarity": meta["rarity"],
                "type": meta["type"],
                "id": meta["id"],
            })

        def walk(
            node,
            inherited_location=default_location,
            inherited_text="",
            inherited_container=default_container,
            inherited_claim=default_claim,
            inherited_region=default_region,
        ):
            if isinstance(node, list):
                for child in node:
                    walk(
                        child,
                        inherited_location,
                        inherited_text,
                        inherited_container,
                        inherited_claim,
                        inherited_region,
                    )
                return

            if not isinstance(node, dict):
                return

            own_text = self._inventory_source_text(node)
            combined_text = " ".join(
                p for p in (inherited_text, own_text) if p
            )

            detected = self._classify_inventory_location(
                node,
                inherited_text,
            )

            # For house-detail payloads, Storage is authoritative.
            # For normal player inventory, retain detected subtypes.
            if default_location == "Storage":
                location = "Storage"
            elif default_location == "Bank":
                location = "Bank"
            else:
                location = detected
                if (
                    location == "Inventory"
                    and inherited_location in ("Bank", "Storage")
                ):
                    location = inherited_location

            container = self._inventory_container_name(
                node,
                inherited_container,
            )

            node_claim = first_value(
                node,
                "claimName", "claim_name", "claim",
                "locationClaimName",
            )
            node_region = first_value(
                node,
                "regionName", "region_name", "region",
                "locationRegionName",
            )

            claim = (
                str(node_claim).strip()
                if node_claim not in (None, "")
                else inherited_claim
            )
            region = (
                str(node_region).strip()
                if node_region not in (None, "")
                else inherited_region
            )

            if "contents" in node:
                contents = node.get("contents")
                if isinstance(contents, dict):
                    add_content(contents, location, container, claim, region)
                elif isinstance(contents, list):
                    for content in contents:
                        add_content(content, location, container, claim, region)

            if any(
                key in node
                for key in (
                    "item_id", "itemId", "cargo_id", "cargoId",
                    "itemDescriptionId", "cargoDescriptionId",
                )
            ) and any(
                key in node
                for key in ("quantity", "count", "amount", "qty")
            ):
                add_content(node, location, container, claim, region)

            for key, value in node.items():
                if key in {"contents", "items", "cargos"}:
                    continue
                if isinstance(value, (dict, list)):
                    walk(
                        value,
                        location,
                        combined_text,
                        container,
                        claim,
                        region,
                    )

        inventory_root = (
            payload.get("inventories")
            if "inventories" in payload
            else payload
        )
        walk(inventory_root)

        return rows

    def _extract_vault_rows(
        self,
        payload,
        shared_item_meta=None,
        shared_cargo_meta=None,
    ):
        if not isinstance(payload, dict):
            return []

        collectibles = payload.get("collectibles") or []
        rows = []

        vault_claim = first_value(
            payload,
            "claimName", "claim_name", "claim",
            "locationClaimName",
        ) or ""
        vault_region = first_value(
            payload,
            "regionName", "region_name", "region",
            "locationRegionName",
        ) or ""

        for raw in collectibles:
            if not isinstance(raw, dict):
                continue

            item_id = first_value(
                raw,
                "itemId", "item_id",
                "cargoId", "cargo_id",
                "id", "descriptionId",
            )
            quantity = to_number(
                first_value(raw, "quantity", "count", "amount", "qty")
            ) or 1

            if item_id in (None, ""):
                continue

            key = str(item_id)
            raw_type = str(
                first_value(raw, "itemType", "item_type", "type") or ""
            ).casefold()

            meta = None
            if "cargo" in raw_type:
                meta = (shared_cargo_meta or {}).get(key)
            elif "item" in raw_type:
                meta = (shared_item_meta or {}).get(key)

            if meta is None:
                meta = (
                    (shared_item_meta or {}).get(key)
                    or (shared_cargo_meta or {}).get(key)
                )

            if meta is None:
                direct_name = first_value(
                    raw,
                    "name", "itemName", "cargoName", "displayName",
                )
                meta = {
                    "id": item_id,
                    "name": direct_name or f"Unknown item {item_id}",
                    "tier": to_number(first_value(raw, "tier", "itemTier")),
                    "rarity": (
                        first_value(raw, "rarityStr", "rarity") or ""
                    ),
                    "type": (
                        "Cargo"
                        if "cargo" in raw_type
                        else "Item"
                    ),
                }

            rows.append({
                "item": meta["name"],
                "quantity": int(quantity),
                "location": "Bank",
                "container": "Vault",
                "claim": str(vault_claim),
                "region": str(vault_region),
                "tier": meta["tier"],
                "rarity": meta["rarity"],
                "type": meta["type"],
                "id": meta["id"],
            })

        return rows

    @staticmethod
    def _fill_missing_item_regions(rows, claim_catalog=None):
        """
        Fill missing region names from each row's claim/settlement name.

        When a claim catalogue is supplied, build a local name -> region index
        once. This avoids repeatedly calling the resolver for each settlement.
        """
        region_by_claim = {}

        if claim_catalog:
            for claim in claim_catalog:
                if not isinstance(claim, dict):
                    continue

                name = str(claim.get("name") or "").strip()
                region = str(claim.get("regionName") or "").strip()
                rid = normalize_region_id(claim.get("regionId"))

                if not name or not region:
                    continue

                display_region = (
                    f"{region} {rid}"
                    if rid
                    else region
                )
                region_by_claim.setdefault(
                    name.casefold(),
                    display_region,
                )

        unresolved = {}

        for row in rows:
            claim = str(row.get("claim") or "").strip()
            region = str(row.get("region") or "").strip()

            if not claim or region:
                continue

            key = claim.casefold()
            resolved_region = region_by_claim.get(key, "")

            if not resolved_region:
                if key not in unresolved:
                    try:
                        resolved = resolve_claim_by_name(claim, None)
                    except Exception:
                        resolved = None

                    resolved_region = ""
                    if resolved:
                        resolved_region = str(
                            resolved.get("region") or ""
                        ).strip()
                        rid = normalize_region_id(
                            resolved.get("region_id")
                        )
                        if resolved_region and rid:
                            resolved_region = (
                                f"{resolved_region} {rid}"
                            )

                    unresolved[key] = resolved_region

                resolved_region = unresolved[key]

            if resolved_region:
                row["region"] = resolved_region

        return rows

    @staticmethod
    def _combine_item_rows(rows):
        combined = {}

        for row in rows:
            key = (
                str(row["id"]),
                row["type"],
                row["location"],
                row["container"],
                row.get("claim", ""),
                row.get("region", ""),
            )
            if key not in combined:
                combined[key] = dict(row)
            else:
                combined[key]["quantity"] += row["quantity"]

        return sorted(
            combined.values(),
            key=lambda r: (
                r["item"].casefold(),
                r["location"],
                r["container"].casefold(),
            ),
        )

    def _refresh_items_tab(self):
        if not self.player_entity_id:
            self.items_status_var.set("Set a player to load items.")
            return

        self.items_status_var.set(
            f"Loading {self.player_name or 'player'} inventory, storage and bank from BitJita..."
        )
        threading.Thread(
            target=self._items_worker,
            daemon=True,
        ).start()

    def _items_worker(self):
        player_id = self.player_entity_id
        if not player_id:
            return

        try:
            rows = []

            # These requests are independent. Fetch them together instead of
            # waiting for inventory -> housing -> vault -> claim catalogue.
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_catalogs = executor.submit(
                    self._load_global_item_catalog
                )
                future_inventory = executor.submit(
                    api_get,
                    f"/players/{player_id}/inventories",
                )
                future_housing = executor.submit(
                    api_get,
                    f"/players/{player_id}/housing",
                )
                future_vault = executor.submit(
                    api_get,
                    f"/players/{player_id}/vault",
                )
                future_claims = executor.submit(get_claim_catalog)

                try:
                    global_items, global_cargos = future_catalogs.result()
                except Exception:
                    global_items, global_cargos = {}, {}

                inventory_payload = future_inventory.result()

                try:
                    houses = future_housing.result()
                except Exception:
                    houses = []

                try:
                    vault_payload = future_vault.result()
                except Exception:
                    vault_payload = {}

                try:
                    claim_catalog = future_claims.result()
                except Exception:
                    claim_catalog = []

            # Character inventory.
            inv_items = self._metadata_lookup(
                inventory_payload.get("items")
                if isinstance(inventory_payload, dict)
                else None,
                "Item",
            )
            inv_cargos = self._metadata_lookup(
                inventory_payload.get("cargos")
                if isinstance(inventory_payload, dict)
                else None,
                "Cargo",
            )
            self._merge_metadata(inv_items, global_items)
            self._merge_metadata(inv_cargos, global_cargos)

            rows.extend(
                self._extract_inventory_rows(
                    inventory_payload,
                    default_location="Inventory",
                    default_container="Inventory",
                    shared_item_meta=inv_items,
                    shared_cargo_meta=inv_cargos,
                )
            )

            # Housing / storage.
            if not isinstance(houses, list):
                houses = (
                    houses.get("housing")
                    or houses.get("houses")
                    or []
                ) if isinstance(houses, dict) else []

            house_jobs = []
            for house in houses:
                if not isinstance(house, dict):
                    continue

                house_id = first_value(
                    house,
                    "buildingEntityId", "houseId", "entityId", "id",
                )
                if house_id in (None, ""):
                    continue

                house_jobs.append((house_id, house))

            # House detail calls are often the slowest part. Run several in
            # parallel while keeping the existing API abstraction unchanged.
            house_details = []
            if house_jobs:
                worker_count = min(
                    MAX_API_WORKERS,
                    max(1, len(house_jobs)),
                )
                with ThreadPoolExecutor(
                    max_workers=worker_count
                ) as executor:
                    futures = {
                        executor.submit(
                            api_get,
                            f"/players/{player_id}/housing/{house_id}",
                        ): (house_id, house)
                        for house_id, house in house_jobs
                    }

                    for future in as_completed(futures):
                        _house_id, house = futures[future]
                        try:
                            detail = future.result()
                        except Exception:
                            continue
                        house_details.append((house, detail))

            for house, detail in house_details:
                house_name = (
                    first_value(
                        house,
                        "buildingNickname", "buildingName",
                        "claimName", "name",
                    )
                    or "Storage"
                )
                house_claim = (
                    first_value(
                        house,
                        "claimName", "claim_name", "claim",
                    )
                    or ""
                )
                house_region = (
                    first_value(
                        house,
                        "regionName", "region_name", "region",
                    )
                    or ""
                )

                if isinstance(detail, dict):
                    if not house_claim:
                        house_claim = (
                            first_value(
                                detail,
                                "claimName", "claim_name", "claim",
                            )
                            or ""
                        )
                    if not house_region:
                        house_region = (
                            first_value(
                                detail,
                                "regionName", "region_name", "region",
                            )
                            or ""
                        )

                house_items = self._metadata_lookup(
                    detail.get("items")
                    if isinstance(detail, dict)
                    else None,
                    "Item",
                )
                house_cargos = self._metadata_lookup(
                    detail.get("cargos")
                    if isinstance(detail, dict)
                    else None,
                    "Cargo",
                )
                self._merge_metadata(house_items, global_items)
                self._merge_metadata(house_cargos, global_cargos)

                rows.extend(
                    self._extract_inventory_rows(
                        detail,
                        default_location="Storage",
                        default_container=str(house_name),
                        default_claim=str(house_claim),
                        default_region=str(house_region),
                        shared_item_meta=house_items,
                        shared_cargo_meta=house_cargos,
                    )
                )

            # Bank / vault.
            rows.extend(
                self._extract_vault_rows(
                    vault_payload,
                    shared_item_meta=global_items,
                    shared_cargo_meta=global_cargos,
                )
            )

            rows = self._fill_missing_item_regions(
                rows,
                claim_catalog=claim_catalog,
            )
            rows = self._combine_item_rows(rows)

        except Exception as exc:
            self.after(
                0,
                lambda msg=str(exc): self._items_load_failed(msg),
            )
            return

        self.after(
            0,
            lambda data=rows: self._items_loaded(data),
        )

    def _items_load_failed(self, message):
        self.items_status_var.set(f"Could not load items: {message}")

    def _items_loaded(self, rows):
        self.items_rows = rows
        self.items_loaded = True
        self._refresh_items_geo_filter()
        self._render_items_tree()

    def _refresh_items_geo_filter(self):
        if not hasattr(self, "items_geo_combo"):
            return

        settlements = sorted({
            str(row.get("claim") or "").strip()
            for row in self.items_rows
            if str(row.get("claim") or "").strip()
        }, key=str.casefold)

        regions = sorted({
            str(row.get("region") or "").strip()
            for row in self.items_rows
            if str(row.get("region") or "").strip()
        }, key=str.casefold)

        values = ["All"]
        values.extend(f"Settlement: {name}" for name in settlements)
        values.extend(f"Region: {name}" for name in regions)

        self.items_geo_combo.configure(values=values)

        current = self.items_geo_var.get()
        if current not in values:
            self.items_geo_var.set("All")

    def _render_items_tree(self):
        if not hasattr(self, "items_tree"):
            return

        query = ""
        if hasattr(self, "items_search_var"):
            query = self.items_search_var.get().strip().casefold()

        location_filter = "All"
        if hasattr(self, "items_location_var"):
            location_filter = self.items_location_var.get() or "All"

        geo_filter = "All"
        if hasattr(self, "items_geo_var"):
            geo_filter = self.items_geo_var.get() or "All"

        visible = []
        for row in self.items_rows:
            if location_filter != "All" and row["location"] != location_filter:
                continue

            if geo_filter.startswith("Settlement: "):
                wanted_claim = geo_filter.split(": ", 1)[1]
                if str(row.get("claim") or "") != wanted_claim:
                    continue
            elif geo_filter.startswith("Region: "):
                wanted_region = geo_filter.split(": ", 1)[1]
                if str(row.get("region") or "") != wanted_region:
                    continue

            searchable = " ".join(
                str(row.get(key) or "")
                for key in (
                    "item", "location", "container", "claim", "region",
                    "rarity", "type", "id"
                )
            ).casefold()

            if query and query not in searchable:
                continue

            visible.append(row)

        for iid in self.items_tree.get_children():
            self.items_tree.delete(iid)

        for idx, row in enumerate(visible):
            tier = (
                "-"
                if row.get("tier") in (None, "")
                else f"T{int(row['tier'])}"
            )
            self.items_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    row["item"],
                    f"{row['quantity']:,}",
                    row["location"],
                    row["container"],
                    row.get("claim") or "-",
                    row.get("region") or "-",
                    tier,
                    row["rarity"],
                    row["type"],
                    row["id"],
                ),
            )

        if self.items_loaded:
            total_qty = sum(row["quantity"] for row in visible)
            self.items_status_var.set(
                f"{len(visible)} entries shown | {total_qty:,} total quantity"
            )

    def _build_settings_tab(self):
        ttk.Label(
            self.settings_tab,
            text="Starting Locations",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 12))

        ttk.Label(self.settings_tab, text="Use").grid(row=1, column=0, sticky="w")
        ttk.Label(self.settings_tab, text="Claim").grid(row=1, column=1, sticky="w")
        ttk.Label(self.settings_tab, text="Region").grid(row=1, column=2, sticky="w")

        cached_locations, cached_active = _load_cached_start_locations()

        self.active_start_location_var = tk.IntVar(value=cached_active)
        self.start_location_vars = []
        self.start_location_label_vars = []
        self.start_claim_combos = []
        self.start_region_combos = []

        defaults = cached_locations or [
            {
                "claim": DEFAULT_START["claim"],
                "region": DEFAULT_START["region"],
                "x": str(int(DEFAULT_START["x"])),
                "z": str(int(DEFAULT_START["z"])),
            },
            {"claim": "", "region": "", "x": "", "z": ""},
            {"claim": "", "region": "", "x": "", "z": ""},
        ]

        for idx, default in enumerate(defaults):
            row = 2 + idx

            ttk.Radiobutton(
                self.settings_tab,
                variable=self.active_start_location_var,
                value=idx,
                command=self._on_start_location_selected,
            ).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)

            claim_var = tk.StringVar(value=default["claim"])
            region_var = tk.StringVar(value=default["region"])
            x_var = tk.StringVar(value=default["x"])
            z_var = tk.StringVar(value=default["z"])

            claim_combo = AutoCompleteCombobox(
                self.settings_tab,
                textvariable=claim_var,
                width=28,
                lookup_func=lambda q, i=idx: self._claim_lookup_for_location(i, q),
                min_chars=1,
                show_existing_when_empty=True,
            )
            claim_combo.grid(
                row=row,
                column=1,
                padx=(0, 10),
                sticky="ew",
                pady=3,
            )
            claim_combo.bind(
                "<<ComboboxSelected>>",
                lambda _e, i=idx: self._on_claim_selected(i),
                add="+",
            )
            self.start_claim_combos.append(claim_combo)

            region_combo = ttk.Combobox(
                self.settings_tab,
                textvariable=region_var,
                values=[],
                state="readonly",
                width=20,
            )
            region_combo.grid(
                row=row,
                column=2,
                padx=(0, 10),
                sticky="ew",
                pady=3,
            )
            region_combo.bind(
                "<<ComboboxSelected>>",
                lambda _e, i=idx: self._on_start_region_selected(i),
                add="+",
            )
            self.start_region_combos.append(region_combo)

            self.start_location_vars.append({
                "claim": claim_var,
                "region": region_var,
                "x": x_var,
                "z": z_var,
            })

            label_var = tk.StringVar()
            self.start_location_label_vars.append(label_var)

            claim_var.trace_add(
                "write",
                lambda *_args, i=idx: self._update_start_location_label(i)
            )
            region_var.trace_add(
                "write",
                lambda *_args, i=idx: self._update_start_location_label(i)
            )

        for idx in range(3):
            self._update_start_location_label(idx)

        initial_region_snapshot = [
            data["region"].get().strip()
            for data in self.start_location_vars
        ]
        threading.Thread(
            target=self._load_initial_claim_choices_worker,
            args=(initial_region_snapshot,),
            daemon=True,
        ).start()

        ttk.Label(
            self.settings_tab,
            text=(
                "Tip: Search and select a Claim from the dropdown. Region and claim-position "
                "data are loaded automatically from BitJita. BitJita coordinates are normalized "
                "to the in-game Small Hex scale before distance calculations."
            ),
        ).grid(row=5, column=0, columnspan=5, sticky="w", pady=(8, 0))

        ttk.Separator(self.settings_tab).grid(
            row=6, column=0, columnspan=5,
            sticky="ew", pady=18
        )

        ttk.Label(
            self.settings_tab,
            text="Shopping List Area Filter",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=7, column=0, columnspan=5, sticky="w")

        self.location_filter_var = tk.StringVar(value="anywhere")

        ttk.Radiobutton(
            self.settings_tab,
            text="Search everywhere",
            variable=self.location_filter_var,
            value="anywhere",
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Radiobutton(
            self.settings_tab,
            text="Current region only",
            variable=self.location_filter_var,
            value="region",
        ).grid(row=8, column=2, sticky="w", pady=(8, 0))

        ttk.Radiobutton(
            self.settings_tab,
            text="Within maximum distance",
            variable=self.location_filter_var,
            value="distance",
        ).grid(row=8, column=3, sticky="w", pady=(8, 0))

        self.max_distance_var = tk.StringVar(value="2500")
        ttk.Entry(
            self.settings_tab,
            textvariable=self.max_distance_var,
            width=12,
        ).grid(row=8, column=4, sticky="w", pady=(8, 0))

        ttk.Label(
            self.settings_tab,
            text="Note: maximum distance is the straight-line distance from the selected starting location.",
        ).grid(
            row=9, column=0, columnspan=5,
            sticky="w", pady=(4, 0)
        )

        ttk.Separator(self.settings_tab).grid(
            row=10, column=0, columnspan=5,
            sticky="ew", pady=18
        )

        ttk.Label(
            self.settings_tab,
            text="Price / Travel Balance",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=11, column=0, columnspan=5, sticky="w")

        self.optimize_mode_var = tk.StringVar(value="balanced")

        ttk.Radiobutton(
            self.settings_tab,
            text="Cheapest (ignore distance)",
            variable=self.optimize_mode_var,
            value="cheapest",
        ).grid(row=12, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Radiobutton(
            self.settings_tab,
            text="Balanced",
            variable=self.optimize_mode_var,
            value="balanced",
        ).grid(row=12, column=2, sticky="w", pady=(8, 0))

        ttk.Radiobutton(
            self.settings_tab,
            text="Least travel",
            variable=self.optimize_mode_var,
            value="travel",
        ).grid(row=12, column=3, sticky="w", pady=(8, 0))

        ttk.Radiobutton(
            self.settings_tab,
            text="Custom",
            variable=self.optimize_mode_var,
            value="custom",
        ).grid(row=12, column=4, sticky="w", pady=(8, 0))

        ttk.Label(
            self.settings_tab,
            text="Hex cost per 1 distance unit (Custom mode):",
        ).grid(row=13, column=0, columnspan=3, sticky="w", pady=(10, 0))

        self.custom_weight_var = tk.StringVar(value="2")
        ttk.Entry(
            self.settings_tab,
            textvariable=self.custom_weight_var,
            width=12,
        ).grid(row=13, column=3, sticky="w", pady=(10, 0))

        ttk.Label(
            self.settings_tab,
            text="Defaults: Cheapest=0, Balanced=2, Least travel=20.",
        ).grid(row=14, column=0, columnspan=5, sticky="w", pady=(4, 0))

        self.settings_tab.columnconfigure(0, weight=0)
        for col in range(1, 5):
            self.settings_tab.columnconfigure(col, weight=1)

    def _claim_lookup_for_location(self, index, query):
        if index >= len(self.start_location_vars):
            return claim_autocomplete_names(query)

        region = self.start_location_vars[index]["region"].get().strip()
        return claim_autocomplete_names(query, region)

    def _save_start_locations(self):
        if not hasattr(self, "start_location_vars"):
            return

        locations = []
        for data in self.start_location_vars:
            locations.append({
                "claim": data["claim"].get().strip(),
                "region": data["region"].get().strip(),
                "x": data["x"].get().strip(),
                "z": data["z"].get().strip(),
            })

        try:
            active = int(self.active_start_location_var.get())
        except Exception:
            active = 0

        _save_cached_start_locations(locations, active)

    def _on_start_region_selected(self, index):
        if index >= len(self.start_location_vars):
            return

        data = self.start_location_vars[index]

        # Region changed: an old Claim may no longer belong to this region.
        data["claim"].set("")
        data["x"].set("")
        data["z"].set("")
        self._update_start_location_label(index)

        region = data["region"].get().strip()
        self._save_start_locations()

        self.shop_status_var.set(
            f"Loading claims for {region or 'selected region'}..."
        )

        threading.Thread(
            target=self._load_claims_for_region_worker,
            args=(index, region),
            daemon=True,
        ).start()

    def _load_claims_for_region_worker(self, index, region):
        try:
            values = claim_autocomplete_names("", region)
        except Exception:
            values = []

        self.after(
            0,
            lambda vals=values, i=index, r=region:
            self._apply_claims_for_region(i, r, vals),
        )

    def _apply_claims_for_region(self, index, region, values):
        if index >= len(self.start_location_vars):
            return

        current_region = self.start_location_vars[index]["region"].get().strip()
        if current_region != region:
            return

        if index < len(self.start_claim_combos):
            self.start_claim_combos[index].set_suggestions(values)

        if region:
            self.shop_status_var.set(
                f"Loaded {len(values)} claim(s) for {region}."
            )
        else:
            self.shop_status_var.set("Ready.")

    def _load_initial_claim_choices_worker(self, region_snapshot):
        """
        Background worker: never read Tkinter variables here.

        Tkinter/StringVar access is main-thread-only. The caller passes plain
        Python strings captured before the thread starts.
        """
        results = []

        for index, region in enumerate(region_snapshot):
            try:
                values = claim_autocomplete_names("", region)
            except Exception:
                values = []
            results.append((index, region, values))

        self.after(
            0,
            lambda rows=results: self._apply_initial_claim_choices(rows),
        )

    def _apply_initial_claim_choices(self, results):
        for index, region, values in results:
            if index >= len(self.start_claim_combos):
                continue

            current_region = self.start_location_vars[index]["region"].get().strip()
            if current_region != region:
                continue

            self.start_claim_combos[index].set_suggestions(values)

    def _on_claim_selected(self, index):
        if index >= len(self.start_location_vars):
            return

        value = self.start_location_vars[index]["claim"].get().strip()
        claim_name = _claim_name_from_display(value)
        preferred_region = None

        if " — " in value:
            region_part = value.split(" — ", 1)[1].strip()
            preferred_region, _rid = parse_region_selection(region_part)

        # Keep the field itself as the clean claim name.
        self.start_location_vars[index]["claim"].set(claim_name)

        threading.Thread(
            target=self._resolve_selected_claim_worker,
            args=(index, claim_name, preferred_region),
            daemon=True,
        ).start()

    def _resolve_selected_claim_worker(self, index, claim_name, preferred_region):
        try:
            resolved = resolve_claim_by_name(claim_name, preferred_region)
        except Exception:
            resolved = None

        self.after(
            0,
            lambda: self._apply_selected_claim(index, resolved),
        )

    def _apply_selected_claim(self, index, resolved):
        if not resolved or index >= len(self.start_location_vars):
            return

        data = self.start_location_vars[index]
        data["claim"].set(resolved.get("claim") or "")

        region = str(resolved.get("region") or "").strip()
        rid = normalize_region_id(resolved.get("region_id"))
        if region and rid:
            region = f"{region} {rid}"
        data["region"].set(region)

        x = resolved.get("x")
        z = resolved.get("z")
        data["x"].set("" if x is None else f"{float(x):.0f}")
        data["z"].set("" if z is None else f"{float(z):.0f}")

        self._update_start_location_label(index)
        self._save_start_locations()

    def _update_start_location_label(self, index):
        if not hasattr(self, "start_location_vars"):
            return
        data = self.start_location_vars[index]
        claim = data["claim"].get().strip()
        region = data["region"].get().strip()

        if claim and region:
            label = f"{claim} ({region})"
        elif claim:
            label = claim
        else:
            label = f"Location {index + 1}"

        if index < len(self.start_location_label_vars):
            self.start_location_label_vars[index].set(label)

    def _on_start_location_selected(self):
        """Refresh the Shopping List automatically when the active start changes."""
        if not hasattr(self, "shop_status_var"):
            return

        index = int(self.active_start_location_var.get())
        label = self.start_location_label_vars[index].get()
        self._save_start_locations()
        self.shop_status_var.set(f"Starting location changed to {label}.")

        if getattr(self, "shopping_rows", None):
            try:
                if str(self.optimize_button.cget("state")) != "disabled":
                    self.after(50, self.start_shopping_optimizer)
            except Exception:
                pass

    def get_start_location(self):
        index = int(self.active_start_location_var.get())
        data = self.start_location_vars[index]

        claim = data["claim"].get().strip()
        region = data["region"].get().strip()
        x_text = data["x"].get().strip()
        z_text = data["z"].get().strip()

        if not claim:
            raise ValueError(
                f"Starting Location {index + 1} is not configured. "
                "Select a Claim under Location / Optimization."
            )

        x = None
        z = None

        if x_text or z_text:
            if not x_text or not z_text:
                raise ValueError(
                    f"Starting Location {index + 1}: enter both X and Z, or leave both blank."
                )
            try:
                x = float(x_text.replace(",", "."))
                z = float(z_text.replace(",", "."))
            except ValueError:
                raise ValueError(
                    f"Starting Location {index + 1}: X and Z must be numeric."
                )

        return {
            "claim": claim,
            "region": region,
            "x": x,
            "z": z,
        }

    def get_distance_weight(self):
        mode = self.optimize_mode_var.get()

        if mode == "cheapest":
            return 0.0
        if mode == "balanced":
            return 2.0
        if mode == "travel":
            return 20.0

        try:
            value = float(self.custom_weight_var.get().replace(",", "."))
        except ValueError:
            raise ValueError("Custom distance cost must be numeric.")

        if value < 0:
            raise ValueError("Distance cost cannot be negative.")

        return value

    def get_location_filter(self):
        mode = self.location_filter_var.get()

        max_distance = None
        if mode == "distance":
            try:
                max_distance = float(
                    self.max_distance_var.get().replace(",", ".")
                )
            except ValueError:
                raise ValueError("Maximum distance must be numeric.")

            if max_distance < 0:
                raise ValueError("Maximum distance cannot be negative.")

        return mode, max_distance

    # ---------------------------- Item Search ----------------------------

    def _build_search_tab(self):
        ttk.Label(
            self.search_tab,
            text="Item Search",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            self.search_tab,
            text=(
                "Search by item name, Item Type, Region, or a combination of them. "
                "For example, select Food + Zephyra to list Food sell orders in Zephyra."
            ),
        ).pack(anchor="w", pady=(2, 12))

        form = ttk.Frame(self.search_tab)
        form.pack(fill="x")

        ttk.Label(form, text="Item").grid(row=0, column=0, sticky="w")
        self.search_item_var = tk.StringVar()
        self.search_item_combo = AutoCompleteCombobox(
            form,
            textvariable=self.search_item_var,
            width=42,
        )
        self.search_item_combo.grid(
            row=1, column=0, padx=(0, 8), sticky="ew"
        )

        ttk.Label(form, text="Item Type").grid(row=0, column=1, sticky="w")
        self.search_category_var = tk.StringVar(value="Any")
        self.search_category_combo = ttk.Combobox(
            form,
            textvariable=self.search_category_var,
            values=["Any"],
            state="readonly",
            width=18,
        )
        self.search_category_combo.grid(row=1, column=1, padx=(0, 8))

        ttk.Label(form, text="Region").grid(row=0, column=2, sticky="w")
        self.search_region_var = tk.StringVar(value="Any")
        self.search_region_combo = ttk.Combobox(
            form,
            textvariable=self.search_region_var,
            values=["Any"],
            state="readonly",
            width=20,
        )
        self.search_region_combo.grid(row=1, column=2, padx=(0, 8))

        ttk.Label(form, text="Rarity").grid(row=0, column=3, sticky="w")
        self.search_rarity_var = tk.StringVar(value="Any")
        ttk.Combobox(
            form,
            textvariable=self.search_rarity_var,
            values=RARITIES,
            state="readonly",
            width=13,
        ).grid(row=1, column=3, padx=(0, 8))

        ttk.Label(form, text="Tier").grid(row=0, column=4, sticky="w")
        self.search_tier_var = tk.StringVar(value="Any")
        ttk.Combobox(
            form,
            textvariable=self.search_tier_var,
            values=TIERS,
            state="readonly",
            width=9,
        ).grid(row=1, column=4, padx=(0, 8))

        ttk.Label(form, text="Sort by").grid(row=0, column=5, sticky="w")
        self.search_sort_var = tk.StringVar(value="Price + Distance")
        ttk.Combobox(
            form,
            textvariable=self.search_sort_var,
            values=["Price", "Distance", "Price + Distance"],
            state="readonly",
            width=17,
        ).grid(row=1, column=5, padx=(0, 8))

        ttk.Label(form, text="Min Quantity").grid(
            row=0,
            column=6,
            sticky="w",
        )
        self.search_min_qty_var = tk.StringVar(value="")
        self.search_min_qty_entry = ttk.Entry(
            form,
            textvariable=self.search_min_qty_var,
            width=11,
        )
        self.search_min_qty_entry.grid(
            row=1,
            column=6,
            padx=(0, 8),
            sticky="ew",
        )

        self.search_button = ttk.Button(
            form,
            text="Search",
            command=self._search_button_action,
        )
        self.search_button.grid(row=1, column=7)

        form.columnconfigure(0, weight=1)

        self.search_item_combo.bind(
            "<Return>",
            lambda _event: self.start_single_search(),
        )

        self.search_min_qty_entry.bind(
            "<Return>",
            lambda _event: self.start_single_search(),
        )

        ttk.Separator(self.search_tab).pack(fill="x", pady=12)

        self.search_best_var = tk.StringVar(
            value="No search yet."
        )
        ttk.Label(
            self.search_tab,
            textvariable=self.search_best_var,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        table_frame = ttk.Frame(self.search_tab)
        table_frame.pack(fill="both", expand=True)

        columns = (
            "price", "quantity", "distance", "est_tp", "item", "tier", "rarity",
            "claim", "region", "seller", "id"
        )
        self.search_tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        headings = {
            "price": "Price",
            "distance": "Distance",
            "est_tp": "Est. TP",
            "item": "Item",
            "tier": "Tier",
            "rarity": "Rarity",
            "quantity": "Quantity",
            "claim": "Location",
            "region": "Region",
            "seller": "Seller",
            "id": "Item ID",
        }

        widths = {
            "price": 90,
            "distance": 90,
            "est_tp": 70,
            "item": 210,
            "tier": 55,
            "rarity": 90,
            "quantity": 60,
            "claim": 190,
            "region": 110,
            "seller": 130,
            "id": 110,
        }

        self.search_headings = headings
        self.search_sort_column = None
        self.search_sort_reverse = False

        for col in columns:
            self.search_tree.heading(
                col,
                text=headings[col],
                command=lambda c=col: self._sort_search_results_by_column(c),
            )
            self.search_tree.column(
                col,
                width=widths[col],
                anchor="e" if col in {"price", "distance", "est_tp", "tier", "quantity"} else "w",
            )

        ybar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.search_tree.yview,
        )
        xbar = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.search_tree.xview,
        )

        self.search_tree.configure(
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
        )

        self.search_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.search_tree.bind("<Double-1>", self.open_search_result)

        self.search_context_menu = tk.Menu(
            self.search_tree,
            tearoff=False,
        )
        self.search_context_menu.add_command(
            label="Add to Shopping List",
            command=self.add_search_result_to_shopping_list,
        )
        self.search_tree.bind("<Button-3>", self._show_search_context_menu)

        self.search_status_var = tk.StringVar(value="Ready.")
        ttk.Label(
            self.search_tab,
            textvariable=self.search_status_var,
        ).pack(fill="x", pady=(8, 0))

        # Load the category list without blocking the GUI.
        threading.Thread(
            target=self._load_market_categories_worker,
            daemon=True,
        ).start()

        threading.Thread(
            target=self._load_market_regions_worker,
            daemon=True,
        ).start()

    def _load_market_categories_worker(self):
        try:
            categories = market_categories()
        except Exception:
            categories = []

        self.after(
            0,
            lambda: self._apply_market_categories(categories),
        )

    def _apply_market_categories(self, categories):
        values = ["Any"] + categories
        self.search_category_combo.configure(values=values)

        # Preserve the current selection if possible.
        current = self.search_category_var.get()
        if current not in values:
            self.search_category_var.set("Any")

    def _load_market_regions_worker(self):
        try:
            regions = market_regions()
        except Exception:
            regions = []

        self.after(
            0,
            lambda: self._apply_market_regions(regions),
        )

    def _apply_market_regions(self, regions):
        regions = list(regions)

        # Item Search keeps the synthetic "Any" option.
        values = ["Any"] + regions
        self.search_region_combo.configure(values=values)

        current = self.search_region_var.get()
        if current not in values:
            self.search_region_var.set("Any")

        # Location / Optimization uses the real BitJita region list only.
        for combo in getattr(self, "start_region_combos", []):
            combo.configure(values=regions)

        for idx, data in enumerate(getattr(self, "start_location_vars", [])):
            current_region = data["region"].get().strip()
            if current_region and current_region not in regions:
                # Preserve an already resolved/default value if the exact
                # presentation label is not returned by the current API list.
                existing = list(regions)
                existing.insert(0, current_region)
                if idx < len(self.start_region_combos):
                    self.start_region_combos[idx].configure(values=existing)

            # Keep the Claim suggestions synchronized with the row's Region.
            if idx < len(self.start_claim_combos):
                try:
                    vals = claim_autocomplete_names("", current_region)
                except Exception:
                    vals = []
                self.start_claim_combos[idx].set_suggestions(vals)

    def _search_button_action(self):
        if self.search_button.cget("text") == "Cancel":
            self.cancel_single_search()
        else:
            self.start_single_search()

    def cancel_single_search(self):
        # Network calls already in progress cannot be forcibly killed safely,
        # so invalidate this search job. Its eventual result/error callback
        # will be ignored.
        self._search_job_id = getattr(self, "_search_job_id", 0) + 1
        self._search_cancelled = True

        self.search_button.config(
            text="Search",
            state="normal",
        )
        self.search_best_var.set("Search cancelled.")
        self.search_status_var.set("Search cancelled.")

    def _search_job_is_current(self, job_id):
        return (
            not getattr(self, "_search_cancelled", False)
            and job_id == getattr(self, "_search_job_id", 0)
        )

    def start_single_search(self):
        query = self.search_item_var.get().strip()
        category = self.search_category_var.get().strip() or "Any"
        region = self.search_region_var.get().strip() or "Any"

        if query and len(query) < 2:
            messagebox.showwarning(
                "Missing information",
                "Enter at least 2 characters for the item name, or leave it blank and select an Item Type.",
            )
            return

        if not query and category == "Any":
            messagebox.showwarning(
                "Missing information",
                "Enter an item name or select an Item Type. Region can be used together with either one.",
            )
            return

        try:
            start = self.get_start_location()
            weight = self.get_distance_weight()

            resolved_start = resolve_claim_by_name(
                start["claim"],
                start.get("region"),
            )
            if (
                resolved_start
                and resolved_start.get("x") is not None
                and resolved_start.get("z") is not None
            ):
                start = resolved_start
            elif start.get("x") is None or start.get("z") is None:
                raise ValueError(
                    f"Could not resolve starting location '{start['claim']}'. "
                    "Check the Claim and Region selection."
                )
        except ValueError as exc:
            messagebox.showerror("Settings error", str(exc))
            return

        rarity = self.search_rarity_var.get()
        tier = self.search_tier_var.get()
        sort_mode = self.search_sort_var.get()

        min_qty_text = self.search_min_qty_var.get().strip()
        if min_qty_text:
            try:
                min_quantity = int(min_qty_text)
            except ValueError:
                messagebox.showwarning(
                    "Invalid quantity",
                    "Min Quantity must be a whole number.",
                )
                return

            if min_quantity < 1:
                messagebox.showwarning(
                    "Invalid quantity",
                    "Min Quantity must be 1 or greater.",
                )
                return
        else:
            min_quantity = None

        self._reset_search_heading_sort_state()

        self._search_cancelled = False
        self._search_job_id = getattr(self, "_search_job_id", 0) + 1
        job_id = self._search_job_id

        self.search_button.config(
            text="Cancel",
            state="normal",
        )
        self.search_status_var.set("Searching BitJita...")
        self.search_best_var.set("Searching...")

        for row in self.search_tree.get_children():
            self.search_tree.delete(row)

        threading.Thread(
            target=self._single_search_worker,
            args=(
                query,
                rarity,
                tier,
                category,
                region,
                sort_mode,
                start,
                weight,
                min_quantity,
                job_id,
            ),
            daemon=True,
        ).start()

    def _single_search_worker(
        self,
        query,
        rarity,
        tier,
        category,
        region,
        sort_mode,
        start,
        weight,
        min_quantity,
        job_id,
    ):
        try:
            if not self._search_job_is_current(job_id):
                return

            items = market_search(
                query=query,
                rarity=rarity,
                tier=tier,
                category=category,
                exact_preferred=bool(query),
            )

            if not self._search_job_is_current(job_id):
                return

            orders = fetch_orders_for_items_parallel(
                items,
                cancel_check=lambda: not self._search_job_is_current(job_id),
            )

            if not self._search_job_is_current(job_id):
                return

            total_items_before_region = len(items)
            total_orders_before_region = len(orders)

            if region != "Any":
                all_orders_before_region_filter = orders
                orders = [
                    order for order in all_orders_before_region_filter
                    if order_matches_region(order, region)
                ]

                # Defensive fallback: labels such as "Zephra R19" are UI labels.
                # If an endpoint exposes only "Zephra", never let the suffix
                # accidentally eliminate otherwise valid sell orders.
                if not orders:
                    wanted_name, _wanted_id = parse_region_selection(region)
                    if wanted_name:
                        orders = [
                            order for order in all_orders_before_region_filter
                            if str(order.get("region") or "").strip().casefold()
                            == wanted_name.casefold()
                        ]

            if min_quantity is not None:
                orders = [
                    order
                    for order in orders
                    if (order.get("quantity") or 0) >= min_quantity
                ]

            for order in orders:
                if not self._search_job_is_current(job_id):
                    return
                order["distance_from_start"] = straight_distance(start, order)

            if sort_mode == "Price":
                orders.sort(key=lambda x: x["price"])
            elif sort_mode == "Distance":
                orders.sort(
                    key=lambda x: (
                        float("inf")
                        if x["distance_from_start"] is None
                        else x["distance_from_start"],
                        x["price"],
                    )
                )
            else:
                # Quantity-aware Price + Distance ranking.
                #
                # Keep Min Quantity as a stock filter, but when it is provided
                # also use it as the effective purchase quantity for ranking.
                # This makes small purchases favor shorter trips, while larger
                # purchases naturally give more importance to unit price.
                #
                # Internal travel valuation:
                #     1 estimated TP = 25 Hex
                effective_quantity = max(1, int(min_quantity or 1))
                tp_value_hex = 25.0

                def price_distance_score(order):
                    distance = order.get("distance_from_start")
                    est_tp = estimate_tp(distance)
                    if est_tp is None:
                        return (float("inf"), float("inf"), float("inf"))

                    purchase_cost = float(order["price"]) * effective_quantity
                    travel_cost = float(est_tp) * tp_value_hex
                    total_score = purchase_cost + travel_cost

                    # Deterministic tie-breakers: cheaper unit price, then TP.
                    return (
                        total_score,
                        float(order["price"]),
                        float(est_tp),
                    )

                orders.sort(key=price_distance_score)

            if not self._search_job_is_current(job_id):
                return

            self.after(
                0,
                lambda rows=orders, jid=job_id:
                self._display_single_results_if_current(jid, rows),
            )

        except Exception as exc:
            self.after(
                0,
                lambda msg=str(exc), jid=job_id:
                self._single_search_error_if_current(jid, msg),
            )

    def _display_single_results_if_current(self, job_id, orders):
        if not self._search_job_is_current(job_id):
            return

        self._display_single_results(orders)

    def _single_search_error_if_current(self, job_id, text):
        if not self._search_job_is_current(job_id):
            return

        self._single_search_error(text)

    def _display_single_results(self, orders):
        self.search_results = list(orders)
        self.search_default_results = list(orders)
        self.search_button.config(text="Search", state="normal")

        if not orders:
            region = self.search_region_var.get().strip() or "Any"
            min_qty_text = self.search_min_qty_var.get().strip()

            if min_qty_text and region != "Any":
                self.search_best_var.set(
                    f"No sell orders found in {region} with quantity ≥ {min_qty_text}."
                )
            elif min_qty_text:
                self.search_best_var.set(
                    f"No sell orders found with quantity ≥ {min_qty_text}."
                )
            elif region != "Any":
                self.search_best_var.set(
                    f"No active sell orders found in {region}."
                )
            else:
                self.search_best_var.set("No active sell orders found.")

            self.search_status_var.set("No results.")
            return

        self._render_search_tree()

        best = orders[0]
        dist = (
            "distance ?"
            if best["distance_from_start"] is None
            else f"{best['distance_from_start']:.0f} distance"
        )

        self.search_best_var.set(
            f"Top result: {best['price']:,.0f} Hex | "
            f"{best['claim']} / "
            f"{region_label(best)} | "
            f"{dist} | "
            f"Est. TP {format_estimated_tp(best.get('distance_from_start'))}"
        )

        self.search_status_var.set(
            f"{len(orders)} active sell orders listed."
        )

    def _render_search_tree(self):
        for item_id in self.search_tree.get_children():
            self.search_tree.delete(item_id)

        for idx, row in enumerate(self.search_results):
            distance = format_distance(row.get("distance_from_start"))

            self.search_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    f"{row['price']:,.0f}",
                    row["quantity"],
                    distance,
                    format_estimated_tp(row.get("distance_from_start")),
                    row["item"],
                    f"T{int(row['tier'])}" if row.get("tier") else "?",
                    row["rarity"],
                    row["claim"],
                    region_label(row),
                    row["seller"],
                    row["item_id"],
                ),
            )

    def _sort_search_results_by_column(self, column):
        if not self.search_results:
            return

        # Three-click cycle for every column:
        #   1st click -> ascending
        #   2nd click -> descending
        #   3rd click -> restore the original Price + Distance search order
        if self.search_sort_column != column:
            state = "asc"
        elif not self.search_sort_reverse:
            state = "desc"
        else:
            state = "default"

        if state == "default":
            self.search_results = list(self.search_default_results)
            self.search_sort_column = None
            self.search_sort_reverse = False
            self._render_search_tree()

            for col, label in self.search_headings.items():
                self.search_tree.heading(
                    col,
                    text=label,
                    command=lambda c=col: self._sort_search_results_by_column(c),
                )
            return

        reverse = state == "desc"
        self.search_sort_column = column
        self.search_sort_reverse = reverse

        def text_key(value):
            return str(value or "").casefold()

        if column == "price":
            key_func = lambda r: float(r.get("price") or 0)
        elif column == "distance":
            sentinel = float("-inf") if reverse else float("inf")
            key_func = lambda r: (
                sentinel
                if r.get("distance_from_start") is None
                else float(r.get("distance_from_start"))
            )
        elif column == "est_tp":
            sentinel = float("-inf") if reverse else float("inf")
            key_func = lambda r: (
                sentinel
                if r.get("distance_from_start") is None
                else estimate_tp(r.get("distance_from_start"))
            )
        elif column == "item":
            key_func = lambda r: text_key(r.get("item"))
        elif column == "tier":
            sentinel = float("-inf") if reverse else float("inf")
            key_func = lambda r: (
                sentinel if r.get("tier") is None else float(r.get("tier"))
            )
        elif column == "rarity":
            key_func = lambda r: text_key(r.get("rarity"))
        elif column == "quantity":
            key_func = lambda r: float(r.get("quantity") or 0)
        elif column == "claim":
            key_func = lambda r: text_key(r.get("claim"))
        elif column == "region":
            key_func = lambda r: text_key(region_label(r))
        elif column == "seller":
            key_func = lambda r: text_key(r.get("seller"))
        elif column == "id":
            key_func = lambda r: text_key(r.get("item_id"))
        else:
            return

        self.search_results.sort(key=key_func, reverse=reverse)
        self._render_search_tree()

        for col, label in self.search_headings.items():
            suffix = ""
            if col == column:
                suffix = " ▼" if reverse else " ▲"
            self.search_tree.heading(
                col,
                text=label + suffix,
                command=lambda c=col: self._sort_search_results_by_column(c),
            )

    def _show_search_context_menu(self, event):
        row_id = self.search_tree.identify_row(event.y)
        if not row_id:
            return

        self.search_tree.selection_set(row_id)
        self.search_tree.focus(row_id)

        try:
            self.search_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.search_context_menu.grab_release()

    def add_search_result_to_shopping_list(self):
        selection = self.search_tree.selection()
        if not selection:
            return

        try:
            row = self.search_results[int(selection[0])]
        except (IndexError, ValueError):
            return

        tier = (
            f"T{int(row['tier'])}"
            if row.get("tier") is not None
            else "Any"
        )
        rarity = row.get("rarity") or "Any"

        self._append_or_increment_shopping_row(
            item=row.get("item") or "",
            rarity=rarity,
            tier=tier,
            qty=1,
        )
        self._refresh_shopping_list()
        self.shop_status_var.set(
            f"Added {row.get('item') or 'item'} to the Shopping List."
        )

    def _reset_search_heading_sort_state(self):
        self.search_sort_column = None
        self.search_sort_reverse = False

        for col, label in self.search_headings.items():
            self.search_tree.heading(
                col,
                text=label,
                command=lambda c=col: self._sort_search_results_by_column(c),
            )

    def _single_search_error(self, text):
        self.search_button.config(text="Search", state="normal")
        self.search_best_var.set("An error occurred during search.")
        self.search_status_var.set("Error.")
        messagebox.showerror("Error", text)

    def open_search_result(self, _event=None):
        selection = self.search_tree.selection()
        if not selection:
            return

        try:
            row = self.search_results[int(selection[0])]
        except (IndexError, ValueError):
            return

        webbrowser.open(f"{SITE_URL}/market/item/{row['item_id']}")

    # ---------------------------- Shopping List ----------------------------

    def _build_shopping_tab(self):
        ttk.Label(
            self.shopping_tab,
            text="Shopping List",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")

        self.shop_intro_label = ttk.Label(
            self.shopping_tab,
            text=(
                "Build your list; the app will calculate "
                "which markets to buy from based on price + travel balance."
            ),
        )
        self.shop_intro_label.pack(anchor="w", pady=(2, 10))

        self.start_frame = ttk.LabelFrame(
            self.shopping_tab,
            text="Starting Location",
            padding=(10, 7),
        )
        self.start_frame.pack(fill="x", pady=(0, 10))
        start_frame = self.start_frame

        for idx in range(3):
            ttk.Radiobutton(
                start_frame,
                textvariable=self.start_location_label_vars[idx],
                variable=self.active_start_location_var,
                value=idx,
                command=self._on_start_location_selected,
            ).pack(side="left", padx=(0, 18))

        add_frame = ttk.Frame(self.shopping_tab)
        add_frame.pack(fill="x")

        ttk.Label(add_frame, text="Item").grid(row=0, column=0, sticky="w")
        self.shop_item_var = tk.StringVar()
        self.shop_item_combo = AutoCompleteCombobox(
            add_frame,
            textvariable=self.shop_item_var,
            width=38,
        )
        self.shop_item_combo.grid(
            row=1, column=0, padx=(0, 8), sticky="ew"
        )

        ttk.Label(add_frame, text="Rarity").grid(row=0, column=1, sticky="w")
        self.shop_rarity_var = tk.StringVar(value="Any")
        ttk.Combobox(
            add_frame,
            textvariable=self.shop_rarity_var,
            values=RARITIES,
            state="readonly",
            width=13,
        ).grid(row=1, column=1, padx=(0, 8))

        ttk.Label(add_frame, text="Tier").grid(row=0, column=2, sticky="w")
        self.shop_tier_var = tk.StringVar(value="Any")
        ttk.Combobox(
            add_frame,
            textvariable=self.shop_tier_var,
            values=TIERS,
            state="readonly",
            width=9,
        ).grid(row=1, column=2, padx=(0, 8))

        ttk.Label(add_frame, text="Quantity").grid(row=0, column=3, sticky="w")
        self.shop_qty_var = tk.IntVar(value=1)
        ttk.Spinbox(
            add_frame,
            from_=1,
            to=999,
            textvariable=self.shop_qty_var,
            width=7,
        ).grid(row=1, column=3, padx=(0, 8))

        ttk.Button(
            add_frame,
            text="Add to List",
            command=self.add_shopping_item,
        ).grid(row=1, column=4, padx=(0, 8))

        ttk.Button(
            add_frame,
            text="Remove Selected",
            command=self.remove_shopping_item,
        ).grid(row=1, column=5)

        add_frame.columnconfigure(0, weight=1)

        self.set_section = ttk.Frame(self.shopping_tab)
        self.set_section.pack(fill="x", pady=(10, 0))

        self.set_section_header = ttk.Frame(self.set_section)
        self.set_section_header.pack(fill="x")

        self.set_section_open = tk.BooleanVar(value=False)
        self.set_toggle_button = ttk.Button(
            self.set_section_header,
            text="▶ Add Equipment Set",
            command=self._toggle_set_section,
            style="SetToggle.TButton",
        )
        self.set_toggle_button.pack(side="left", anchor="w")

        self.set_frame = ttk.Frame(
            self.set_section,
            padding=(10, 7),
        )
        set_frame = self.set_frame

        ttk.Label(set_frame, text="Armor Type").grid(row=0, column=0, sticky="w")
        self.shop_armor_type_var = tk.StringVar(value="Leather")
        self.shop_armor_type_combo = ttk.Combobox(
            set_frame,
            textvariable=self.shop_armor_type_var,
            values=list(ARMOR_CATEGORY_BY_TYPE.keys()),
            state="readonly",
            width=14,
        )
        self.shop_armor_type_combo.grid(row=1, column=0, padx=(0, 8))
        self.shop_armor_type_combo.bind(
            "<<ComboboxSelected>>",
            self._on_armor_type_changed,
        )

        ttk.Label(set_frame, text="Set").grid(row=0, column=1, sticky="w")
        self.shop_set_var = tk.StringVar(value="Fine Leather Set")
        self.shop_set_combo = ttk.Combobox(
            set_frame,
            textvariable=self.shop_set_var,
            values=list(LEATHER_SETS.keys()),
            state="readonly",
            width=32,
        )
        self.shop_set_combo.grid(row=1, column=1, padx=(0, 8), sticky="ew")

        ttk.Label(set_frame, text="Rarity").grid(row=0, column=2, sticky="w")
        self.shop_set_rarity_var = tk.StringVar(value="Any")
        ttk.Combobox(
            set_frame,
            textvariable=self.shop_set_rarity_var,
            values=RARITIES,
            state="readonly",
            width=13,
        ).grid(row=1, column=2, padx=(0, 8))

        ttk.Label(set_frame, text="Sets").grid(row=0, column=3, sticky="w")
        self.shop_set_qty_var = tk.IntVar(value=1)
        ttk.Spinbox(
            set_frame,
            from_=1,
            to=99,
            textvariable=self.shop_set_qty_var,
            width=7,
        ).grid(row=1, column=3, padx=(0, 8))

        ttk.Button(
            set_frame,
            text="Add Set",
            command=self.add_shopping_set,
        ).grid(row=1, column=4)

        self.set_hint_label = ttk.Label(
            set_frame,
            text="Leather, Metal and Cloth set families are loaded from BitJita; only pieces that actually exist are added.",
        )
        self.set_hint_label.grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(5, 0)
        )

        set_frame.columnconfigure(1, weight=1)

        # Maps the visible set name to prefix/tier/category for the currently
        # selected armor type.
        self.shop_set_definitions = {
            name: {
                "prefix": definition["prefix"],
                "tier": definition["tier"],
                "category": resolve_armor_category("Leather"),
            }
            for name, definition in LEATHER_SETS.items()
        }

        self.shop_list_frame = ttk.LabelFrame(
            self.shopping_tab,
            text="Shopping List",
            padding=8,
        )
        self.shop_list_frame.pack(fill="x", pady=(12, 8))
        list_frame = self.shop_list_frame

        columns = ("item", "rarity", "tier", "qty")
        self.shop_list_tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="headings",
            height=6,
            selectmode="browse",
        )

        for col, title, width in [
            ("item", "Item", 340),
            ("rarity", "Rarity", 120),
            ("tier", "Tier", 80),
            ("qty", "Quantity", 80),
        ]:
            self.shop_list_tree.heading(col, text=title)
            self.shop_list_tree.column(
                col,
                width=width,
                anchor="w" if col == "item" else "center",
            )

        self.shop_list_scrollbar = ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=self.shop_list_tree.yview,
        )
        self.shop_list_tree.configure(
            yscrollcommand=self.shop_list_scrollbar.set,
        )

        self.shop_list_tree.grid(row=0, column=0, sticky="nsew")
        self.shop_list_scrollbar.grid(row=0, column=1, sticky="ns")

        self.shop_list_context_menu = tk.Menu(
            self.shop_list_tree,
            tearoff=False,
        )
        self.shop_list_context_menu.add_command(
            label="Edit",
            command=self.edit_selected_shopping_item,
        )
        self.shop_list_context_menu.add_command(
            label="Remove",
            command=self.remove_shopping_item,
        )
        self.shop_list_tree.bind(
            "<Button-3>",
            self._show_shopping_list_context_menu,
        )

        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        action_frame = ttk.Frame(self.shopping_tab)
        action_frame.pack(fill="x", pady=(4, 8))

        self.optimize_button = ttk.Button(
            action_frame,
            text="Optimize Shopping List",
            command=self.start_shopping_optimizer,
        )
        self.optimize_button.pack(side="left")

        ttk.Button(
            action_frame,
            text="Clear List",
            command=self.clear_shopping_list,
        ).pack(side="left", padx=(8, 0))

        self.purchase_mode_var = tk.StringVar(value="Buy from Sell Orders")
        self.purchase_mode_combo = ttk.Combobox(
            action_frame,
            textvariable=self.purchase_mode_var,
            values=["Buy from Sell Orders", "Plan Buy Orders"],
            state="readonly",
            width=21,
        )
        self.purchase_mode_combo.pack(side="right")
        self.purchase_mode_combo.bind(
            "<<ComboboxSelected>>",
            self._on_purchase_mode_changed,
        )
        ttk.Label(action_frame, text="Purchase Mode:").pack(
            side="right", padx=(12, 6)
        )

        self.buy_price_strategy_var = tk.StringVar(
            value="Highest Current Buy Price"
        )

        # Buy-order-only controls live in their own frame so they can be
        # completely hidden while normal sell-order purchasing is selected.
        self.buy_strategy_frame = ttk.Frame(action_frame)

        self.buy_price_strategy_combo = ttk.Combobox(
            self.buy_strategy_frame,
            textvariable=self.buy_price_strategy_var,
            values=list(BUY_ORDER_STRATEGIES),
            state="readonly",
            width=24,
        )
        self.buy_price_strategy_combo.pack(side="right")
        self.buy_price_strategy_combo.bind(
            "<<ComboboxSelected>>",
            self._on_buy_strategy_changed,
        )

        ttk.Label(
            self.buy_strategy_frame,
            text="Price Strategy:",
        ).pack(side="right", padx=(12, 6))

        # Visible processing status directly under the action buttons.
        self.shop_status_var = tk.StringVar(value="Ready.")
        self.progress_frame = ttk.Frame(self.shopping_tab)
        self.progress_frame.pack(fill="x", pady=(2, 8))
        progress_frame = self.progress_frame

        ttk.Label(
            progress_frame,
            textvariable=self.shop_status_var,
        ).pack(anchor="w")

        self.shop_progress = ttk.Progressbar(
            progress_frame,
            mode="indeterminate",
        )

        self.shop_summary_var = tk.StringVar(
            value="Add items to the list and optimize."
        )
        self.shop_summary_label = ttk.Label(
            self.shopping_tab,
            textvariable=self.shop_summary_var,
            font=("Segoe UI", 10, "bold"),
        )
        self.shop_summary_label.pack(anchor="w", pady=(4, 8))

        self.shopping_solution_mode_var = tk.StringVar(value="Balanced")
        self.shopping_solutions = {}
        self.shopping_solution_context = None

        self.result_notebook = ttk.Notebook(self.shopping_tab)
        self.result_notebook.pack(fill="both", expand=True)

        # Keep Plan option as a dropdown, but place it in the free area to the
        # right of the Purchase Plan / Route notebook tabs.
        self.solution_frame = ttk.Frame(self.result_notebook)
        ttk.Label(self.solution_frame, text="Plan option:").pack(side="left")
        self.shopping_solution_combo = ttk.Combobox(
            self.solution_frame,
            textvariable=self.shopping_solution_mode_var,
            values=["Cheapest", "Nearest", "Balanced"],
            state="readonly",
            width=14,
        )
        self.shopping_solution_combo.pack(side="left", padx=(8, 0))
        self.shopping_solution_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._show_selected_shopping_solution(),
        )
        self.solution_frame.place(
            relx=1.0,
            x=-8,
            y=3,
            anchor="ne",
        )
        self.solution_frame.lift()

        plan_frame = ttk.Frame(self.result_notebook)
        route_frame = ttk.Frame(self.result_notebook)
        self.plan_frame = plan_frame
        self.route_frame = route_frame

        self.result_notebook.add(plan_frame, text="Purchase Plan")
        self.result_notebook.add(route_frame, text="Route")

        self.tp_note_label = ttk.Label(
            self.shopping_tab,
            text="Est. TP assumes an empty inventory and rounds up per 400 hex.",
        )
        self.tp_note_label.pack(anchor="w", pady=(4, 0))

        # Purchase plan tree
        plan_columns = (
            "item", "qty", "cost", "unit", "claim",
            "region", "distance", "est_tp", "seller", "id"
        )
        self.plan_tree = ttk.Treeview(
            plan_frame,
            columns=plan_columns,
            show="headings",
        )

        plan_defs = [
            ("item", "Item", 220),
            ("qty", "Quantity", 55),
            ("cost", "Total", 90),
            ("unit", "Avg. Unit", 85),
            ("claim", "Location", 180),
            ("region", "Region", 100),
            ("distance", "Distance from Start", 110),
            ("est_tp", "Est. TP", 70),
            ("seller", "Seller(s)", 190),
            ("id", "Item ID", 110),
        ]

        for col, title, width in plan_defs:
            self.plan_tree.heading(col, text=title)
            self.plan_tree.column(
                col,
                width=width,
                anchor="w" if col == "item" else "center",
            )

        buy_plan_columns = (
            "item", "qty", "method", "suggested", "total", "status"
        )
        self.buy_plan_tree = ttk.Treeview(
            plan_frame,
            columns=buy_plan_columns,
            show="headings",
        )
        for col, title, width in [
            ("item", "Item", 260),
            ("qty", "Quantity", 85),
            ("method", "Price Method", 190),
            ("suggested", "Suggested Price", 120),
            ("total", "Estimated Total", 130),
            ("status", "Status", 260),
        ]:
            self.buy_plan_tree.heading(col, text=title)
            self.buy_plan_tree.column(
                col,
                width=width,
                anchor="w" if col == "item" else "center",
            )

        p_y = ttk.Scrollbar(
            plan_frame,
            orient="vertical",
            command=self.plan_tree.yview,
        )
        p_x = ttk.Scrollbar(
            plan_frame,
            orient="horizontal",
            command=self.plan_tree.xview,
        )

        self.plan_ybar = p_y
        self.plan_xbar = p_x

        self.plan_tree.configure(
            yscrollcommand=p_y.set,
            xscrollcommand=p_x.set,
        )
        self.buy_plan_tree.configure(
            yscrollcommand=p_y.set,
            xscrollcommand=p_x.set,
        )

        self.plan_tree.grid(row=0, column=0, sticky="nsew")
        p_y.grid(row=0, column=1, sticky="ns")
        p_x.grid(row=1, column=0, sticky="ew")
        plan_frame.rowconfigure(0, weight=1)
        plan_frame.columnconfigure(0, weight=1)

        self.plan_tree.bind("<Double-1>", self.open_plan_result)
        self.buy_plan_tree.bind("<Double-1>", self.open_buy_plan_result)

        # Route tree
        route_columns = ("stop", "claim", "region", "from_prev", "est_tp", "items")
        self.route_tree = ttk.Treeview(
            route_frame,
            columns=route_columns,
            show="headings",
        )

        for col, title, width in [
            ("stop", "#", 45),
            ("claim", "Location", 220),
            ("region", "Region", 120),
            ("from_prev", "From Previous Stop", 120),
            ("est_tp", "Est. TP", 70),
            ("items", "Items to Buy Here", 520),
        ]:
            self.route_tree.heading(col, text=title)
            self.route_tree.column(col, width=width)

        self.route_tree.pack(fill="both", expand=True)

        # Keep Purchase Plan / Route visible when the window is shorter.
        self._shopping_compact_mode = None
        self._shopping_resize_after_id = None
        self.bind("<Configure>", self._on_window_resize, add="+")
        self.after(100, self._update_shopping_responsive_layout)
        self.after(0, lambda: self._set_purchase_result_mode(False))


    def _set_purchase_result_mode(self, buy_order_mode):
        if buy_order_mode:
            self.buy_price_strategy_combo.configure(state="readonly")
            self.plan_tree.grid_remove()
            self.buy_plan_tree.grid(row=0, column=0, sticky="nsew")
            self.plan_ybar.configure(command=self.buy_plan_tree.yview)
            self.plan_xbar.configure(command=self.buy_plan_tree.xview)
            self.result_notebook.tab(self.plan_frame, text="Buy Order Plan")
            self.result_notebook.hide(self.route_frame)
            self.solution_frame.place_forget()
            self.tp_note_label.pack_forget()
        else:
            self.buy_price_strategy_combo.configure(state="disabled")
            self.buy_plan_tree.grid_remove()
            self.plan_tree.grid(row=0, column=0, sticky="nsew")
            self.plan_ybar.configure(command=self.plan_tree.yview)
            self.plan_xbar.configure(command=self.plan_tree.xview)
            self.result_notebook.tab(self.plan_frame, text="Purchase Plan")
            self.result_notebook.add(self.route_frame, text="Route")
            self.solution_frame.place(relx=1.0, x=-8, y=3, anchor="ne")
            self.solution_frame.lift()
            if not self.tp_note_label.winfo_manager():
                self.tp_note_label.pack(anchor="w", pady=(4, 0))

    def _on_purchase_mode_changed(self, _event=None):
        buy_mode = self.purchase_mode_var.get() == "Plan Buy Orders"

        if buy_mode:
            if not self.buy_strategy_frame.winfo_manager():
                self.buy_strategy_frame.pack(
                    side="right",
                    before=self.purchase_mode_combo,
                )
        else:
            self.buy_strategy_frame.pack_forget()

        self._set_purchase_result_mode(buy_mode)

        if self.shopping_rows:
            self.after(20, self.start_shopping_optimizer)

    def _on_buy_strategy_changed(self, _event=None):
        if (
            self.purchase_mode_var.get() == "Plan Buy Orders"
            and self.shopping_rows
        ):
            self.after(20, self.start_shopping_optimizer)

    def _toggle_set_section(self):
        is_open = self.set_section_open.get()

        if is_open:
            self.set_frame.pack_forget()
            self.set_section_open.set(False)
            self.set_toggle_button.configure(text="▶ Add Equipment Set")
        else:
            self.set_frame.pack(fill="x", pady=(6, 0))
            self.set_section_open.set(True)
            self.set_toggle_button.configure(text="▼ Add Equipment Set")

        self.after(20, self._update_shopping_responsive_layout)

    def _on_window_resize(self, event=None):
        if event is not None and event.widget is not self:
            return

        pending = getattr(self, "_shopping_resize_after_id", None)
        if pending:
            try:
                self.after_cancel(pending)
            except Exception:
                pass

        self._shopping_resize_after_id = self.after(
            80,
            self._update_shopping_responsive_layout,
        )

    def _update_shopping_responsive_layout(self):
        self._shopping_resize_after_id = None

        if not hasattr(self, "shop_list_tree"):
            return

        try:
            height = self.winfo_height()
        except tk.TclError:
            return

        if height < 720:
            mode = "very_compact"
            list_rows = 2
        elif height < 860:
            mode = "compact"
            list_rows = 3
        else:
            mode = "normal"
            list_rows = 6

        if mode == self._shopping_compact_mode:
            return

        self._shopping_compact_mode = mode
        self.shop_list_tree.configure(height=list_rows)

        if mode == "normal":
            if not self.shop_intro_label.winfo_manager():
                self.shop_intro_label.pack(
                    anchor="w",
                    pady=(2, 10),
                    before=self.start_frame,
                )

            if (
                self.set_section_open.get()
                and not self.set_hint_label.winfo_manager()
            ):
                self.set_hint_label.grid(
                    row=2,
                    column=0,
                    columnspan=5,
                    sticky="w",
                    pady=(5, 0),
                )

            self.start_frame.configure(padding=(10, 7))
            self.set_frame.configure(padding=(10, 7))
            self.shop_list_frame.configure(padding=8)
        else:
            if self.shop_intro_label.winfo_manager():
                self.shop_intro_label.pack_forget()

            if self.set_hint_label.winfo_manager():
                self.set_hint_label.grid_remove()

            self.start_frame.configure(padding=(8, 3))
            self.set_frame.configure(padding=(8, 3))
            self.shop_list_frame.configure(padding=4)

    def _append_or_increment_shopping_row(self, item, rarity, tier, qty):
        """
        Add an item to the Shopping List, or increase quantity when the exact
        same item/rarity/tier combination already exists.
        """
        for row in self.shopping_rows:
            if (
                row.get("item", "").casefold() == item.casefold()
                and row.get("rarity") == rarity
                and row.get("tier") == tier
            ):
                row["qty"] = int(row.get("qty", 0)) + qty
                return

        self.shopping_rows.append({
            "item": item,
            "rarity": rarity,
            "tier": tier,
            "qty": qty,
        })

    def _on_armor_type_changed(self, _event=None):
        armor_type = self.shop_armor_type_var.get().strip()

        self.shop_set_combo.configure(values=[])
        self.shop_set_var.set("")
        self.shop_set_definitions = {}
        self.shop_status_var.set(f"Loading {armor_type} armor sets from BitJita...")

        threading.Thread(
            target=self._load_armor_sets_worker,
            args=(armor_type,),
            daemon=True,
        ).start()

    def _load_armor_sets_worker(self, armor_type):
        try:
            rows = list(discover_armor_sets(armor_type))
            error = None
        except Exception as exc:
            rows = []
            error = str(exc)

        self.after(
            0,
            lambda: self._apply_armor_sets(armor_type, rows, error),
        )

    def _apply_armor_sets(self, armor_type, rows, error):
        # Ignore stale results if the user changed type while loading.
        if self.shop_armor_type_var.get().strip() != armor_type:
            return

        if error:
            self.shop_status_var.set(f"Could not load {armor_type} armor sets.")
            messagebox.showerror(
                "Set lookup failed",
                f"Could not load {armor_type} armor sets from BitJita.\\n\\n{error}",
            )
            return

        definitions = {}
        names = []

        for display_name, prefix, tier, category in rows:
            # Include tier in duplicate display names if BitJita ever reuses
            # the same prefix at multiple tiers.
            visible = display_name
            if visible in definitions:
                visible = f"{display_name} ({tier})"

            definitions[visible] = {
                "prefix": prefix,
                "tier": tier,
                "category": category,
            }
            names.append(visible)

        self.shop_set_definitions = definitions
        self.shop_set_combo.configure(values=names)

        if names:
            self.shop_set_var.set(names[0])
            self.shop_status_var.set(
                f"Loaded {len(names)} {armor_type} armor set families."
            )
        else:
            self.shop_set_var.set("")
            self.shop_status_var.set(
                f"No {armor_type} armor set families were found."
            )

    def add_shopping_set(self):
        set_name = self.shop_set_var.get().strip()
        definition = self.shop_set_definitions.get(set_name)

        if not definition:
            messagebox.showwarning(
                "Missing information",
                "Select an equipment set.",
            )
            return

        rarity = self.shop_set_rarity_var.get()

        try:
            set_qty = int(self.shop_set_qty_var.get())
        except (ValueError, tk.TclError):
            set_qty = 1

        set_qty = max(1, set_qty)

        prefix = definition["prefix"]
        tier = definition["tier"]
        category = definition["category"]

        self.shop_status_var.set(
            f"Checking {set_name} pieces on BitJita..."
        )

        threading.Thread(
            target=self._add_shopping_set_worker,
            args=(set_name, prefix, tier, category, rarity, set_qty),
            daemon=True,
        ).start()

    def _add_shopping_set_worker(
        self, set_name, prefix, tier, category, rarity, set_qty
    ):
        try:
            pieces = list(discover_armor_set_pieces(prefix, tier, category))
        except Exception as exc:
            self.after(
                0,
                lambda: messagebox.showerror(
                    "Set lookup failed",
                    f"Could not check {set_name} on BitJita.\\n\\n{exc}",
                ),
            )
            self.after(
                0,
                lambda: self.shop_status_var.set("Set lookup failed."),
            )
            return

        self.after(
            0,
            lambda: self._apply_discovered_shopping_set(
                set_name, pieces, tier, rarity, set_qty
            ),
        )

    def _apply_discovered_shopping_set(
        self, set_name, pieces, tier, rarity, set_qty
    ):
        if not pieces:
            messagebox.showwarning(
                "No set pieces found",
                f"No matching {set_name} pieces were found on BitJita.",
            )
            self.shop_status_var.set("No set pieces found.")
            return

        for item_name in pieces:
            self._append_or_increment_shopping_row(
                item=item_name,
                rarity=rarity,
                tier=tier,
                qty=set_qty,
            )

        self._refresh_shopping_list()

        piece_names = [
            name.rsplit(" ", 1)[-1]
            for name in pieces
        ]

        self.shop_status_var.set(
            f"Added {set_qty} × {set_name} ({rarity}): "
            + ", ".join(piece_names)
            + "."
        )

    def add_shopping_item(self):
        item = self.shop_item_var.get().strip()

        if len(item) < 2:
            messagebox.showwarning(
                "Missing information",
                "Enter an item name to add to the Shopping List.",
            )
            return

        rarity = self.shop_rarity_var.get()
        tier = self.shop_tier_var.get()

        try:
            qty = int(self.shop_qty_var.get())
        except (ValueError, tk.TclError):
            qty = 1

        if qty < 1:
            qty = 1

        self._append_or_increment_shopping_row(
            item=item,
            rarity=rarity,
            tier=tier,
            qty=qty,
        )
        self._refresh_shopping_list()

        self.shop_item_var.set("")
        self.shop_qty_var.set(1)
        self.shop_item_combo.focus_set()

    def _show_shopping_list_context_menu(self, event):
        row_id = self.shop_list_tree.identify_row(event.y)
        if not row_id:
            return

        self.shop_list_tree.selection_set(row_id)
        self.shop_list_tree.focus(row_id)

        try:
            self.shop_list_context_menu.tk_popup(
                event.x_root,
                event.y_root,
            )
        finally:
            self.shop_list_context_menu.grab_release()

    def edit_selected_shopping_item(self):
        selection = self.shop_list_tree.selection()
        if not selection:
            return

        try:
            index = int(selection[0])
            row = self.shopping_rows[index]
        except (ValueError, IndexError):
            return

        dialog = tk.Toplevel(self)
        dialog.title("Edit Shopping List Item")
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()

        # Center the edit dialog over the main application window.
        dialog.update_idletasks()
        self.update_idletasks()

        dialog_width = max(dialog.winfo_reqwidth(), 460)
        dialog_height = max(dialog.winfo_reqheight(), 220)

        main_x = self.winfo_rootx()
        main_y = self.winfo_rooty()
        main_width = self.winfo_width()
        main_height = self.winfo_height()

        x = main_x + max(0, (main_width - dialog_width) // 2)
        y = main_y + max(0, (main_height - dialog_height) // 2)

        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Item").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        item_var = tk.StringVar(value=row.get("item", ""))
        item_entry = AutoCompleteCombobox(
            frame,
            textvariable=item_var,
            width=38,
        )
        item_entry.grid(
            row=1, column=0, columnspan=3,
            sticky="ew", pady=(0, 10)
        )

        ttk.Label(frame, text="Rarity").grid(
            row=2, column=0, sticky="w"
        )
        ttk.Label(frame, text="Tier").grid(
            row=2, column=1, sticky="w"
        )
        ttk.Label(frame, text="Quantity").grid(
            row=2, column=2, sticky="w"
        )

        rarity_var = tk.StringVar(value=row.get("rarity") or "Any")
        tier_var = tk.StringVar(value=row.get("tier") or "Any")
        qty_var = tk.IntVar(value=max(1, int(row.get("qty") or 1)))

        ttk.Combobox(
            frame,
            textvariable=rarity_var,
            values=RARITIES,
            state="readonly",
            width=14,
        ).grid(row=3, column=0, padx=(0, 8), sticky="ew")

        ttk.Combobox(
            frame,
            textvariable=tier_var,
            values=TIERS,
            state="readonly",
            width=10,
        ).grid(row=3, column=1, padx=(0, 8), sticky="ew")

        ttk.Spinbox(
            frame,
            from_=1,
            to=999999,
            textvariable=qty_var,
            width=10,
        ).grid(row=3, column=2, sticky="ew")

        buttons = ttk.Frame(frame)
        buttons.grid(
            row=4, column=0, columnspan=3,
            sticky="e", pady=(14, 0)
        )

        def save_edit():
            item = item_var.get().strip()
            if len(item) < 2:
                messagebox.showwarning(
                    "Missing information",
                    "Enter an item name.",
                    parent=dialog,
                )
                return

            try:
                qty = int(qty_var.get())
            except (ValueError, tk.TclError):
                qty = 1

            qty = max(1, qty)

            self.shopping_rows[index] = {
                "item": item,
                "rarity": rarity_var.get(),
                "tier": tier_var.get(),
                "qty": qty,
            }
            self._refresh_shopping_list()
            dialog.destroy()

        ttk.Button(
            buttons,
            text="Cancel",
            command=dialog.destroy,
        ).pack(side="right")

        ttk.Button(
            buttons,
            text="Save",
            command=save_edit,
        ).pack(side="right", padx=(0, 8))

        dialog.bind("<Return>", lambda _e: save_edit())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        item_entry.focus_set()

    def remove_shopping_item(self):
        selection = self.shop_list_tree.selection()
        if not selection:
            return

        try:
            index = int(selection[0])
            del self.shopping_rows[index]
        except (ValueError, IndexError):
            return

        self._refresh_shopping_list()

    def clear_shopping_list(self):
        self.shopping_rows.clear()
        self._refresh_shopping_list()

        for tree in (self.plan_tree, self.buy_plan_tree, self.route_tree):
            for row in tree.get_children():
                tree.delete(row)

        self.buy_order_plan_results = []
        self.shopping_solutions = {}
        self.shopping_solution_context = None
        self.shopping_solution = None
        self.shop_progress.stop()
        self.shop_progress.pack_forget()
        self.shop_summary_var.set("Add items to the list and optimize.")
        self.shop_status_var.set("Ready.")

    def _refresh_shopping_list(self):
        for row in self.shop_list_tree.get_children():
            self.shop_list_tree.delete(row)

        for idx, item in enumerate(self.shopping_rows):
            self.shop_list_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    item["item"],
                    item["rarity"],
                    item["tier"],
                    item["qty"],
                ),
            )

    def start_shopping_optimizer(self):
        if not self.shopping_rows:
            messagebox.showwarning(
                "Shopping List is empty",
                "Add at least one item first.",
            )
            return

        if self.purchase_mode_var.get() == "Plan Buy Orders":
            self._start_buy_order_planning()
            return

        try:
            start = self.get_start_location()
            weight = self.get_distance_weight()
            filter_mode, max_distance = self.get_location_filter()

            resolved_start = resolve_claim_by_name(
                start["claim"],
                start.get("region"),
            )
            if (
                resolved_start
                and resolved_start.get("x") is not None
                and resolved_start.get("z") is not None
            ):
                start = resolved_start
            elif start.get("x") is None or start.get("z") is None:
                raise ValueError(
                    f"Could not resolve starting location '{start['claim']}'. "
                    "Check the Claim and Region selection."
                )
        except ValueError as exc:
            messagebox.showerror("Settings error", str(exc))
            return

        self.optimize_button.config(state="disabled")
        self.purchase_mode_combo.configure(state="disabled")
        self._missing_warning_shown = False
        self.shop_status_var.set("Processing... searching markets for Shopping List...")
        self.shop_summary_var.set("Calculating...")
        if not self.shop_progress.winfo_manager():
            self.shop_progress.pack(fill="x", pady=(4, 0))
        self.shop_progress.start(12)

        for tree in (self.plan_tree, self.buy_plan_tree, self.route_tree):
            for row in tree.get_children():
                tree.delete(row)

        rows = [dict(row) for row in self.shopping_rows]

        threading.Thread(
            target=self._shopping_worker,
            args=(rows, start, weight, filter_mode, max_distance),
            daemon=True,
        ).start()

    def _start_buy_order_planning(self):
        strategy = self.buy_price_strategy_var.get()
        if strategy not in BUY_ORDER_STRATEGIES:
            strategy = "Highest Current Buy Price"
            self.buy_price_strategy_var.set(strategy)

        self._set_purchase_result_mode(True)
        self.optimize_button.config(state="disabled")
        self.purchase_mode_combo.configure(state="disabled")
        self.buy_price_strategy_combo.configure(state="disabled")
        self.shop_status_var.set(
            f"Planning buy orders using {strategy}..."
        )
        self.shop_summary_var.set("Calculating buy order plan...")
        if not self.shop_progress.winfo_manager():
            self.shop_progress.pack(fill="x", pady=(4, 0))
        self.shop_progress.start(12)

        for tree in (self.plan_tree, self.buy_plan_tree, self.route_tree):
            for child in tree.get_children():
                tree.delete(child)

        rows = [dict(row) for row in self.shopping_rows]
        threading.Thread(
            target=self._buy_order_worker,
            args=(rows, strategy),
            daemon=True,
        ).start()

    def _buy_order_worker(self, rows, strategy):
        try:
            results_by_index = {}
            workers = min(MAX_API_WORKERS, max(1, len(rows)))

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(
                        build_buy_order_plan_item,
                        row,
                        strategy,
                    ): (index, row)
                    for index, row in enumerate(rows)
                }

                completed = 0
                for future in as_completed(future_map):
                    index, row = future_map[future]
                    completed += 1
                    self.after(
                        0,
                        lambda done=completed, total=len(rows), name=row["item"]:
                        self.shop_status_var.set(
                            f"Checking buy-order prices ({done}/{total}): {name}"
                        ),
                    )

                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {
                            "item_id": None,
                            "item_name": row.get("item") or "",
                            "required_quantity": int(row.get("qty") or 1),
                            "pricing_strategy": strategy,
                            "suggested_unit_price": None,
                            "estimated_total_cost": None,
                            "data_source": None,
                            "source_period": None,
                            "status": f"Lookup failed: {exc}",
                            "market_type": "item",
                        }
                    results_by_index[index] = result

            results = [
                results_by_index[index]
                for index in sorted(results_by_index)
            ]
            self.after(
                0,
                lambda data=results: self._display_buy_order_plan(data),
            )
        except Exception as exc:
            self.after(
                0,
                lambda msg=str(exc): self._buy_order_error(msg),
            )

    @staticmethod
    def _format_plan_decimal(value):
        if value is None:
            return "-"
        value = Decimal(value)
        if value == value.to_integral():
            return f"{int(value):,}"
        return f"{value:,.2f}".rstrip("0").rstrip(".")

    def _display_buy_order_plan(self, results):
        self.buy_order_plan_results = results
        self.shopping_solution = None
        self.shopping_solutions = {}
        self.shopping_solution_context = None

        self.optimize_button.config(state="normal")
        self.purchase_mode_combo.configure(state="readonly")
        self.shop_progress.stop()
        self.shop_progress.pack_forget()
        self._set_purchase_result_mode(True)

        for child in self.buy_plan_tree.get_children():
            self.buy_plan_tree.delete(child)

        total = Decimal("0")
        ready_count = 0

        for idx, result in enumerate(results):
            price = result.get("suggested_unit_price")
            estimated = result.get("estimated_total_cost")
            if estimated is not None:
                total += Decimal(estimated)
                ready_count += 1

            status = result.get("status") or ""
            source = result.get("source_period")
            if status == "Ready" and result.get("data_source"):
                if source:
                    status = f"Ready — {result['data_source']} ({source})"
                else:
                    status = f"Ready — {result['data_source']}"

            self.buy_plan_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    result.get("item_name") or "",
                    result.get("required_quantity") or 0,
                    result.get("pricing_strategy") or "",
                    self._format_plan_decimal(price),
                    self._format_plan_decimal(estimated),
                    status,
                ),
            )

        missing_count = len(results) - ready_count
        strategy = self.buy_price_strategy_var.get()
        summary = (
            f"Buy Order Plan | {strategy} | "
            f"Estimated total: {self._format_plan_decimal(total)} Hex | "
            f"Ready: {ready_count}"
        )
        if missing_count:
            summary += f" | No data: {missing_count}"
        self.shop_summary_var.set(summary)
        self.shop_status_var.set(
            f"Buy order plan ready: {ready_count}/{len(results)} item(s) have pricing data."
        )

    def _buy_order_error(self, text):
        self.optimize_button.config(state="normal")
        self.purchase_mode_combo.configure(state="readonly")
        self.buy_price_strategy_combo.configure(state="readonly")
        self.shop_progress.stop()
        self.shop_progress.pack_forget()
        self.shop_summary_var.set("Could not create a buy order plan.")
        self.shop_status_var.set("Error / no results.")
        messagebox.showerror("Buy Order Plan", text)

    def _shopping_row_candidates(
        self,
        row,
        start,
        filter_mode,
        max_distance,
    ):
        items = market_search(
            row["item"],
            row["rarity"],
            row["tier"],
            exact_preferred=True,
        )

        if not items:
            return None, {
                "row": row,
                "reason": "No matching item variant was found for the selected rarity/tier.",
            }

        all_orders = fetch_orders_for_items_parallel(items)

        if not all_orders:
            return None, {
                "row": row,
                "reason": "No active sell orders were found.",
            }

        options_before_filter = group_purchase_options(
            all_orders,
            row["qty"],
        )

        if not options_before_filter:
            return None, {
                "row": row,
                "reason": (
                    f"Active sell orders exist, but no single market has "
                    f"enough stock for quantity {row['qty']}."
                ),
            }

        options = apply_location_filter(
            options_before_filter,
            start,
            filter_mode,
            start["region"],
            max_distance,
        )

        if not options:
            return None, {
                "row": row,
                "reason": "No suitable stock was found within the selected area filter.",
            }

        for option in options:
            option["shopping_row"] = row

        options = prune_candidates(options)

        if not options:
            return None, {
                "row": row,
                "reason": "No usable market candidates remained after filtering.",
            }

        return options, None

    def _shopping_worker(
        self,
        rows,
        start,
        weight,
        filter_mode,
        max_distance,
    ):
        try:
            item_candidates_by_index = {}
            missing_by_index = {}

            workers = min(MAX_API_WORKERS, max(1, len(rows)))

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(
                        self._shopping_row_candidates,
                        row,
                        start,
                        filter_mode,
                        max_distance,
                    ): (index, row)
                    for index, row in enumerate(rows)
                }

                completed = 0
                for future in as_completed(future_map):
                    index, row = future_map[future]
                    completed += 1

                    self.after(
                        0,
                        lambda done=completed, total=len(rows), name=row["item"]:
                        self.shop_status_var.set(
                            f"Scanning markets ({done}/{total}): {name}"
                        ),
                    )

                    try:
                        options, missing = future.result()
                    except Exception:
                        options, missing = None, {
                            "row": row,
                            "reason": "Market lookup failed for this item.",
                        }

                    if options:
                        item_candidates_by_index[index] = options
                    elif missing:
                        missing_by_index[index] = missing

            item_candidates = [
                item_candidates_by_index[index]
                for index in sorted(item_candidates_by_index)
            ]
            missing_items = [
                missing_by_index[index]
                for index in sorted(missing_by_index)
            ]

            if not item_candidates:
                details = self._format_missing_items(missing_items)
                self.after(
                    0,
                    lambda d=details: self._shopping_error(
                        "No purchasable items were found for this Shopping List.\n\n" + d
                    ),
                )
                return

            self.after(
                0,
                lambda: self.shop_status_var.set(
                    "Calculating the best market combination and route..."
                ),
            )

            solutions = {
                "Cheapest": choose_shopping_solution(
                    item_candidates, start, "cheapest", weight
                ),
                "Nearest": choose_shopping_solution(
                    item_candidates, start, "nearest", weight
                ),
                "Balanced": choose_shopping_solution(
                    item_candidates, start, "balanced", weight
                ),
            }

            if not any(solutions.values()):
                self.after(
                    0,
                    lambda: self._shopping_error(
                        "No suitable Shopping List solution was found."
                    ),
                )
                return

            self.after(
                0,
                lambda sols=solutions, missing=missing_items:
                self._display_shopping_solutions(
                    sols,
                    start,
                    weight,
                    filter_mode,
                    max_distance,
                    missing,
                ),
            )

        except Exception as exc:
            self.after(
                0,
                lambda: self._shopping_error(str(exc)),
            )

    def _format_missing_items(self, missing_items):
        if not missing_items:
            return ""

        lines = []
        for entry in missing_items:
            row = entry["row"]
            lines.append(
                f"• {row['item']} "
                f"({row['rarity']}, {row['tier']}, quantity {row['qty']}): "
                f"{entry['reason']}"
            )
        return "\n".join(lines)

    def _display_shopping_solutions(
        self,
        solutions,
        start,
        weight,
        filter_mode,
        max_distance,
        missing_items=None,
    ):
        self.shopping_solutions = {k: v for k, v in solutions.items() if v}
        self.shopping_solution_context = (
            start,
            weight,
            filter_mode,
            max_distance,
            missing_items or [],
        )

        preferred = self.shopping_solution_mode_var.get()
        if preferred not in self.shopping_solutions:
            preferred = "Balanced" if "Balanced" in self.shopping_solutions else next(iter(self.shopping_solutions))
            self.shopping_solution_mode_var.set(preferred)

        self._show_selected_shopping_solution()

    def _show_selected_shopping_solution(self):
        if not self.shopping_solutions or not self.shopping_solution_context:
            return
        label = self.shopping_solution_mode_var.get()
        solution = self.shopping_solutions.get(label)
        if not solution:
            return
        start, weight, filter_mode, max_distance, missing_items = (
            self.shopping_solution_context
        )
        self._display_shopping_solution(
            solution,
            start,
            weight,
            filter_mode,
            max_distance,
            plan_label=label,
            missing_items=missing_items,
        )

    def _display_shopping_solution(
        self,
        solution,
        start,
        weight,
        filter_mode,
        max_distance,
        plan_label="Balanced",
        missing_items=None,
    ):
        self._set_purchase_result_mode(False)
        self.shopping_solution = solution
        self.optimize_button.config(state="normal")
        self.purchase_mode_combo.configure(state="readonly")
        self.shop_progress.stop()
        self.shop_progress.pack_forget()

        for tree in (self.plan_tree, self.route_tree):
            for row in tree.get_children():
                tree.delete(row)

        # Satın alma planı
        for idx, choice in enumerate(solution["choices"]):
            sellers_text = ", ".join(
                f"{s['seller']} x{s['qty']} @{s['unit_price']:,.0f}"
                for s in choice["sellers_breakdown"]
            )

            distance_text = (
                "-"
                if choice["distance_from_start"] is None
                else format_distance(choice['distance_from_start'])
            )

            self.plan_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    choice["shopping_row"]["item"],
                    choice["wanted_quantity"],
                    f"{choice['total_cost']:,.0f}",
                    f"{choice['avg_unit_price']:,.1f}",
                    choice["claim"],
                    region_label(choice),
                    distance_text,
                    format_estimated_tp(choice.get("distance_from_start")),
                    sellers_text,
                    choice["item_id"],
                ),
            )

        # Rota
        current = start
        total_est_tp = 0

        for stop_no, loc in enumerate(solution["route"], start=1):
            from_prev = straight_distance(current, loc)
            from_prev_text = format_distance(from_prev)
            leg_tp = estimate_tp(from_prev)
            if leg_tp is not None:
                total_est_tp += leg_tp

            loc_key = location_key(loc)

            bought_here = []
            for choice in solution["choices"]:
                if location_key(choice) == loc_key:
                    bought_here.append(
                        f"{choice['shopping_row']['item']} x{choice['wanted_quantity']}"
                    )

            self.route_tree.insert(
                "",
                "end",
                values=(
                    stop_no,
                    loc["claim"],
                    region_label(loc),
                    from_prev_text,
                    format_estimated_tp(from_prev),
                    ", ".join(bought_here),
                ),
            )

            current = loc

        route_text = (
            "?"
            if solution["route_distance"] is None
            else format_distance(solution['route_distance'])
        )

        if filter_mode == "region":
            filter_text = f"Only {start['region']}"
        elif filter_mode == "distance":
            filter_text = (
                f"From start ≤ {max_distance:.0f}"
                if max_distance is not None else "Maximum distance"
            )
        else:
            filter_text = "Everywhere"

        missing_items = missing_items or []
        missing_count = len(missing_items)

        summary = (
            f"{plan_label} plan | "
            f"Item total: {solution['item_total']:,.0f} Hex | "
            f"Route: {route_text} | "
            f"Est. TP: {total_est_tp} | "
            f"Filter: {filter_text}"
        )
        if missing_count:
            summary += f" | Missing: {missing_count}"

        self.shop_summary_var.set(summary)

        if missing_count:
            self.shop_status_var.set(
                f"Partial plan ready: {len(solution['choices'])} item(s) found, "
                f"{missing_count} item(s) unavailable, "
                f"{len(solution['route'])} market stop(s)."
            )

            if not getattr(self, "_missing_warning_shown", False):
                self._missing_warning_shown = True
                details = self._format_missing_items(missing_items)
                messagebox.showwarning(
                    "Shopping List - Partial Plan",
                    "A plan was created for the available items.\n\n"
                    "The following items could not be included:\n\n"
                    + details,
                )
        else:
            self.shop_status_var.set(
                f"Done. Plan ready: {len(solution['choices'])} item(s), "
                f"{len(solution['route'])} market stop(s). "
                "You can view alternatives from the Plan option menu below."
            )

    def _shopping_error(self, text):
        self.optimize_button.config(state="normal")
        self.purchase_mode_combo.configure(state="readonly")
        self.shop_progress.stop()
        self.shop_progress.pack_forget()
        self.shop_summary_var.set("Could not create a plan.")
        self.shop_status_var.set("Error / no results.")
        messagebox.showerror("Shopping List", text)

    def open_buy_plan_result(self, _event=None):
        selection = self.buy_plan_tree.selection()
        if not selection:
            return

        try:
            result = self.buy_order_plan_results[int(selection[0])]
        except (ValueError, IndexError):
            return

        item_id = result.get("item_id")
        if not item_id:
            return

        market_type = "cargo" if result.get("market_type") == "cargo" else "item"
        webbrowser.open(f"{SITE_URL}/market/{market_type}/{item_id}")

    def open_plan_result(self, _event=None):
        selection = self.plan_tree.selection()
        if not selection or not self.shopping_solution:
            return

        try:
            choice = self.shopping_solution["choices"][int(selection[0])]
        except (ValueError, IndexError):
            return

        webbrowser.open(f"{SITE_URL}/market/item/{choice['item_id']}")


if __name__ == "__main__":
    app = BitJitaMarketAssistant()
    app.mainloop()
