import gzip
import json
import re

import popostock


def test_schema_is_namespaced():
    assert "popostock_instruments" in popostock.SCHEMA_SQL
    assert "popostock_candles" in popostock.SCHEMA_SQL
    assert "popostock_page_views" in popostock.SCHEMA_SQL
    assert "popostock_fund_profiles" in popostock.SCHEMA_SQL
    assert "popostock_fund_holdings" in popostock.SCHEMA_SQL
    assert "popostock_fund_asset_classes" in popostock.SCHEMA_SQL
    assert "popostock_tracker_items" in popostock.SCHEMA_SQL
    assert "popostock_tracker_holdings" in popostock.SCHEMA_SQL
    assert "popostock_tracker_metadata" in popostock.SCHEMA_SQL
    assert "PRIMARY KEY (instrument_id, trade_date, timeframe)" in popostock.SCHEMA_SQL
    source = (popostock.BASE_DIR / "popostock.py").read_text(encoding="utf-8")
    assert '"total": int(row["total"] or 0)' in source
    assert '"today": int(row["today"] or 0)' in source
    assert '@app.get("/popostock/api/tracker")' in source


def test_seed_is_readable_and_complete():
    with gzip.open(popostock.SEED_PATH, "rt", encoding="utf-8") as handle:
        seed = json.load(handle)
    assert seed["instrumentCount"] >= 69
    assert seed["candleCount"] >= 120_000
    assert seed["fundProfileCount"] == 23
    assert seed["fundHoldingCount"] == 265
    assert seed["fundAssetClassCount"] == 57
    assert seed["trackerItemCount"] == 76
    assert seed["trackerHoldingCount"] == 2943
    assert seed["trackerReferenceCount"] == 123
    symbols = {item["symbol"] for item in seed["instruments"]}
    assert {"TAIEX", "VIXTWN", "SPY", "QQQ", "SMH", "0050", "00981A", "ALI005"} <= symbols
    assert {
        "UNI023",
        "NOM156",
        "NOM015",
        "YUI089",
        "CSI097",
        "NBG061",
        "UNI026",
        "CSI002",
        "UNI002",
    } <= symbols
    profiles = {item["code"]: item for item in seed["fundProfiles"]}
    assert len(profiles) == 23
    assert profiles["ALI005"]["name"] == "安聯台灣大壩基金-A類型"
    assert profiles["UNI023"]["name"] == "統一奔騰基金"
    nom156_info = {
        item["label"]: item["value"] for item in profiles["NOM156"]["basicInfo"]
    }
    assert nom156_info["最新淨值資料日"] == "2026-07-24"
    assert len(profiles["CSI002"]["holdings"]) == 10
    group_counts = {}
    for item in seed["trackerItems"]:
        group_counts[item["group"]] = group_counts.get(item["group"], 0) + 1
    assert group_counts == {"funds": 23, "activeEtfs": 28, "passiveEtfs": 25}


