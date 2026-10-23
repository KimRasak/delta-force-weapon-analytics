#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-Click Live Data Crawler & Updater for Delta Force Weapon & Parts Analytics
==============================================================================
Sources crawled in real time:
  1. https://dfttk.com/data/v3/manifest.json
     - catalog/weapons.json (All weapons base combat summaries)
     - catalog/ammo.json (All 114 ammo items)
     - combat/defense/ammo-interactions.json, armors.json, helmets.json
     - library/sol.json (All 577 parts & SDK operations/hidden multipliers)
     - locales/zh-CN/items.json, tune.json, common.json
     - economy/market-prices.json (Daily synced auction house prices via orzice-work-api)
     - packs/combat/weapons/{weaponId}.json (All 68 weapon SDK combat runtime packs & tuning curves)
  2. https://orzice.com/v/ammo?a=ammo&top=2-2&p={1..9}&grade=-1&n=
     - Real-time SSR HTML scraping of live auction house ammo prices (including .300BLK, 12.7x55mm, season ammo)

Usage:
  python3 scripts/fetch_live_data.py [--skip-combat-packs]
"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw_cache"
V3_DIR = RAW_DIR / "dfttk_v3"
COMBAT_PACKS_DIR = V3_DIR / "combat_weapons"

DFTTK_BASE = "https://dfttk.com/data/v3"
ORZICE_AMMO_URL = "https://orzice.com/v/ammo?a=ammo&top=2-2&p={page}&grade=-1&n="
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
}


def fetch_bytes(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_json_to_file(url: str, dst: Path) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    raw = fetch_bytes(url)
    data = json.loads(raw.decode("utf-8-sig"))
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def scrape_orzice_live_ammo(max_pages: int = 9) -> list:
    """
    Scrape real-time auction house ammo prices directly from orzice.com SSR HTML pages.
    """
    row_pattern = re.compile(
        r'<div class="ui-tname">\s*([^<]+?)\s*</div>.*?'
        r'<div class="ui-cell-gold">\s*<span class="icon-gold ui-num">\s*([0-9,]+)\s*</span>',
        re.S,
    )
    results = []
    seen = set()

    def fetch_page(p: int):
        url = ORZICE_AMMO_URL.format(page=p)
        try:
            html = fetch_bytes(url, timeout=15).decode("utf-8", errors="ignore")
            return row_pattern.findall(html)
        except Exception as e:
            print(f"  [warn] Failed to scrape orzice ammo page {p}: {e}")
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        pages_matches = list(ex.map(fetch_page, range(1, max_pages + 1)))

    for matches in pages_matches:
        for name_raw, price_raw in matches:
            nm = name_raw.strip().replace("\xa0", " ")
            pr = int(price_raw.replace(",", "").strip())
            if nm not in seen and pr > 0:
                seen.add(nm)
                results.append({"name": nm, "price": pr, "source": "orzice_live_ssr"})

    return results


def main():
    parser = argparse.ArgumentParser(description="Fetch live Delta Force weapon, part, and market price data.")
    parser.add_argument("--skip-combat-packs", action="store_true", help="Skip re-downloading 68 weapon combat packs if cached.")
    args = parser.parse_args()

    V3_DIR.mkdir(parents=True, exist_ok=True)
    COMBAT_PACKS_DIR.mkdir(parents=True, exist_ok=True)

    print("1. Fetching dfttk.com v3 manifest...")
    manifest = fetch_json_to_file(f"{DFTTK_BASE}/manifest.json", V3_DIR / "manifest.json")
    print(f"   -> Manifest dataVersion: {manifest.get('dataVersion')}")

    core_files = [
        ("catalog/weapons.json", V3_DIR / "catalog_weapons.json"),
        ("catalog/ammo.json", V3_DIR / "catalog_ammo.json"),
        ("combat/defense/ammo-interactions.json", V3_DIR / "combat_defense_ammo-interactions.json"),
        ("combat/defense/armors.json", V3_DIR / "combat_defense_armors.json"),
        ("combat/defense/helmets.json", V3_DIR / "combat_defense_helmets.json"),
        ("library/sol.json", V3_DIR / "library_sol.json"),
        ("economy/market-prices.json", V3_DIR / "economy_market-prices.json"),
        ("locales/zh-CN/items.json", V3_DIR / "locales_zh-CN_items.json"),
        ("locales/zh-CN/tune.json", V3_DIR / "locales_zh-CN_tune.json"),
        ("locales/zh-CN/common.json", V3_DIR / "locales_zh-CN_common.json"),
    ]

    print("2. Fetching core catalogs, 577 parts library, and real-time market prices...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futures = {
            ex.submit(fetch_json_to_file, f"{DFTTK_BASE}/{rel}", dst): rel
            for rel, dst in core_files
        }
        for fut in concurrent.futures.as_completed(futures):
            rel = futures[fut]
            data = fut.result()
            if rel == "economy/market-prices.json":
                print(f"   -> Economy market-prices.json priceVersion: {data.get('priceVersion')} ({len(data.get('prices', {}))} items)")

    weapon_packs = manifest.get("weaponPacks", {})
    print(f"3. Fetching {len(weapon_packs)} weapon combat runtime packs (packs/combat/weapons/*.json)...")
    pack_tasks = []
    for wid, pinfo in weapon_packs.items():
        rel = pinfo.get("combat")
        dst = COMBAT_PACKS_DIR / f"{wid}.json"
        if args.skip_combat_packs and dst.exists() and dst.stat().st_size > 100:
            continue
        pack_tasks.append((f"{DFTTK_BASE}/{rel}", dst))

    if pack_tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
            list(ex.map(lambda t: fetch_json_to_file(t[0], t[1]), pack_tasks))
    print(f"   -> Ready ({len(weapon_packs)} weapon combat runtime packs).")

    print("4. Scraping real-time ammo prices from orzice.com/v/ammo (pages 1..9)...")
    orzice_live_ammo = scrape_orzice_live_ammo(9)
    with open(RAW_DIR / "orzice_live_ammo.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "scrapedAt": datetime.now(timezone.utc).isoformat(),
                "count": len(orzice_live_ammo),
                "items": orzice_live_ammo,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"   -> Scraped {len(orzice_live_ammo)} live ammo prices from orzice.com.")

    print("5. Rebuilding all structured CSV/JSON datasets and Markdown reports...")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_datasets_and_analyze.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_docs.py")], check=True)
    print("Done! All datasets and reports are up to date.")


if __name__ == "__main__":
    main()
