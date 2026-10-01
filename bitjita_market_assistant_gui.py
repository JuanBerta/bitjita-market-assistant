#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BitJita Market Assistant - GUI v3.6.9

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
import webbrowser
import json
import os
import re
from urllib.parse import urljoin, urlparse
from collections import defaultdict
from functools import lru_cache
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

def _load_cached_api_url() -> str | None:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return _normalize_base_url(data.get("api_base_url"))
    except Exception:
        return None

def _save_cached_api_url(url: str) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump({"api_base_url": url}, fh, indent=2)
    except Exception:
        # Cache failures must never stop the application.
        pass

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

# BitCraft locationX/locationZ values are Small Hex coordinates.
# Distance must therefore be measured on the hex grid, not with Euclidean
# math.hypot() and an arbitrary scale factor.

session = requests.Session()
session.headers.update({
    "User-Agent": "BitJita-Market-Assistant/3.5.6",
    "Accept": "application/json",
})


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
    return {
        "id": first_value(raw, "id", "itemId"),
        "name": first_value(raw, "name", "itemName") or "",
        "tier": to_number(first_value(raw, "tier", "itemTier")),
        "rarity": first_value(raw, "rarityStr", "itemRarityStr") or "",
        "category": first_value(
            raw,
            "tag", "itemTag", "category", "categoryName"
        ) or "",
        "raw": raw,
    }


@lru_cache(maxsize=2048)
def get_claim(claim_id: str):
    if not claim_id:
        return {}
    try:
        data = api_get(f"/claims/{claim_id}")
        return data.get("claim") or {}
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

    claim_data = get_claim(str(claim_id)) if claim_id else {}

    claim_name = first_value(order, "claimName", "marketName")
    if not claim_name and isinstance(nested_claim, dict):
        claim_name = first_value(nested_claim, "name")
    if not claim_name:
        claim_name = first_value(claim_data, "name") or "?"

    region = first_value(order, "regionName", "region")
    if not region:
        region = first_value(claim_data, "regionName", "region") or "?"

    # Keep the actual BitJita region ID separate from shard/server metadata.
    # Rxx labels are based on regionId, not on shardName/serverName.
    region_id = first_value(order, "regionId", "regionID")
    if region_id in (None, ""):
        region_id = first_value(claim_data, "regionId", "regionID")
    region_id = str(region_id).strip() if region_id not in (None, "") else None

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

    # Distance hesabında marketin bağlı olduğu claim'in koordinatını kullan.
    # Claim endpoint'i burada otoritatif kaynaktır.
    cx, cz = claim_coordinates(claim_data)
    x, z = cx, cz

    # Claim koordinatı alınamazsa order alanlarını yalnız fallback olarak kullan.
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

    return list(unique.values())


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
    """Return all known BitJita regions as labels such as 'Zephyra R19'."""
    found = {}
    page = 1
    limit = 100

    # Claims are paged. Collect unique regionName + regionId pairs.
    while page <= 100:
        data = api_get(
            "/claims",
            params={
                "page": page,
                "limit": limit,
                "sort": "name",
                "order": "asc",
            },
        )

        claims = data.get("claims") or []
        if not claims:
            break

        for claim in claims:
            region = str(first_value(claim, "regionName", "region") or "").strip()
            region_id = first_value(claim, "regionId", "regionID")

            if not region:
                continue

            rid = normalize_region_id(region_id)
            if rid:
                label = f"{region} {rid}"
            else:
                label = region

            found[label.casefold()] = label

        if len(claims) < limit:
            break

        page += 1

    return sorted(found.values(), key=str.casefold)

def resolve_claim_by_name(name, preferred_region=None):
    """Claim adını BitJita API üzerinden çözer ve gerçek koordinatını döndürür."""
    if not name or len(name.strip()) < 2:
        return None

    data = api_get(
        "/claims",
        params={
            "q": name.strip(),
            "page": 1,
            "limit": 100,
            "sort": "name",
            "order": "asc",
        },
    )
    claims = data.get("claims") or []

    exact = [
        c for c in claims
        if str(c.get("name", "")).strip().casefold()
        == name.strip().casefold()
    ]

    if preferred_region:
        same_region = [
            c for c in exact
            if str(c.get("regionName", "")).strip().casefold()
            == preferred_region.strip().casefold()
        ]
        if same_region:
            exact = same_region

    if not exact:
        return None

    claim = exact[0]
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


