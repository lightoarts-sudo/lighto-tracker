import gzip
import json

import popostock


def test_schema_is_namespaced():
    assert "popostock_instruments" in popostock.SCHEMA_SQL
    assert "popostock_candles" in popostock.SCHEMA_SQL
    assert "popostock_page_views" in popostock.SCHEMA_SQL
    assert "popostock_fund_profiles" in popostock.SCHEMA_SQL
    assert "popostock_fund_holdings" in popostock.SCHEMA_SQL
    assert "popostock_fund_asset_classes" in popostock.SCHEMA_SQL
    assert "PRIMARY KEY (instrument_id, trade_date, timeframe)" in popostock.SCHEMA_SQL
    source = (popostock.BASE_DIR / "popostock.py").read_text(encoding="utf-8")
    assert '"total": int(row["total"] or 0)' in source
    assert '"today": int(row["today"] or 0)' in source


def test_seed_is_readable_and_complete():
    with gzip.open(popostock.SEED_PATH, "rt", encoding="utf-8") as handle:
        seed = json.load(handle)
    assert seed["instrumentCount"] >= 69
    assert seed["candleCount"] >= 120_000
    assert seed["fundProfileCount"] == 9
    assert seed["fundHoldingCount"] == 90
    assert seed["fundAssetClassCount"] == 26
    symbols = {item["symbol"] for item in seed["instruments"]}
    assert {"TAIEX", "VIXTWN", "0050", "00981A", "ALI005"} <= symbols
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
    assert profiles["UNI023"]["name"] == "統一奔騰基金"
    nom156_info = {
        item["label"]: item["value"] for item in profiles["NOM156"]["basicInfo"]
    }
    assert nom156_info["最新淨值資料日"] == "2026-07-22"
    assert len(profiles["CSI002"]["holdings"]) == 10


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
    assert (popostock.SITE_DIR / "data" / "nav" / "ALI006.json").exists()
    assert (popostock.SITE_DIR / "data" / "nav" / "UNI023.json").exists()
    assert 'sessionStorage.getItem(key)' in page
    assert 'fetch("api/page-view"' in page
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
    assert "POC " in asset_text
    assert "instrument-detail-sections" not in asset_text