def test_page_contains_full_fund_tracker():
    page = (popostock.SITE_DIR / "index.html").read_text(encoding="utf-8")
    asset_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (popostock.SITE_DIR / "assets").iterdir()
        if path.suffix in {".js", ".css"}
    )
    assert '<base href="/popostock/"' in page
    assert "PoPoStock｜波波流" in page
    assert 'href="favicon.png"' in page
    assert (popostock.SITE_DIR / "favicon.png").exists()
    assert (popostock.SITE_DIR / "bobo-flow-logo.png").exists()
    assert (popostock.SITE_DIR / "data" / "market" / "TAIEX.json").exists()
    assert (popostock.SITE_DIR / "data" / "market" / "SPY.json").exists()
    assert (popostock.SITE_DIR / "data" / "market" / "QQQ.json").exists()
    assert (popostock.SITE_DIR / "data" / "market" / "SMH.json").exists()
    assert (popostock.SITE_DIR / "data" / "nav" / "ALI006.json").exists()
    assert (popostock.SITE_DIR / "data" / "nav" / "UNI023.json").exists()
    assert 'sessionStorage.getItem(key)' in page
    assert 'fetch("api/page-view"' in page
    assert 'fetch("api/tracker"' in page
    assert "__POPOSTOCK_TRACKER_DATA__" in page
    assert "window.__POPOSTOCK_TRACKER_DATA__?.items" in asset_text
    assert "https://www.googletagmanager.com/gtag/js?id=G-TFK1BMB9LT" in page
    assert 'gtag("config", "G-TFK1BMB9LT")' in page
    assert "basic-info-list" in asset_text
    assert ".basic-info-disclosure" in asset_text
    assert "歷史淨值走勢" in asset_text
    assert "每日持股異動" in asset_text
    assert "統一奔騰基金" in asset_text
    assert "野村優質基金-TISA類型" in asset_text
    assert "consensus-streak" in asset_text
    assert "🔥 " in asset_text
    assert "consensus-sources" in asset_text
    assert "查看 " in asset_text
    assert "vrvp-toggle" in asset_text
    assert "vrvp-overlay" in asset_text
    assert "left:12px" in asset_text
    assert "justify-content:flex-start" in asset_text
    assert "POC " in asset_text
    assert "instrument-detail-sections" not in asset_text
    assert "brand-home-link" in asset_text
    assert "https://lighto-tracker.onrender.com/popostock" in asset_text
    assert "美股大盤" in asset_text
    assert "etfCode:`SPY`" in asset_text
    assert "etfCode:`QQQ`" in asset_text
    assert "etfCode:`SMH`" in asset_text


def test_consensus_bundle_matches_latest_published_data():
    consensus = json.loads(
        (popostock.SITE_DIR / "data" / "consensus-history.json").read_text(
            encoding="utf-8"
        )
    )
    script = next(
        path.read_text(encoding="utf-8")
        for path in (popostock.SITE_DIR / "assets").glob("index-*.js")
        if "單日共識加碼" in path.read_text(encoding="utf-8")
    )
    match = re.search(
        r"var [A-Za-z_$][\w$]*=JSON\.parse\((\"(?:\\.|[^\"\\])*\")\),"
        r"[A-Za-z_$][\w$]*=[A-Za-z_$][\w$]*;function",
        script,
    )
    assert match is not None
    bundled = json.loads(json.loads(match.group(1)))
    latest_date = consensus["availableDates"][0]
    assert bundled["availableDates"][0] == latest_date
    assert bundled["daily"][latest_date] == consensus["daily"][latest_date]


def test_nav_reports_and_passive_bundle_match_latest_published_data():
    passive = json.loads(
        (popostock.SITE_DIR / "data" / "passive-etf-latest.json").read_text(
            encoding="utf-8"
        )
    )
    funds = json.loads(
        (popostock.SITE_DIR / "data" / "fund-nav-latest.json").read_text(
            encoding="utf-8"
        )
    )
    script = next(
        path.read_text(encoding="utf-8")
        for path in (popostock.SITE_DIR / "assets").glob("index-*.js")
        if "臺灣證券交易所 ETF e添富每日盤後淨值" in path.read_text(
            encoding="utf-8"
        )
    )
    embedded = None
    for match in re.finditer(r"JSON\.parse\((\"(?:\\.|[^\"\\])*\")\)", script):
        candidate = json.loads(json.loads(match.group(1)))
        if (
            isinstance(candidate, dict)
            and candidate.get("sourceTitle")
            == "臺灣證券交易所 ETF e添富每日盤後淨值"
        ):
            embedded = candidate
            break

    assert embedded is not None
    assert embedded["expectedDate"] == passive["expectedDate"]
    assert embedded["snapshots"] == passive["snapshots"]
    assert embedded["missing"] == passive["missing"]
    assert all(
        snapshot["sourceDate"] == passive["expectedDate"]
        for snapshot in passive["snapshots"].values()
    )
    assert all(
        (popostock.SITE_DIR / "data" / "nav" / f"{code}.json").exists()
        for code in funds["funds"]
    )