@lru_cache(maxsize=1024)
def claim_autocomplete_names(query, region_filter=""):
    """
    Return matching Claim labels, paging through the full BitJita /claims list.

    The previous implementation fetched only page 1 (max 100 claims), then
    applied the Region filter locally. That meant many regions showed only a
    handful of claims simply because most of their claims were on later pages.
    """
    query = str(query or "").strip()
    region_filter = str(region_filter or "").strip()

    wanted_region, wanted_rid = parse_region_selection(region_filter)

    labels = []
    seen = set()

    page = 1
    limit = 100

    while True:
        params = {
            "page": page,
            "limit": limit,
            "sort": "name",
            "order": "asc",
        }
        if query:
            params["q"] = query

        data = api_get("/claims", params=params)
        claims = data.get("claims") or []

        for claim in claims:
            if region_filter:
                claim_region = str(claim.get("regionName") or "").strip()
                claim_rid = normalize_region_id(claim.get("regionId"))

                if (
                    wanted_region
                    and claim_region.casefold() != wanted_region.casefold()
                ):
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

        # Stop conditions:
        # 1) Short page means no more results.
        # 2) If API exposes pagination metadata, respect it.
        if len(claims) < limit:
            break

        pagination = data.get("pagination") or {}
        total_pages = (
            pagination.get("totalPages")
            or pagination.get("total_pages")
            or data.get("totalPages")
            or data.get("total_pages")
        )

        if total_pages is not None:
            try:
                if page >= int(total_pages):
                    break
            except (TypeError, ValueError):
                pass

        page += 1

        # Defensive guard in case the API ignores the page parameter.
        if page > 500:
            break

    labels.sort(key=str.casefold)
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
    data = api_get(f"/market/item/{item['id']}")
    raw_orders = data.get("sellOrders") or []

    result = []
    for raw in raw_orders:
        order = normalize_order(raw, item)
        if order["price"] is not None:
            result.append(order)

    return result


# ---------------------------------------------------------------------------
# Distance ve market hesapları
# ---------------------------------------------------------------------------

def _small_hex_to_cube(x, z):
    """
    Convert BitCraft Small Hex offset coordinates to cube coordinates.

    BitJita/API:
        locationX = East / column
        locationZ = North / row

    BitCraft's Small Hex map is a staggered horizontal-row hex grid.
    Using odd-r conversion gives distances that closely match the in-game
    hex-distance display and, importantly, preserves the correct ordering of
    nearby claims.
    """
    col = int(round(float(x)))
    row = int(round(float(z)))

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
        self.shopping_rows = []
        self.shopping_solution = None

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
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.search_tab = ttk.Frame(notebook, padding=12)
        self.shopping_tab = ttk.Frame(notebook, padding=(12, 5, 12, 12))
        self.settings_tab = ttk.Frame(notebook, padding=12)
        self.about_tab = ttk.Frame(notebook, padding=28)

        notebook.add(self.shopping_tab, text="Shopping List")
        notebook.add(self.search_tab, text="Item Search")
        notebook.add(self.settings_tab, text="Location / Optimization")
        notebook.add(self.about_tab, text="About")

        self._build_settings_tab()
        self._build_search_tab()
        self._build_shopping_tab()
        self._build_about_tab()

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

    def _build_settings_tab(self):
        ttk.Label(
            self.settings_tab,
            text="Starting Locations",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 12))

        ttk.Label(self.settings_tab, text="Use").grid(row=1, column=0, sticky="w")
        ttk.Label(self.settings_tab, text="Claim").grid(row=1, column=1, sticky="w")
        ttk.Label(self.settings_tab, text="Region").grid(row=1, column=2, sticky="w")

        self.active_start_location_var = tk.IntVar(value=0)
        self.start_location_vars = []
        self.start_location_label_vars = []
        self.start_claim_combos = []
        self.start_region_combos = []

        defaults = [
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
                "data are loaded automatically from BitJita. Distances are calculated on the "
                "BitCraft Small Hex grid."
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
        self.search_sort_var = tk.StringVar(value="Price")
        ttk.Combobox(
            form,
            textvariable=self.search_sort_var,
            values=["Price", "Distance", "Price + Distance"],
            state="readonly",
            width=17,
        ).grid(row=1, column=5, padx=(0, 8))

        self.search_button = ttk.Button(
            form,
            text="Search",
            command=self._search_button_action,
        )
        self.search_button.grid(row=1, column=6)

        form.columnconfigure(0, weight=1)

        self.search_item_combo.bind(
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
            "price", "distance", "item", "tier", "rarity",
            "quantity", "claim", "region", "seller", "id"
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
                anchor="e" if col in {"price", "distance", "tier", "quantity"} else "w",
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

            orders = []
            for item in items:
                if not self._search_job_is_current(job_id):
                    return

                try:
                    orders.extend(fetch_orders_for_item(item))
                except Exception:
                    continue

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
                orders.sort(
                    key=lambda x: (
                        x["price"]
                        + weight * (
                            x["distance_from_start"]
                            if x["distance_from_start"] is not None
                            else 10**9
                        )
                    )
                )

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
        self.search_results = orders
        self.search_button.config(text="Search", state="normal")

        if not orders:
            region = self.search_region_var.get().strip() or "Any"
            if region != "Any":
                self.search_best_var.set(f"No active sell orders found in {region}.")
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

        coord_text = (
            "coordinates ?"
            if best.get("x") is None or best.get("z") is None
            else f"N {best['z']:.0f}, E {best['x']:.0f}"
        )

        self.search_best_var.set(
            f"Top result: {best['price']:,.0f} Hex | "
            f"{best['claim']} / "
            f"{region_label(best)} | "
            f"{dist} | {coord_text}"
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
                    distance,
                    row["item"],
                    f"T{int(row['tier'])}" if row.get("tier") else "?",
                    row["rarity"],
                    row["quantity"],
                    row["claim"],
                    region_label(row),
                    row["seller"],
                    row["item_id"],
                ),
            )

    def _sort_search_results_by_column(self, column):
        if not self.search_results:
            return

        reverse = (
            self.search_sort_column == column
            and not self.search_sort_reverse
        )
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
            self.shop_list_tree.column(col, width=width)

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

        self.result_notebook.add(plan_frame, text="Purchase Plan")
        self.result_notebook.add(route_frame, text="Route")

        # Purchase plan tree
        plan_columns = (
            "item", "qty", "cost", "unit", "claim",
            "region", "distance", "seller", "id"
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
            ("seller", "Seller(s)", 190),
            ("id", "Item ID", 110),
        ]

        for col, title, width in plan_defs:
            self.plan_tree.heading(col, text=title)
            self.plan_tree.column(col, width=width)

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

        self.plan_tree.configure(
            yscrollcommand=p_y.set,
            xscrollcommand=p_x.set,
        )

        self.plan_tree.grid(row=0, column=0, sticky="nsew")
        p_y.grid(row=0, column=1, sticky="ns")
        p_x.grid(row=1, column=0, sticky="ew")
        plan_frame.rowconfigure(0, weight=1)
        plan_frame.columnconfigure(0, weight=1)

        self.plan_tree.bind("<Double-1>", self.open_plan_result)

        # Route tree
        route_columns = ("stop", "claim", "region", "from_prev", "items")
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

        for tree in (self.plan_tree, self.route_tree):
            for row in tree.get_children():
                tree.delete(row)

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
                    "Check the claim/region name or enter X and Z manually."
                )
        except ValueError as exc:
            messagebox.showerror("Settings error", str(exc))
            return

        self.optimize_button.config(state="disabled")
        self._missing_warning_shown = False
        self.shop_status_var.set("Processing... searching markets for Shopping List...")
        self.shop_summary_var.set("Calculating...")
        if not self.shop_progress.winfo_manager():
            self.shop_progress.pack(fill="x", pady=(4, 0))
        self.shop_progress.start(12)

        for tree in (self.plan_tree, self.route_tree):
            for row in tree.get_children():
                tree.delete(row)

        rows = [dict(row) for row in self.shopping_rows]

        threading.Thread(
            target=self._shopping_worker,
            args=(rows, start, weight, filter_mode, max_distance),
            daemon=True,
        ).start()

    def _shopping_worker(
        self,
        rows,
        start,
        weight,
        filter_mode,
        max_distance,
    ):
        try:
            item_candidates = []
            missing_items = []

            for index, row in enumerate(rows, start=1):
                self.after(
                    0,
                    lambda i=index, total=len(rows), name=row["item"]:
                    self.shop_status_var.set(
                        f"Scanning markets ({i}/{total}): {name}"
                    ),
                )

                items = market_search(
                    row["item"],
                    row["rarity"],
                    row["tier"],
                    exact_preferred=True,
                )

                if not items:
                    missing_items.append({
                        "row": row,
                        "reason": "No matching item variant was found for the selected rarity/tier.",
                    })
                    continue

                all_orders = []
                for item in items:
                    try:
                        all_orders.extend(fetch_orders_for_item(item))
                    except Exception:
                        continue

                if not all_orders:
                    missing_items.append({
                        "row": row,
                        "reason": "No active sell orders were found.",
                    })
                    continue

                options_before_filter = group_purchase_options(
                    all_orders,
                    row["qty"],
                )

                if not options_before_filter:
                    missing_items.append({
                        "row": row,
                        "reason": (
                            f"Active sell orders exist, but no single market has "
                            f"enough stock for quantity {row['qty']}."
                        ),
                    })
                    continue

                options = apply_location_filter(
                    options_before_filter,
                    start,
                    filter_mode,
                    start["region"],
                    max_distance,
                )

                if not options:
                    missing_items.append({
                        "row": row,
                        "reason": "No suitable stock was found within the selected area filter.",
                    })
                    continue

                for option in options:
                    option["shopping_row"] = row

                options = prune_candidates(options)

                if not options:
                    missing_items.append({
                        "row": row,
                        "reason": "No usable market candidates remained after filtering.",
                    })
                    continue

                item_candidates.append(options)

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
        self.shopping_solution = solution
        self.optimize_button.config(state="normal")
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
                    sellers_text,
                    choice["item_id"],
                ),
            )

        # Rota
        current = start

        for stop_no, loc in enumerate(solution["route"], start=1):
            from_prev = straight_distance(current, loc)
            from_prev_text = "-" if from_prev is None else f"{from_prev:.0f}"

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
        self.shop_progress.stop()
        self.shop_progress.pack_forget()
        self.shop_summary_var.set("Could not create a plan.")
        self.shop_status_var.set("Error / no results.")
        messagebox.showerror("Shopping List", text)

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
