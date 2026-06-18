import asyncio
import json
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import asyncpg
import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from top10_overview import TOP10_STRATEGY_OVERVIEW_HTML, top10_strategy_overview_payload


OKX_BASE = os.environ.get("CRYPTO_OKX_BASE", "https://www.okx.com").rstrip("/")
TW_TZ = timezone(timedelta(hours=8))


def _symbols():
    raw = os.environ.get("CRYPTO_SYMBOLS", os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT"))
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _csv_env(name, default):
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]



_DEFAULT_MICRO_ACTIVE = (
    "auto_top1_4h_d3_r3_chg3-10_green_uw1.2_vol10dur1040_sl1.2_be0.6_tr0.9x0.4_t8",
    "auto_top2_4h_d3_r3_chg3-10_green_uw1.2_vol10dur1040_sl0.8_be0.6_tr0.9x0.4_t8",
    "auto_top3_4h_d3_r3_chg3-10_green_uw1.2_vol10dur1040_sl1.0_be0.6_tr0.9x0.4_t8",
    "strategy20_6h12h_cool_vwap_reclaim",
    "strategy4_1_breakout_confirmation",
)


CONFIG = {
    "symbols": _symbols(),
    "dataSource": "OKX",
    "interval": os.environ.get("CRYPTO_INTERVAL", "5m"),
    "higherInterval": os.environ.get("CRYPTO_HIGHER_INTERVAL", "15m"),
    "pollSeconds": int(os.environ.get("CRYPTO_POLL_SECONDS", "300")),
    "startingCash": float(os.environ.get("CRYPTO_STARTING_CASH", "1000")),
    "orderQuoteSize": float(os.environ.get("CRYPTO_ORDER_QUOTE_SIZE", "50")),
    "takeProfitPct": float(os.environ.get("CRYPTO_TAKE_PROFIT_PCT", "1.2")),
    "stopLossPct": float(os.environ.get("CRYPTO_STOP_LOSS_PCT", "0.6")),
    "maxEntriesPerDay": int(os.environ.get("CRYPTO_MAX_ENTRIES_PER_DAY", "2")),
    "cooldownMinutes": int(os.environ.get("CRYPTO_COOLDOWN_MINUTES", "120")),
    "microPollSeconds": int(os.environ.get("CRYPTO_MICRO_POLL_SECONDS", "300")),
    "microMarginUSDT": float(os.environ.get("CRYPTO_MICRO_MARGIN_USDT", "10")),
    "microLeverage": float(os.environ.get("CRYPTO_MICRO_LEVERAGE", "5")),
    "microStrategySince": os.environ.get("CRYPTO_MICRO_STRATEGY_SINCE", "2026-05-15T13:58:21+00:00"),
    "microMaxPositions": int(os.environ.get("CRYPTO_MICRO_MAX_POSITIONS", "8")),
    "microScanLimit": int(os.environ.get("CRYPTO_MICRO_SCAN_LIMIT", "240")),
    "microMinQuoteVolume24h": float(os.environ.get("CRYPTO_MICRO_MIN_QUOTE_VOLUME_24H", "0")),
    "microMaxQuoteVolume24h": float(os.environ.get("CRYPTO_MICRO_MAX_QUOTE_VOLUME_24H", "1000000000000")),
    "microMinVolumeRatio": float(os.environ.get("CRYPTO_MICRO_MIN_VOLUME_RATIO", "3")),
    "microMinBreakoutPct5m": float(os.environ.get("CRYPTO_MICRO_MIN_BREAKOUT_PCT_5M", "2")),
    "microMinBreakoutPct15m": float(os.environ.get("CRYPTO_MICRO_MIN_BREAKOUT_PCT_15M", "3")),
    "microInstType": os.environ.get("CRYPTO_MICRO_INST_TYPE", "SWAP").upper(),
    "microTrendVolumeRatio": float(os.environ.get("CRYPTO_MICRO_TREND_VOLUME_RATIO", "1.35")),
    "microEarlyVolumeRatio": float(os.environ.get("CRYPTO_MICRO_EARLY_VOLUME_RATIO", "1.12")),
    "microEntryMinVolumeRatio": float(os.environ.get("CRYPTO_MICRO_ENTRY_MIN_VOLUME_RATIO", "2.0")),
    "microEntryMaxVolumeRatio": float(os.environ.get("CRYPTO_MICRO_ENTRY_MAX_VOLUME_RATIO", "8.0")),
    "microTrendMinPct1h": float(os.environ.get("CRYPTO_MICRO_TREND_MIN_PCT_1H", "0.8")),
    "microTrendMinPct15m": float(os.environ.get("CRYPTO_MICRO_TREND_MIN_PCT_15M", "0.2")),
    "microEntryMaxPct15m": float(os.environ.get("CRYPTO_MICRO_ENTRY_MAX_PCT_15M", "1.8")),
    "microNoChasePct1h": float(os.environ.get("CRYPTO_MICRO_NO_CHASE_PCT_1H", "3")),
    "microNoChaseRangePct": float(os.environ.get("CRYPTO_MICRO_NO_CHASE_RANGE_PCT", "3")),
    "microEntryMaxRangePct": float(os.environ.get("CRYPTO_MICRO_ENTRY_MAX_RANGE_PCT", "4.5")),
    "microTrendMaxPct1h": float(os.environ.get("CRYPTO_MICRO_TREND_MAX_PCT_1H", "8")),
    "microTrendMaxPct15m": float(os.environ.get("CRYPTO_MICRO_TREND_MAX_PCT_15M", "4")),
    "microMaxDistanceMa60Pct": float(os.environ.get("CRYPTO_MICRO_MAX_DISTANCE_MA60_PCT", "3")),
    "microConfirmBreakoutBufferPct": float(os.environ.get("CRYPTO_MICRO_CONFIRM_BREAKOUT_BUFFER_PCT", "0.1")),
    "microStopLossPct": float(os.environ.get("CRYPTO_MICRO_STOP_LOSS_PCT", "1.0")),
    "microTakeProfit1Pct": float(os.environ.get("CRYPTO_MICRO_TAKE_PROFIT_1_PCT", "1.2")),
    "microTakeProfit2Pct": float(os.environ.get("CRYPTO_MICRO_TAKE_PROFIT_2_PCT", "2.5")),
    "microBreakevenLockPct": float(os.environ.get("CRYPTO_MICRO_BREAKEVEN_LOCK_PCT", "0.2")),
    "microTrailingStartPct": float(os.environ.get("CRYPTO_MICRO_TRAILING_START_PCT", "1.8")),
    "microTrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_TRAILING_GIVEBACK_PCT", "0.8")),
    "microEarlyExitPct15m": float(os.environ.get("CRYPTO_MICRO_EARLY_EXIT_PCT_15M", "-0.3")),
    "microInterval": os.environ.get("CRYPTO_MICRO_INTERVAL", "5m"),
    "microBaseInterval": os.environ.get("CRYPTO_MICRO_BASE_INTERVAL", "5m"),
    "microSurgeArchiveTopN": int(os.environ.get("CRYPTO_MICRO_SURGE_ARCHIVE_TOP_N", "10")),
    "microSurgeArchiveHours": int(os.environ.get("CRYPTO_MICRO_SURGE_ARCHIVE_HOURS", "4")),
    "microStrategy2TopN": int(os.environ.get("CRYPTO_MICRO_STRATEGY2_TOP_N", "5")),
    "microStrategy2MinPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_MIN_PCT_1H", "3.0")),
    "microStrategy2MaxPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_MAX_PCT_1H", "25.0")),
    "microStrategy2MinPct15m": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_MIN_PCT_15M", "0.2")),
    "microStrategy2MinVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_MIN_VOLUME_RATIO", "1.0")),
    "microStrategy2MaxVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_MAX_VOLUME_RATIO", "60.0")),
    "microStrategy2StopLossPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_STOP_LOSS_PCT", "1.0")),
    "microStrategy2NoFollowMinutes": int(os.environ.get("CRYPTO_MICRO_STRATEGY2_NO_FOLLOW_MINUTES", "15")),
    "microStrategy2NoFollowMinGainPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_NO_FOLLOW_MIN_GAIN_PCT", "1.2")),
    "microStrategy2TrailingStartPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_TRAILING_START_PCT", "2.0")),
    "microStrategy2TrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_TRAILING_GIVEBACK_PCT", "1.0")),
        "microActiveStrategies": _csv_env("CRYPTO_MICRO_ACTIVE_STRATEGIES", "strategy4_1_breakout_confirmation,strategy20_6h12h_cool_vwap_reclaim,top5dplus_score95_chg2_5_sl1_tr06x03_t6,auto_top1_4h_d3_r3_chg3-10_greenuw1.2_vol10_dur1040_sl1.2_be0.6_tr0.9x0.4_t8,auto_top2_4h_d3_r3_chg3-10_greenuw1.2_vol10_dur1040_sl1.0_be0.6_tr0.9x0.4_t8,auto_top3_4h_d3_r3_chg3-10_greenuw1.2_vol10_dur1040_sl0.8_be0.6_tr0.9x0.4_t8"),
    "microStrategy4BreakVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_BREAK_VOLUME_RATIO", "1.4")),
    "microStrategy4HoldFactor": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_HOLD_FACTOR", "1.0")),
    "microStrategy4ConfirmGainPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_CONFIRM_GAIN_PCT", "0.2")),
    "microStrategy4ConfirmVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_CONFIRM_VOLUME_RATIO", "1.1")),
    "microStrategy4MinPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_MIN_PCT_1H", "0.4")),
    "microStrategy4StopLossPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_STOP_LOSS_PCT", "0.8")),
    "microStrategy4TakeProfit1Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_TAKE_PROFIT_1_PCT", "0.8")),
    "microStrategy4TakeProfit2Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_TAKE_PROFIT_2_PCT", "2.4")),
    "microStrategy4BreakevenLockPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_BREAKEVEN_LOCK_PCT", "0.2")),
    "microStrategy4TrailingStartPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_TRAILING_START_PCT", "1.6")),
    "microStrategy4TrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_TRAILING_GIVEBACK_PCT", "0.6")),
    "microStrategy4TimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY4_TIME_STOP_BARS", "8")),
    "microStrategy21SurgeTopN": int(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_TOP_N", "12")),
    "microStrategy21SurgeMinPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_MIN_PCT_1H", "1.2")),
    "microStrategy21SurgeMaxPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_MAX_PCT_1H", "4.8")),
    "microStrategy21SurgeMinPct15m": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_MIN_PCT_15M", "0.1")),
    "microStrategy21SurgeMaxPct15m": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_MAX_PCT_15M", "1.4")),
    "microStrategy21SurgeMinVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_MIN_VOLUME_RATIO", "0.8")),
    "microStrategy21SurgeMaxVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_MAX_VOLUME_RATIO", "4.5")),
    "microStrategy21SurgeMaxDistanceMa60Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_MAX_DISTANCE_MA60_PCT", "2.8")),
    "microStrategy21SurgeMaxSpreadPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_MAX_SPREAD_PCT", "0.35")),
    "microStrategy21SurgeStopLossPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_STOP_LOSS_PCT", "0.7")),
    "microStrategy21SurgeNoFollowMinutes": int(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_NO_FOLLOW_MINUTES", "10")),
    "microStrategy21SurgeNoFollowMinGainPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_NO_FOLLOW_MIN_GAIN_PCT", "0.6")),
    "microStrategy21SurgeTrailingStartPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_TRAILING_START_PCT", "1.4")),
    "microStrategy21SurgeTrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY2_1_TRAILING_GIVEBACK_PCT", "0.55")),
    "microStrategy41MaxPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_1_MAX_PCT_1H", "4.0")),
    "microStrategy41MaxPct15m": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_1_MAX_PCT_15M", "1.6")),
    "microStrategy41MaxVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_1_MAX_VOLUME_RATIO", "5.0")),
    "microStrategy41MaxUpperWickRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_1_MAX_UPPER_WICK_RATIO", "0.45")),
    "microStrategy41MaxBreakoutStretchPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_1_MAX_BREAKOUT_STRETCH_PCT", "1.0")),
    "microStrategy41MaxSpreadPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY4_1_MAX_SPREAD_PCT", "0.35")),
    "microStrategy9TopN": int(os.environ.get("CRYPTO_MICRO_STRATEGY9_TOP_N", "20")),
    "microStrategy9MinPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_MIN_PCT_1H", "0.55")),
    "microStrategy9MaxPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_MAX_PCT_1H", "2.2")),
    "microStrategy9MaxPct15m": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_MAX_PCT_15M", "0.9")),
    "microStrategy9Ema9TouchPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_EMA9_TOUCH_PCT", "0.25")),
    "microStrategy9Ema21SlackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_EMA21_SLACK_PCT", "0.1")),
    "microStrategy9MinVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_MIN_VOLUME_RATIO", "0.7")),
    "microStrategy9MaxVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_MAX_VOLUME_RATIO", "2.5")),
    "microStrategy9StopLossPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_STOP_LOSS_PCT", "0.7")),
    "microStrategy9TakeProfit1Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_TAKE_PROFIT_1_PCT", "1.0")),
    "microStrategy9TakeProfit1Fraction": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_TAKE_PROFIT_1_FRACTION", "0.35")),
    "microStrategy9TakeProfit2Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_TAKE_PROFIT_2_PCT", "2.4")),
    "microStrategy9BreakevenLockPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_BREAKEVEN_LOCK_PCT", "0.2")),
    "microStrategy9TrailingStartPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_TRAILING_START_PCT", "1.5")),
    "microStrategy9TrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_TRAILING_GIVEBACK_PCT", "0.7")),
    "microStrategy9SoftTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY9_SOFT_TIME_STOP_BARS", "6")),
    "microStrategy9HardTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY9_HARD_TIME_STOP_BARS", "12")),
    "microStrategy9MinProgressPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY9_MIN_PROGRESS_PCT", "0.0")),
    "microStrategy18TopN": int(os.environ.get("CRYPTO_MICRO_STRATEGY18_TOP_N", "20")),
    "microStrategy18MinPct2h": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_MIN_PCT_2H", "2.2")),
    "microStrategy18MaxPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_MAX_PCT_1H", "3.0")),
    "microStrategy18MaxPct15m": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_MAX_PCT_15M", "1.5")),
    "microStrategy18BreakVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_BREAK_VOLUME_RATIO", "1.1")),
    "microStrategy18ConfirmVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_CONFIRM_VOLUME_RATIO", "0.6")),
    "microStrategy18RetestTolerancePct": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_RETEST_TOLERANCE_PCT", "0.45")),
    "microStrategy18HoldPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_HOLD_PCT", "0.0")),
    "microStrategy18StopLossPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_STOP_LOSS_PCT", "0.6")),
    "microStrategy18TakeProfit1Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_TAKE_PROFIT_1_PCT", "1.2")),
    "microStrategy18TakeProfit1Fraction": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_TAKE_PROFIT_1_FRACTION", "0.35")),
    "microStrategy18TakeProfit2Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_TAKE_PROFIT_2_PCT", "2.4")),
    "microStrategy18BreakevenLockPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_BREAKEVEN_LOCK_PCT", "0.15")),
    "microStrategy18TrailingStartPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_TRAILING_START_PCT", "1.8")),
    "microStrategy18TrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_TRAILING_GIVEBACK_PCT", "0.8")),
    "microStrategy18SoftTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY18_SOFT_TIME_STOP_BARS", "6")),
    "microStrategy18HardTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY18_HARD_TIME_STOP_BARS", "12")),
    "microStrategy18MinProgressPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY18_MIN_PROGRESS_PCT", "0.0")),
    "microStrategy20TopN": int(os.environ.get("CRYPTO_MICRO_STRATEGY20_TOP_N", "20")),
    "microStrategy20MinPct12h": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_MIN_PCT_12H", "6.0")),
    "microStrategy20MinPct6h": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_MIN_PCT_6H", "1.0")),
    "microStrategy20MinPct3h": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_MIN_PCT_3H", "0.5")),
    "microStrategy20MinPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_MIN_PCT_1H", "0.0")),
    "microStrategy20MaxPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_MAX_PCT_1H", "3.0")),
    "microStrategy20MaxPct15m": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_MAX_PCT_15M", "0.8")),
    "microStrategy20ReclaimBufferPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_RECLAIM_BUFFER_PCT", "0.45")),
    "microStrategy20MinVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_MIN_VOLUME_RATIO", "0.5")),
    "microStrategy20MaxVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_MAX_VOLUME_RATIO", "3.5")),
    "microStrategy20MaxUpperWickRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_MAX_UPPER_WICK_RATIO", "0.65")),
    "microStrategy20StopLossPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_STOP_LOSS_PCT", "0.7")),
    "microStrategy20TakeProfit1Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_TAKE_PROFIT_1_PCT", "1.6")),
    "microStrategy20TakeProfit1Fraction": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_TAKE_PROFIT_1_FRACTION", "0.25")),
    "microStrategy20TakeProfit2Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_TAKE_PROFIT_2_PCT", "5.0")),
    "microStrategy20BreakevenLockPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_BREAKEVEN_LOCK_PCT", "0.25")),
    "microStrategy20TrailingStartPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_TRAILING_START_PCT", "2.8")),
    "microStrategy20TrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_TRAILING_GIVEBACK_PCT", "0.9")),
    "microStrategy20SoftTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY20_SOFT_TIME_STOP_BARS", "10")),
    "microStrategy20HardTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY20_HARD_TIME_STOP_BARS", "24")),
    "microStrategy20MinProgressPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY20_MIN_PROGRESS_PCT", "0.25")),
    "microStrategy21TopN": int(os.environ.get("CRYPTO_MICRO_STRATEGY21_TOP_N", "20")),
    "microStrategy21MinPct12h": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_MIN_PCT_12H", "4.0")),
    "microStrategy21MinPct6h": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_MIN_PCT_6H", "1.0")),
    "microStrategy21MinPct3h": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_MIN_PCT_3H", "3.0")),
    "microStrategy21MaxPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_MAX_PCT_1H", "1.8")),
    "microStrategy21MaxPct15m": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_MAX_PCT_15M", "0.8")),
    "microStrategy21Ema9TouchPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_EMA9_TOUCH_PCT", "0.45")),
    "microStrategy21Ema21SlackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_EMA21_SLACK_PCT", "0.15")),
    "microStrategy21MinBodyPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_MIN_BODY_PCT", "0.15")),
    "microStrategy21MinVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_MIN_VOLUME_RATIO", "0.7")),
    "microStrategy21MaxVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_MAX_VOLUME_RATIO", "3.5")),
    "microStrategy21StopLossPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_STOP_LOSS_PCT", "0.6")),
    "microStrategy21TakeProfit1Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_TAKE_PROFIT_1_PCT", "1.4")),
    "microStrategy21TakeProfit1Fraction": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_TAKE_PROFIT_1_FRACTION", "0.3")),
    "microStrategy21TakeProfit2Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_TAKE_PROFIT_2_PCT", "4.0")),
    "microStrategy21BreakevenLockPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_BREAKEVEN_LOCK_PCT", "0.25")),
    "microStrategy21TrailingStartPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_TRAILING_START_PCT", "2.4")),
    "microStrategy21TrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_TRAILING_GIVEBACK_PCT", "0.8")),
    "microStrategy21SoftTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY21_SOFT_TIME_STOP_BARS", "8")),
    "microStrategy21HardTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY21_HARD_TIME_STOP_BARS", "20")),
    "microStrategy21MinProgressPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY21_MIN_PROGRESS_PCT", "0.2")),
    "microStrategy22TopN": int(os.environ.get("CRYPTO_MICRO_STRATEGY22_TOP_N", "10")),
    "microStrategy22MinPct2h": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_MIN_PCT_2H", "1.2")),
    "microStrategy22MinPct3h": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_MIN_PCT_3H", "0.0")),
    "microStrategy22MaxPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_MAX_PCT_1H", "2.0")),
    "microStrategy22MaxPct15m": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_MAX_PCT_15M", "1.4")),
    "microStrategy22BreakVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_BREAK_VOLUME_RATIO", "1.3")),
    "microStrategy22ConfirmVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_CONFIRM_VOLUME_RATIO", "0.5")),
    "microStrategy22RetestTolerancePct": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_RETEST_TOLERANCE_PCT", "0.7")),
    "microStrategy22HoldPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_HOLD_PCT", "0")),
    "microStrategy22MaxUpperWickRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_MAX_UPPER_WICK_RATIO", "0.7")),
    "microStrategy22StopLossPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_STOP_LOSS_PCT", "0.7")),
    "microStrategy22TakeProfit1Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_TAKE_PROFIT_1_PCT", "1.6")),
    "microStrategy22TakeProfit1Fraction": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_TAKE_PROFIT_1_FRACTION", "0.25")),
    "microStrategy22TakeProfit2Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_TAKE_PROFIT_2_PCT", "5.0")),
    "microStrategy22BreakevenLockPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_BREAKEVEN_LOCK_PCT", "0.25")),
    "microStrategy22TrailingStartPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_TRAILING_START_PCT", "2.8")),
    "microStrategy22TrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_TRAILING_GIVEBACK_PCT", "0.9")),
    "microStrategy22SoftTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY22_SOFT_TIME_STOP_BARS", "10")),
    "microStrategy22HardTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY22_HARD_TIME_STOP_BARS", "24")),
    "microStrategy22MinProgressPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY22_MIN_PROGRESS_PCT", "0.25")),
    "microStrategy23TopN": int(os.environ.get("CRYPTO_MICRO_STRATEGY23_TOP_N", "20")),
    "microStrategy23MinPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_MIN_PCT_1H", "1.4")),
    "microStrategy23MaxPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_MAX_PCT_1H", "3.4")),
    "microStrategy23MinPct3h": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_MIN_PCT_3H", "0.0")),
    "microStrategy23MaxPct15m": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_MAX_PCT_15M", "0.8")),
    "microStrategy23MinVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_MIN_VOLUME_RATIO", "2.0")),
    "microStrategy23MaxVolumeRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_MAX_VOLUME_RATIO", "4.5")),
    "microStrategy23MaxUpperWickRatio": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_MAX_UPPER_WICK_RATIO", "0.25")),
    "microStrategy23MaxBreakoutStretchPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_MAX_BREAKOUT_STRETCH_PCT", "1.1")),
    "microStrategy23MinBodyPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_MIN_BODY_PCT", "0.1")),
    "microStrategy23StopLossPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_STOP_LOSS_PCT", "0.6")),
    "microStrategy23TakeProfit1Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_TAKE_PROFIT_1_PCT", "1.4")),
    "microStrategy23TakeProfit1Fraction": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_TAKE_PROFIT_1_FRACTION", "0.3")),
    "microStrategy23TakeProfit2Pct": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_TAKE_PROFIT_2_PCT", "4.0")),
    "microStrategy23BreakevenLockPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_BREAKEVEN_LOCK_PCT", "0.25")),
    "microStrategy23TrailingStartPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_TRAILING_START_PCT", "2.4")),
    "microStrategy23TrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_TRAILING_GIVEBACK_PCT", "0.8")),
    "microStrategy23SoftTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY23_SOFT_TIME_STOP_BARS", "8")),
    "microStrategy23HardTimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY23_HARD_TIME_STOP_BARS", "20")),
    "microStrategy23MinProgressPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY23_MIN_PROGRESS_PCT", "0.2")),
    "microStrategy24TopN": int(os.environ.get("CRYPTO_MICRO_STRATEGY24_TOP_N", "5")),
    "microStrategy24SessionTopN": int(os.environ.get("CRYPTO_MICRO_STRATEGY24_SESSION_TOP_N", "10")),
    "microStrategy24DelayBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY24_DELAY_BARS", "1")),
    "microStrategy24MinPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY24_MIN_PCT_1H", "1.0")),
    "microStrategy24MaxPct1h": float(os.environ.get("CRYPTO_MICRO_STRATEGY24_MAX_PCT_1H", "5.0")),
    "microStrategy24StopLossPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY24_STOP_LOSS_PCT", "1.5")),
    "microStrategy24BreakevenAfterPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY24_BREAKEVEN_AFTER_PCT", "0.8")),
    "microStrategy24TrailingStartPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY24_TRAILING_START_PCT", "1.2")),
    "microStrategy24TrailingGivebackPct": float(os.environ.get("CRYPTO_MICRO_STRATEGY24_TRAILING_GIVEBACK_PCT", "0.6")),
    "microStrategy24TimeStopBars": int(os.environ.get("CRYPTO_MICRO_STRATEGY24_TIME_STOP_BARS", "12")),
}


MICRO_TOP10_OPTIMIZED_STRATEGIES = {
    # === 2026-06-18 04:00 optimizer winners (4H cycle, 14d lookback, vol_ratio>=1.0, min_trades>=10) ===
    # Entry: delay=3, max_rank=3, chg=3-10%, green_confirm, max_upper_wick=1.2%, min_vol=1.0x, reclaim=false, dur=10-40
    # All 144 candidates pass thresholds: net_avg>0, PF>1.5, max_loss>-2%, WR>40%, trades>=10 (78-101 closed trades)
    # Top 1 (sl1.2, be0.6, trail0.9x0.4, t8): net_avg=0.649%, WR=56.4%, PF=2.58, max_loss=-1.36%
    # Top 2 (sl1.2, be0.6, trail0.9x0.4, t12): net_avg=0.649%, WR=56.4%, PF=2.58, max_loss=-1.36%
    # Top 3 (sl1.2, be0.6, trail0.9x0.4, t18): net_avg=0.649%, WR=56.4%, PF=2.58, max_loss=-1.36%


# === Strategy 4.1 (production backtest positive) ===
    # Kept from previous: net_avg=0.087%, WR=44.4%, PF=1.21, max_loss=-0.96%
    "strategy4_1_breakout_confirmation": {
        "version": "strategy4.1",
        "entry_delay_bars": 0,
        "max_rank": 5,
        "min_change_1h_pct": 0.4,
        "max_change_1h_pct": 4.0,
        "min_current_change_1h_pct": 0.2,
        "require_change_reclaim": True,
        "require_green_confirm": True,
        "max_upper_wick_pct": 0.45,
        "min_volume_ratio": 1.4,
        "reclaim_entry_price": True,
        "shadow_only": False,
        "stop_loss_pct": 0.8,
        "breakeven_after_pct": 0.2,
        "trailing_start_pct": 1.6,
        "trailing_giveback_pct": 0.6,
        "time_stop_bars": 8,
    },
    # === Strategy 20 (6h/12h VWAP reclaim, net_avg=0.465%, PF=2.11) ===
    "strategy20_6h12h_cool_vwap_reclaim": {
        "version": "strategy20",
        "entry_delay_bars": 0,
        "max_rank": 20,
        "min_change_1h_pct": 0.0,
        "max_change_1h_pct": 3.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": True,
        "require_green_confirm": False,
        "max_upper_wick_pct": 0.65,
        "min_volume_ratio": 0.5,
        "reclaim_entry_price": True,
        "shadow_only": False,
        "stop_loss_pct": 0.7,
        "breakeven_after_pct": 0.25,
        "trailing_start_pct": 2.8,
        "trailing_giveback_pct": 0.9,
        "time_stop_bars": 24,
    },
    # === Top5 quality score strategy (shadow-only) ===
    "top5dplus_score95_chg2_5_sl1_tr06x03_t6": {
        "version": "top5dplus",
        "entry_delay_bars": 0,
        "max_rank": 5,
        "min_change_1h_pct": 2.0,
        "max_change_1h_pct": 5.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "min_volume_ratio": 0.0,
        "shadow_only": True,
        "quality_score_threshold": 95.0,
        "quality_rank_weight": 8.0,
        "quality_change_peak_pct": 5.0,
        "quality_change_peak_score": 25.0,
        "quality_change_penalty": 7.0,
        "quality_volume_weight": 8.0,
        "quality_volume_cap_score": 20.0,
        "quality_ema_bonus": 12.0,
        "quality_green_bonus": 8.0,
        "quality_upper_wick_bonus": 8.0,
        "quality_close_pos_bonus": 6.0,
        "quality_body_bonus": 5.0,
        "quality_atr_bonus": 5.0,
        "quality_max_upper_wick_ratio": 0.25,
        "quality_min_close_position": 0.60,
        "quality_min_body_ratio": 0.25,
        "quality_atr_bonus_max_pct": 1.8,
        "stop_loss_pct": 1.0,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 0.6,
        "trailing_giveback_pct": 0.3,
        "time_stop_bars": 6,
    },
    # === Legacy strategies (kept for backward compat, not in default active set) ===
    "top10scan_d2_r5_chg2-8_cur2_vol1.2_sl0.8_tr1.5x0.5_t12": {
        "version": "top10scan",
        "entry_delay_bars": 2,
        "max_rank": 5,
        "min_change_1h_pct": 2.0,
        "max_change_1h_pct": 8.0,
        "min_current_change_1h_pct": 2.0,
        "require_change_reclaim": False,
        "require_green_confirm": True,
        "max_upper_wick_pct": 999.9,
        "min_volume_ratio": 1.2,
        "reclaim_entry_price": False,
        "shadow_only": True,
        "stop_loss_pct": 0.8,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 1.5,
        "trailing_giveback_pct": 0.5,
        "time_stop_bars": 12,
    },
    "top10scan6_d1_r3_chg3_12_cur1_sl08_tr15x05_t12": {
        "version": "top10scan6",
        "entry_delay_bars": 1,
        "max_rank": 3,
        "min_change_1h_pct": 3.0,
        "max_change_1h_pct": 12.0,
        "min_current_change_1h_pct": 1.0,
        "require_change_reclaim": True,
        "require_green_confirm": True,
        "max_upper_wick_pct": 999.9,
        "min_volume_ratio": 0.0,
        "reclaim_entry_price": False,
        "shadow_only": True,
        "stop_loss_pct": 0.8,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 1.5,
        "trailing_giveback_pct": 0.5,
        "time_stop_bars": 12,
    },
    "top10scan1_d1_r3_chg3_12_cur1_sl1_tr15x05_t12": {
        "version": "top10scan1",
        "entry_delay_bars": 1,
        "max_rank": 3,
        "min_change_1h_pct": 3.0,
        "max_change_1h_pct": 12.0,
        "min_current_change_1h_pct": 1.0,
        "require_change_reclaim": True,
        "require_green_confirm": True,
        "max_upper_wick_pct": 999.9,
        "min_volume_ratio": 0.0,
        "reclaim_entry_price": False,
        "shadow_only": True,
        "stop_loss_pct": 1.0,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 1.5,
        "trailing_giveback_pct": 0.5,
        "time_stop_bars": 12,
    },
    "top10scan1v_d1_r3_chg3_12_cur1_vol12_sl1_tr15x05_t12": {
        "version": "top10scan1v",
        "entry_delay_bars": 1,
        "max_rank": 3,
        "min_change_1h_pct": 3.0,
        "max_change_1h_pct": 12.0,
        "min_current_change_1h_pct": 1.0,
        "require_change_reclaim": True,
        "require_green_confirm": True,
        "max_upper_wick_pct": 999.9,
        "min_volume_ratio": 1.2,
        "reclaim_entry_price": False,
        "shadow_only": True,
        "stop_loss_pct": 1.0,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 1.5,
        "trailing_giveback_pct": 0.5,
        "time_stop_bars": 12,
    },
    "top10shadow1_d0_r5_chg2_15_cur0_sl1_tr1x05_t12": {
        "version": "top10shadow1",
        "entry_delay_bars": 0,
        "max_rank": 5,
        "min_change_1h_pct": 2.0,
        "max_change_1h_pct": 15.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": False,
        "max_upper_wick_pct": 999.9,
        "min_volume_ratio": 0.0,
        "reclaim_entry_price": False,
        "shadow_only": True,
        "stop_loss_pct": 1.0,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 1.0,
        "trailing_giveback_pct": 0.5,
        "time_stop_bars": 12,
    },
    "top10v1_rank5_chg3_10_sl1_trail09_t12": {
        "version": "top10v1",
        "entry_delay_bars": 0,
        "max_rank": 5,
        "min_change_1h_pct": 3.0,
        "max_change_1h_pct": 10.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": False,
        "max_upper_wick_pct": 999.9,
        "min_volume_ratio": 0.0,
        "reclaim_entry_price": False,
        "shadow_only": False,
        "stop_loss_pct": 1.0,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 0.9,
        "trailing_giveback_pct": 0.4,
        "time_stop_bars": 12,
    },
    "top10v3_rank5_chg3_10_sl08_trail09_t12": {
        "version": "top10v3",
        "entry_delay_bars": 0,
        "max_rank": 5,
        "min_change_1h_pct": 3.0,
        "max_change_1h_pct": 10.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": False,
        "max_upper_wick_pct": 999.9,
        "min_volume_ratio": 0.0,
        "reclaim_entry_price": False,
        "shadow_only": False,
        "stop_loss_pct": 0.8,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 0.9,
        "trailing_giveback_pct": 0.4,
        "time_stop_bars": 12,
    },
    "top10v5_delay1_rank3_chg1_5_sl15_trail12_t12": {
        "version": "top10v5",
        "entry_delay_bars": 1,
        "max_rank": 3,
        "min_change_1h_pct": 1.0,
        "max_change_1h_pct": 5.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": False,
        "max_upper_wick_pct": 999.9,
        "min_volume_ratio": 0.0,
        "reclaim_entry_price": False,
        "shadow_only": False,
        "stop_loss_pct": 1.5,
        "breakeven_after_pct": 0.8,
        "trailing_start_pct": 1.2,
        "trailing_giveback_pct": 0.6,
        "time_stop_bars": 12,
    },
    # === 2026-06-18 20:00 optimizer winners (4H cycle, 14d lookback, vol_ratio>=1.0, min_trades>=10) ===
    # Entry: delay=3, max_rank=3, chg=3-10%, green_confirm, max_upper_wick=1.2%, min_vol=1.0x, reclaim=false
    # dur=10-40 (top1/2) / dur=8-50 (top3), 144 candidates, 78-95 closed trades
    # Thresholds: net_avg>0, PF>1.5, max_loss>-2%, WR>40%, trades>=10
    # Top 1 (dur10-40, sl1.2, be0.6, trail0.9x0.4, t8): net_avg=0.612%, WR=55.1%, PF=2.48, max_loss=-1.36%, trades=78
    # Top 2 (dur10-40, sl0.8, be0.6, trail0.9x0.4, t8): net_avg=0.602%, WR=50.0%, PF=2.55, max_loss=-0.96%, trades=78
    # Top 3 (dur8-50, sl1.2, be0.6, trail0.9x0.4, t8): net_avg=0.554%, WR=52.6%, PF=2.34, max_loss=-1.36%, trades=95
    "auto_top1_4h_d3_r3_chg3-10_green_uw1.2_vol10dur1040_sl1.2_be0.6_tr0.9x0.4_t8": {
        "version": "auto_top1_4h",
        "entry_delay_bars": 3,
        "max_rank": 3,
        "min_change_1h_pct": 3.0,
        "max_change_1h_pct": 10.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": True,
        "max_upper_wick_pct": 1.2,
        "min_volume_ratio": 1.0,
        "reclaim_entry_price": False,
        "shadow_only": False,
        "stop_loss_pct": 1.2,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 0.9,
        "trailing_giveback_pct": 0.4,
        "time_stop_bars": 8,
    },
    "auto_top2_4h_d3_r3_chg3-10_green_uw1.2_vol10dur1040_sl0.8_be0.6_tr0.9x0.4_t8": {
        "version": "auto_top2_4h",
        "entry_delay_bars": 3,
        "max_rank": 3,
        "min_change_1h_pct": 3.0,
        "max_change_1h_pct": 10.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": True,
        "max_upper_wick_pct": 1.2,
        "min_volume_ratio": 1.0,
        "reclaim_entry_price": False,
        "shadow_only": False,
        "stop_loss_pct": 0.8,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 0.9,
        "trailing_giveback_pct": 0.4,
        "time_stop_bars": 8,
    },
    "auto_top3_4h_d3_r3_chg3-10_green_uw1.2_vol10dur850_sl1.2_be0.6_tr0.9x0.4_t8": {
        "version": "auto_top3_4h",
        "entry_delay_bars": 3,
        "max_rank": 3,
        "min_change_1h_pct": 3.0,
        "max_change_1h_pct": 10.0,
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": False,
        "require_green_confirm": True,
        "max_upper_wick_pct": 1.2,
        "min_volume_ratio": 1.0,
        "reclaim_entry_price": False,
        "shadow_only": False,
        "stop_loss_pct": 1.2,
        "breakeven_after_pct": 0.6,
        "trailing_start_pct": 0.9,
        "trailing_giveback_pct": 0.4,
        "time_stop_bars": 8,
    },
}
MICRO_EXCLUDED_BASESMICRO_EXCLUDED_BASES = {"BTC", "ETH", "BNB", "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USD", "EUR", "BRL"}
MICRO_EXCLUDED_SYNTHETIC_BASES = {
    "AAPL", "AMD", "AMZN", "BABA", "CL", "COIN", "DIA", "GLD", "GOOGL", "HOOD",
    "INTC", "IWM", "META", "MSTR", "MSFT", "NFLX", "NVDA", "ORCL", "PLTR",
    "QQQ", "SNDK", "SLV", "SPY", "TSLA", "USO", "XLE",
    "CBRS", "COHR", "COST", "DRAM", "MU", "WDC", "XAG", "XAU",
}

# Standard large-cap crypto strategies were retired so the service can focus on
# OKX micro-cap strategies only. Keep the list empty to prevent the legacy
# paper-trading loop, performance endpoint, and backtest endpoint from emitting
# the old 5 strategy rows.
STRATEGIES = []

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS crypto_state (
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY(symbol, strategy)
);
CREATE TABLE IF NOT EXISTS crypto_signals (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ DEFAULT NOW(),
    symbol TEXT,
    strategy TEXT,
    price DOUBLE PRECISION,
    signal TEXT,
    reason TEXT,
    action TEXT,
    equity DOUBLE PRECISION,
    return_pct DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS crypto_trades (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ DEFAULT NOW(),
    symbol TEXT,
    strategy TEXT,
    side TEXT,
    price DOUBLE PRECISION,
    quantity DOUBLE PRECISION,
    quote_amount DOUBLE PRECISION,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS crypto_candles (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    source TEXT,
    PRIMARY KEY(symbol, interval, ts)
);
CREATE TABLE IF NOT EXISTS crypto_micro_state (
    inst_id TEXT PRIMARY KEY,
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS crypto_micro_trades (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ DEFAULT NOW(),
    inst_id TEXT,
    strategy TEXT DEFAULT 'strategy1',
    side TEXT,
    price DOUBLE PRECISION,
    quantity DOUBLE PRECISION,
    quote_amount DOUBLE PRECISION,
    ma60 DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    pct5 DOUBLE PRECISION,
    pct15 DOUBLE PRECISION,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS crypto_micro_trade_windows (
    id SERIAL PRIMARY KEY,
    trade_id INTEGER NOT NULL,
    inst_id TEXT NOT NULL,
    side TEXT NOT NULL,
    window_type TEXT NOT NULL,
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    candles JSONB NOT NULL,
    signal JSONB,
    UNIQUE(trade_id, window_type)
);
CREATE TABLE IF NOT EXISTS crypto_micro_surge_archive (
    id SERIAL PRIMARY KEY,
    scan_hour TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    rank INTEGER NOT NULL,
    inst_id TEXT NOT NULL,
    price DOUBLE PRECISION,
    pct5 DOUBLE PRECISION,
    pct15 DOUBLE PRECISION,
    pct1h DOUBLE PRECISION,
    pct12h DOUBLE PRECISION,
    pct24 DOUBLE PRECISION,
    quote_volume_24h DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    distance_ma60_pct DOUBLE PRECISION,
    candles JSONB NOT NULL,
    signal JSONB,
    UNIQUE(scan_hour, inst_id)
);
CREATE TABLE IF NOT EXISTS crypto_micro_strategy_performance_12h (
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    strategy TEXT NOT NULL,
    entries INTEGER NOT NULL DEFAULT 0,
    closed_trades INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    open_trades INTEGER NOT NULL DEFAULT 0,
    realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_pnl_roe_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    win_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY(window_start, strategy)
);
"""


class CryptoPaperBot:
    def __init__(self):
        self.pool = None
        self.running = False
        self.task = None
        self.backfill_task = None
        self.backfill_status = {"running": False, "message": "idle", "symbols": {}, "startedAt": None, "finishedAt": None, "error": ""}
        self.micro_run_lock = asyncio.Lock()
        self.micro_task = None
        self.micro_running = False
        self.micro_last_run_at = None
        self.micro_last_error = ""
        self.micro_candidates = []
        self.micro_ranking12h = []
        self.micro_ranking1h = []
        self.micro_positions = []
        self.micro_top10_debug = []
        self.micro_surge_last_archive_hour = None
        self.micro_surge_archive_status = {"lastRunAt": None, "lastHour": None, "saved": 0, "lastError": ""}
        self.last_error = ""
        self.last_run_at = None
        self.snapshots = {}

    async def start(self):
        # Standard crypto paper strategies are retired. Starting the crypto bot
        # now only starts the micro-cap scanner/trader.
        self.running = False
        self.task = None
        await self.start_micro()

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            self.task = None
        await self.stop_micro()

    async def setup(self):
        database_url = os.environ.get("DATABASE_URL", "")
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        if not database_url.startswith("postgresql://"):
            raise RuntimeError("CRYPTO bot needs Render PostgreSQL DATABASE_URL.")
        self.pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
        async with self.pool.acquire() as conn:
            await conn.execute(CREATE_SQL)
            await conn.execute("ALTER TABLE crypto_micro_trades ADD COLUMN IF NOT EXISTS strategy TEXT DEFAULT 'strategy1'")
            await conn.execute("UPDATE crypto_micro_trades SET strategy='strategy1' WHERE strategy IS NULL")
            await conn.execute(
                """DELETE FROM crypto_micro_trades t
                   USING (
                       SELECT id, ROW_NUMBER() OVER(PARTITION BY inst_id ORDER BY ts DESC) AS rn
                       FROM crypto_micro_trades
                       WHERE strategy='strategy2' AND side='BUY' AND ts > NOW() - INTERVAL '1 day'
                   ) d
                   WHERE t.id=d.id AND d.rn>1
                     AND NOT EXISTS (
                         SELECT 1 FROM crypto_micro_trades s
                         WHERE s.strategy='strategy2' AND s.inst_id=t.inst_id AND s.side='SELL' AND s.ts>t.ts
                     )"""
            )

    async def close(self):
        await self.stop()
        await self.stop_micro()
        if self.pool:
            await self.pool.close()

    async def start_micro(self):
        if self.micro_running:
            return
        self.micro_running = True
        self.micro_task = asyncio.create_task(self._micro_loop())

    async def stop_micro(self):
        self.micro_running = False
        if self.micro_task:
            self.micro_task.cancel()
            self.micro_task = None

    async def _micro_loop(self):
        while self.micro_running:
            try:
                await self.run_micro_once()
                self.micro_last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.micro_last_error = str(exc)
            await asyncio.sleep(CONFIG["microPollSeconds"])

    async def _loop(self):
        while self.running:
            try:
                await self.run_once()
                self.last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
            await asyncio.sleep(CONFIG["pollSeconds"])

    async def run_once(self):
        # No-op: legacy standard crypto strategies have been removed.
        self.last_run_at = datetime.now(timezone.utc).isoformat()

    async def _apply_symbol(self, symbol, candles, higher):
        price = candles[-1]["close"]
        close_time = candles[-1]["closeTime"]
        await self._save_candles(symbol, CONFIG["interval"], candles)
        states = await self._load_states(symbol)
        rows = []
        for strategy in STRATEGIES:
            account = states[strategy["id"]]
            if account.get("lastCandleCloseTime") == close_time:
                rows.append(snapshot_row(strategy, account, price))
                continue
            refresh_daily_limit(account, close_time)
            decision = decide(strategy["id"], candles, higher, account)
            decision = with_risk_exit(decision, account, price)
            action = "no_trade"
            if decision["signal"] == "BUY" and account["assetQty"] <= 0:
                if can_enter(account, close_time):
                    quote = min(account["cash"], CONFIG["orderQuoteSize"])
                    qty = quote / price
                    account["cash"] -= quote
                    account["assetQty"] += qty
                    account["avgEntry"] = price
                    account["entryCountToday"] += 1
                    account["trades"] += 1
                    action = "buy_paper"
                    await self._log_trade(symbol, strategy["id"], "BUY", price, qty, quote, decision["reason"])
                else:
                    action = "skip_daily_limit_or_cooldown"
            elif decision["signal"] == "SELL" and account["assetQty"] > 0:
                qty = account["assetQty"]
                quote = qty * price
                pnl = quote - qty * account["avgEntry"]
                account["cash"] += quote
                account["assetQty"] = 0
                account["avgEntry"] = 0
                account["lastExitTime"] = close_time
                account["realizedPnl"] += pnl
                account["trades"] += 1
                account["closedTrades"] += 1
                account["wins"] += 1 if pnl > 0 else 0
                action = "sell_paper"
                await self._log_trade(symbol, strategy["id"], "SELL", price, qty, quote, decision["reason"])

            equity = account["cash"] + account["assetQty"] * price
            account["peakEquity"] = max(account["peakEquity"], equity)
            if account["peakEquity"] > 0:
                account["maxDrawdownPct"] = max(account["maxDrawdownPct"], ((account["peakEquity"] - equity) / account["peakEquity"]) * 100)
            account["lastSignal"] = decision["signal"]
            account["lastReason"] = decision["reason"]
            account["lastAction"] = action
            account["lastCandleCloseTime"] = close_time
            await self._save_state(symbol, strategy["id"], account)
            await self._log_signal(symbol, strategy["id"], price, decision, action, equity)
            rows.append(snapshot_row(strategy, account, price))

        rows.sort(key=lambda row: row["equity"], reverse=True)
        self.snapshots[symbol] = {
            "config": {**CONFIG, "symbol": symbol},
            "running": self.running,
            "lastError": self.last_error,
            "lastRunAt": self.last_run_at,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "lastPrice": price,
            "strategies": rows,
            "candles": candles[-80:],
        }

    async def _load_states(self, symbol):
        async with self.pool.acquire() as conn:
            records = await conn.fetch("SELECT strategy, state FROM crypto_state WHERE symbol=$1", symbol)
        states = {}
        for record in records:
            raw_state = record["state"]
            states[record["strategy"]] = raw_state if isinstance(raw_state, dict) else json.loads(raw_state)
        for strategy in STRATEGIES:
            states.setdefault(strategy["id"], new_account())
        return states

    async def _save_state(self, symbol, strategy, state):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO crypto_state(symbol,strategy,state,updated_at)
                   VALUES($1,$2,$3::jsonb,NOW())
                   ON CONFLICT(symbol,strategy) DO UPDATE SET state=$3::jsonb, updated_at=NOW()""",
                symbol,
                strategy,
                json.dumps(state),
            )

    async def _log_signal(self, symbol, strategy, price, decision, action, equity):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO crypto_signals(symbol,strategy,price,signal,reason,action,equity,return_pct)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
                symbol, strategy, price, decision["signal"], decision["reason"], action,
                equity, ((equity - CONFIG["startingCash"]) / CONFIG["startingCash"]) * 100,
            )

    async def _log_trade(self, symbol, strategy, side, price, qty, quote, reason):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO crypto_trades(symbol,strategy,side,price,quantity,quote_amount,reason)
                   VALUES($1,$2,$3,$4,$5,$6,$7)""",
                symbol, strategy, side, price, qty, quote, reason,
            )

    async def _save_candles(self, symbol, interval, candles):
        rows = [
            (
                symbol,
                interval,
                datetime.fromtimestamp(candle["closeTime"] / 1000, tz=timezone.utc),
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"],
                candle["volume"],
                CONFIG["dataSource"],
            )
            for candle in candles
        ]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO crypto_candles(symbol,interval,ts,open,high,low,close,volume,source)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   ON CONFLICT(symbol,interval,ts) DO UPDATE SET
                   open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                   close=EXCLUDED.close, volume=EXCLUDED.volume, source=EXCLUDED.source""",
                rows,
            )

    async def start_backfill(self, days=90):
        if self.backfill_task and not self.backfill_task.done():
            return self.backfill_status
        self.backfill_status = {
            "running": True,
            "message": "starting",
            "symbols": {},
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "finishedAt": None,
            "error": "",
            "days": days,
        }
        self.backfill_task = asyncio.create_task(self._backfill_history(days))
        return self.backfill_status

    async def _backfill_history(self, days):
        try:
            since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
            async with httpx.AsyncClient(timeout=30) as client:
                for symbol in CONFIG["symbols"]:
                    self.backfill_status["symbols"].setdefault(symbol, {})
                    for interval in [CONFIG["interval"], CONFIG["higherInterval"]]:
                        saved = await self._backfill_symbol_interval(client, symbol, interval, since_ms)
                        self.backfill_status["symbols"][symbol][interval] = saved
            self.backfill_status["message"] = "completed"
        except Exception as exc:
            self.backfill_status["error"] = str(exc)
            self.backfill_status["message"] = "failed"
        finally:
            self.backfill_status["running"] = False
            self.backfill_status["finishedAt"] = datetime.now(timezone.utc).isoformat()

    async def _backfill_symbol_interval(self, client, symbol, interval, since_ms):
        after = None
        total = 0
        seen_oldest = None
        while True:
            candles = await fetch_history_klines(client, symbol, interval, 300, after)
            candles = dedupe_candles(candles)
            if not candles:
                break
            wanted = [candle for candle in candles if candle["closeTime"] >= since_ms]
            if wanted:
                await self._save_candles(symbol, interval, wanted)
                total += len(wanted)
            oldest = min(candle["closeTime"] for candle in candles)
            self.backfill_status["message"] = f"{symbol} {interval} saved {total}"
            self.backfill_status["symbols"].setdefault(symbol, {})[interval] = total
            if oldest <= since_ms or oldest == seen_oldest:
                break
            seen_oldest = oldest
            after = str(oldest)
            await asyncio.sleep(0.12)
        return total

    async def run_micro_once(self):
        async with self.micro_run_lock:
            return await self._run_micro_once_locked()

    async def _run_micro_once_locked(self):
        async with httpx.AsyncClient(timeout=20) as client:
            tickers = await fetch_market_tickers(client, CONFIG["microInstType"])
            shortlist = shortlist_micro_tickers(tickers)
            states = await self._load_micro_states()
            open_count = sum(1 for state in states.values() if state.get("assetQty", 0) > 0)
            candidates = []
            archive_sources = {}
            positions = []
            for ticker in shortlist:
                inst_id = ticker["instId"]
                raw_candles = await fetch_okx_candles_by_inst(client, inst_id, CONFIG["microBaseInterval"], 240)
                candles = to_micro_candles(raw_candles)
                if len(candles) < 61:
                    continue
                signal = micro_trend_signal(ticker, candles)
                archive_sources[inst_id] = {"signal": dict(signal), "candles": candles, "ticker": ticker}
                state = states.get(inst_id, new_micro_state())
                if await self._maybe_capture_exit_post_window(inst_id, state, candles, signal):
                    states[inst_id] = state
                price = candles[-1]["close"]
                if state.get("assetQty", 0) > 0:
                    update_micro_position_state(state, price, signal)
                    if micro_should_exit(signal, state, price):
                        await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"])
                        open_count = max(0, open_count - 1)
                    else:
                        positions.append(micro_position_row(inst_id, state, price, signal))
                        await self._save_micro_state(inst_id, state)
                elif state.get("pendingEntry") and open_count < CONFIG["microMaxPositions"]:
                    if micro_entry_confirmed(state, signal, price):
                        signal["reason"] = "confirmed_breakout_5m"
                        state.pop("pendingEntry", None)
                        await self._micro_buy(inst_id, state, price, signal)
                        open_count += 1
                        positions.append(micro_position_row(inst_id, state, price, signal))
                    elif signal["time"] > state["pendingEntry"].get("expiresAt", 0) or not signal.get("entryVolumeOk"):
                        state.pop("pendingEntry", None)
                        await self._save_micro_state(inst_id, state)
                elif signal["buy"] and open_count < CONFIG["microMaxPositions"]:
                    state["pendingEntry"] = {
                        "time": signal["time"],
                        "breakoutLevel": signal["priorHigh"],
                        "expiresAt": signal["time"] + (micro_bar_minutes() * 3 * 60 * 1000),
                    }
                    await self._save_micro_state(inst_id, state)
                    signal["reason"] = "pending_breakout_confirm"
                    signal["buy"] = False
                candidate = dict(signal)
                candidate.pop("pre1hCandles", None)
                candidates.append(candidate)
                await asyncio.sleep(0.08)
        candidates.sort(key=lambda row: (row["buy"], row["trendScore"]), reverse=True)
        ranking12h = sorted(candidates, key=lambda row: row["pct12h"], reverse=True)
        ranking1h = sorted(candidates, key=lambda row: row["pct1h"], reverse=True)
        ranking2h = sorted(candidates, key=lambda row: row.get("pct2h", 0), reverse=True)
        ranking3h = sorted(candidates, key=lambda row: row.get("pct3h", 0), reverse=True)
        ranking6h = sorted(candidates, key=lambda row: row.get("pct6h", 0), reverse=True)
        # Only positions whose instruments are in the current scan universe can be
        # updated, displayed, and eventually closed by this run. Old paper states
        # for delisted/no-longer-shortlisted instruments must not occupy all
        # slots forever, otherwise newly deployed Render shadow probes never get
        # a chance to collect samples.
        open_count = sum(
            1
            for key, state in states.items()
            if state.get("assetQty", 0) > 0 and key.split("::", 1)[-1] in archive_sources
        )
        await self._archive_micro_surge_if_due(ranking1h, archive_sources)
        self.micro_top10_debug = []
        for strategy in CONFIG.get("microActiveStrategies") or []:
            if strategy in MICRO_TOP10_OPTIMIZED_STRATEGIES:
                open_count = await self._apply_micro_top10_optimized(strategy, ranking1h, archive_sources, states, positions, open_count)
        if micro_strategy_enabled("strategy4_breakout_confirmation"):
            open_count = await self._apply_micro_strategy4(archive_sources, states, positions, open_count)
        if micro_strategy_enabled("strategy4.1_breakout_confirmation"):
            open_count = await self._apply_micro_strategy41(archive_sources, states, positions, open_count)
        if micro_strategy_enabled("strategy9_ema9_bounce_low_heat"):
            open_count = await self._apply_micro_strategy9(ranking1h, archive_sources, states, positions, open_count)
        if micro_strategy_enabled("s18_top2h_retest_runner"):
            open_count = await self._apply_micro_strategy18(ranking2h, archive_sources, states, positions, open_count)
        if micro_strategy_enabled("strategy20_6h12h_cool_vwap_reclaim"):
            open_count = await self._apply_micro_strategy20(ranking12h, archive_sources, states, positions, open_count)
        if micro_strategy_enabled("strategy21_multi_tf_intersection_ema9_bounce"):
            open_count = await self._apply_micro_strategy21(ranking1h, ranking3h, ranking6h, archive_sources, states, positions, open_count)
        if micro_strategy_enabled("strategy22_2h_strength_breakout_retest"):
            open_count = await self._apply_micro_strategy22(ranking2h, archive_sources, states, positions, open_count)
        if micro_strategy_enabled("strategy23_top1h_clean_early_breakout"):
            open_count = await self._apply_micro_strategy23(ranking1h, archive_sources, states, positions, open_count)
        if micro_strategy_enabled("strategy24_top1h_delay_rank5_chg1_5"):
            open_count = await self._apply_micro_strategy24(ranking1h, archive_sources, states, positions, open_count)
        if micro_strategy_enabled("strategy2"):
            open_count = await self._apply_micro_strategy2(ranking1h, archive_sources, states, positions, open_count)
        if micro_strategy_enabled("strategy2.1_surge_momentum"):
            open_count = await self._apply_micro_strategy21_surge(ranking1h, archive_sources, states, positions, open_count)
        positions.sort(key=lambda row: row["unrealizedPnlPct"], reverse=True)
        self.micro_candidates = candidates[:40]
        self.micro_ranking12h = ranking12h[:40]
        self.micro_ranking1h = ranking1h[:40]
        self.micro_ranking2h = ranking2h[:40]
        self.micro_ranking3h = ranking3h[:40]
        self.micro_ranking6h = ranking6h[:40]
        self.micro_positions = positions
        self.micro_last_run_at = datetime.now(timezone.utc).isoformat()

    async def _apply_micro_top10_optimized(self, strategy, ranking1h, archive_sources, states, positions, open_count):
        params = MICRO_TOP10_OPTIMIZED_STRATEGIES[strategy]
        top_rank = {
            signal["instId"]: rank
            for rank, signal in enumerate(ranking1h[:10], start=1)
        }
        tracked_inst_ids = [
            key.split("::", 1)[1]
            for key in states
            if key.startswith(f"{strategy}::")
        ]
        for inst_id in dict.fromkeys(list(top_rank.keys()) + tracked_inst_ids):
            source = archive_sources.get(inst_id)
            if not source:
                continue
            state_key = micro_state_key(strategy, inst_id)
            state = states.get(state_key, new_micro_state())
            rank_1h = top_rank.get(inst_id)
            was_seen = bool(state.get("top10SessionSeen"))
            previous_active = bool(state.get("top10SessionActive"))
            if rank_1h is None:
                if state.get("top10SessionActive") or state.get("top10SessionSeen"):
                    state["top10SessionActive"] = False
                    state["top10SessionSeen"] = False
                    state["top10SessionAgeBars"] = 0
                    state["top10ShadowEntryTaken"] = False
                if state.get("assetQty", 0) <= 0:
                    await self._save_micro_state(state_key, state)
                    continue
            else:
                state["top10SessionActive"] = True
                state["top10SessionAgeBars"] = int(state.get("top10SessionAgeBars", 0) or 0) + 1 if previous_active else 0
            session_age_bars = int(state.get("top10SessionAgeBars", 0) or 0)
            source_signal = source["signal"]
            rank_1h = top_rank.get(inst_id)
            signal = micro_top10_optimized_signal(
                {
                    "instId": inst_id,
                    "_pct24": source_signal.get("pct24", 0),
                    "_quoteVol": source_signal.get("quoteVolume24h", 0),
                    "bidPx": source.get("ticker", {}).get("bidPx"),
                    "askPx": source.get("ticker", {}).get("askPx"),
                },
                source["candles"],
                strategy,
                rank_1h=rank_1h,
                collector_change_1h_pct=source_signal.get("pct1h", 0),
                session_age_bars=session_age_bars,
            )
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if rank_1h is None:
                    set_micro_exit(signal, f"{params['version']}_session_end", 1.0, price)
                    await self._micro_sell(inst_id, state, price, signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                elif micro_top10_optimized_should_exit(signal, state, price, strategy):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                    await self._save_micro_state(state_key, state)
            shadow_entry_allowed = bool(params.get("shadow_only")) and not state.get("top10ShadowEntryTaken")
            entry_allowed = (not was_seen) or shadow_entry_allowed
            if len(self.micro_top10_debug) < 120:
                self.micro_top10_debug.append({
                    "strategy": strategy,
                    "instId": inst_id,
                    "rank1h": rank_1h,
                    "buy": bool(signal.get("buy")),
                    "reason": signal.get("reason"),
                    "wasSeen": was_seen,
                    "shadowOnly": bool(params.get("shadow_only")),
                    "shadowEntryTaken": bool(state.get("top10ShadowEntryTaken")),
                    "shadowEntryAllowed": shadow_entry_allowed,
                    "entryAllowed": entry_allowed,
                    "openCount": open_count,
                    "maxPositions": CONFIG["microMaxPositions"],
                    "assetQty": state.get("assetQty", 0),
                    "top10RankOk": signal.get("top10RankOk"),
                    "top10HeatOk": signal.get("top10HeatOk"),
                    "top10CurrentChangeOk": signal.get("top10CurrentChangeOk"),
                    "top10ReclaimOk": signal.get("top10ReclaimOk"),
                    "top10VolumeOk": signal.get("top10VolumeOk"),
                    "top10DelayOk": signal.get("top10DelayOk"),
                    "collectorChange1hPct": signal.get("collectorChange1hPct"),
                    "top10CurrentChange1hPct": signal.get("top10CurrentChange1hPct"),
                })
            if state.get("assetQty", 0) > 0:
                pass
            elif (open_count < CONFIG["microMaxPositions"] or params.get("shadow_only")) and signal.get("buy") and entry_allowed:
                state["top10Params"] = dict(params)
                state["top10SessionActive"] = True
                state["top10SessionSeen"] = True
                if params.get("shadow_only"):
                    state["top10ShadowEntryTaken"] = True
                await self._micro_buy(inst_id, state, price, signal, strategy, state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, strategy))
            elif rank_1h is not None and not was_seen and state.get("assetQty", 0) <= 0 and signal.get("top10DelayOk"):
                state["top10SessionActive"] = True
                state["top10SessionSeen"] = True
                await self._save_micro_state(state_key, state)
            elif rank_1h is not None and not was_seen and state.get("assetQty", 0) <= 0:
                await self._save_micro_state(state_key, state)
        return open_count

    async def _apply_micro_strategy4(self, archive_sources, states, positions, open_count):
        active_inst_ids = [
            key.split("::", 1)[1]
            for key, state in states.items()
            if key.startswith("strategy4_breakout_confirmation::") and state.get("assetQty", 0) > 0
        ]
        source_items = sorted(
            archive_sources.items(),
            key=lambda item: item[1]["signal"].get("trendScore", 0),
            reverse=True,
        )
        active_set = set(active_inst_ids)
        ordered_items = [(inst_id, archive_sources[inst_id]) for inst_id in active_inst_ids if inst_id in archive_sources]
        ordered_items.extend((inst_id, source) for inst_id, source in source_items if inst_id not in active_set)
        for inst_id, source in ordered_items:
            state_key = micro_state_key("strategy4_breakout_confirmation", inst_id)
            state = states.get(state_key, new_micro_state())
            signal = micro_strategy4_signal({"instId": inst_id, "_pct24": source["signal"].get("pct24", 0), "_quoteVol": source["signal"].get("quoteVolume24h", 0)}, source["candles"])
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy4_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], "strategy4_breakout_confirmation", state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, "strategy4_breakout_confirmation"))
                    await self._save_micro_state(state_key, state)
            elif open_count < CONFIG["microMaxPositions"] and signal.get("buy"):
                await self._micro_buy(inst_id, state, price, signal, "strategy4_breakout_confirmation", state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, "strategy4_breakout_confirmation"))
        return open_count

    async def _apply_micro_strategy41(self, archive_sources, states, positions, open_count):
        strategy = "strategy4.1_breakout_confirmation"
        active_inst_ids = [
            key.split("::", 1)[1]
            for key, state in states.items()
            if key.startswith(f"{strategy}::") and state.get("assetQty", 0) > 0
        ]
        source_items = sorted(archive_sources.items(), key=lambda item: item[1]["signal"].get("trendScore", 0), reverse=True)
        active_set = set(active_inst_ids)
        ordered_items = [(inst_id, archive_sources[inst_id]) for inst_id in active_inst_ids if inst_id in archive_sources]
        ordered_items.extend((inst_id, source) for inst_id, source in source_items if inst_id not in active_set)
        for inst_id, source in ordered_items:
            state_key = micro_state_key(strategy, inst_id)
            state = states.get(state_key, new_micro_state())
            signal = micro_strategy41_signal({"instId": inst_id, "_pct24": source["signal"].get("pct24", 0), "_quoteVol": source["signal"].get("quoteVolume24h", 0), "bidPx": source.get("ticker", {}).get("bidPx"), "askPx": source.get("ticker", {}).get("askPx")}, source["candles"])
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy41_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                    await self._save_micro_state(state_key, state)
            elif open_count < CONFIG["microMaxPositions"] and signal.get("buy"):
                await self._micro_buy(inst_id, state, price, signal, strategy, state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, strategy))
        return open_count


    async def _apply_micro_strategy9(self, ranking1h, archive_sources, states, positions, open_count):
        strategy = "strategy9_ema9_bounce_low_heat"
        top_inst_ids = [signal["instId"] for signal in ranking1h[:CONFIG["microStrategy9TopN"]]]
        active_inst_ids = [
            key.split("::", 1)[1]
            for key, state in states.items()
            if key.startswith(f"{strategy}::") and state.get("assetQty", 0) > 0
        ]
        for inst_id in dict.fromkeys(top_inst_ids + active_inst_ids):
            source = archive_sources.get(inst_id)
            if not source:
                continue
            state_key = micro_state_key(strategy, inst_id)
            state = states.get(state_key, new_micro_state())
            signal = micro_strategy9_signal(
                {
                    "instId": inst_id,
                    "_pct24": source["signal"].get("pct24", 0),
                    "_quoteVol": source["signal"].get("quoteVolume24h", 0),
                    "bidPx": source.get("ticker", {}).get("bidPx"),
                    "askPx": source.get("ticker", {}).get("askPx"),
                },
                source["candles"],
            )
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy9_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                    await self._save_micro_state(state_key, state)
            elif open_count < CONFIG["microMaxPositions"] and signal.get("buy"):
                await self._micro_buy(inst_id, state, price, signal, strategy, state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, strategy))
        return open_count

    async def _apply_micro_strategy18(self, ranking2h, archive_sources, states, positions, open_count):
        strategy = "s18_top2h_retest_runner"
        top_inst_ids = [signal["instId"] for signal in ranking2h[:CONFIG["microStrategy18TopN"]]]
        active_inst_ids = [
            key.split("::", 1)[1]
            for key, state in states.items()
            if key.startswith(f"{strategy}::") and state.get("assetQty", 0) > 0
        ]
        for inst_id in dict.fromkeys(top_inst_ids + active_inst_ids):
            source = archive_sources.get(inst_id)
            if not source:
                continue
            state_key = micro_state_key(strategy, inst_id)
            state = states.get(state_key, new_micro_state())
            signal = micro_strategy18_signal(
                {
                    "instId": inst_id,
                    "_pct24": source["signal"].get("pct24", 0),
                    "_quoteVol": source["signal"].get("quoteVolume24h", 0),
                    "bidPx": source.get("ticker", {}).get("bidPx"),
                    "askPx": source.get("ticker", {}).get("askPx"),
                },
                source["candles"],
            )
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy18_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                    await self._save_micro_state(state_key, state)
            elif open_count < CONFIG["microMaxPositions"] and signal.get("buy"):
                await self._micro_buy(inst_id, state, price, signal, strategy, state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, strategy))
        return open_count


    async def _apply_micro_strategy20(self, ranking12h, archive_sources, states, positions, open_count):
        strategy = "strategy20_6h12h_cool_vwap_reclaim"
        top_inst_ids = [signal["instId"] for signal in ranking12h[:CONFIG["microStrategy20TopN"]]]
        active_inst_ids = [
            key.split("::", 1)[1]
            for key, state in states.items()
            if key.startswith(f"{strategy}::") and state.get("assetQty", 0) > 0
        ]
        for inst_id in dict.fromkeys(top_inst_ids + active_inst_ids):
            source = archive_sources.get(inst_id)
            if not source:
                continue
            state_key = micro_state_key(strategy, inst_id)
            state = states.get(state_key, new_micro_state())
            signal = micro_strategy20_signal(
                {
                    "instId": inst_id,
                    "_pct24": source["signal"].get("pct24", 0),
                    "_quoteVol": source["signal"].get("quoteVolume24h", 0),
                    "bidPx": source.get("ticker", {}).get("bidPx"),
                    "askPx": source.get("ticker", {}).get("askPx"),
                },
                source["candles"],
            )
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy20_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                    await self._save_micro_state(state_key, state)
            elif open_count < CONFIG["microMaxPositions"] and signal.get("buy"):
                await self._micro_buy(inst_id, state, price, signal, strategy, state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, strategy))
        return open_count


    async def _apply_micro_strategy21(self, ranking1h, ranking3h, ranking6h, archive_sources, states, positions, open_count):
        strategy = "strategy21_multi_tf_intersection_ema9_bounce"
        top_n = CONFIG["microStrategy21TopN"]
        top1 = {signal["instId"] for signal in ranking1h[:top_n]}
        top3 = {signal["instId"] for signal in ranking3h[:top_n]}
        top6 = {signal["instId"] for signal in ranking6h[:top_n]}
        top_inst_ids = [signal["instId"] for signal in ranking1h if signal["instId"] in top1 & top3 & top6]
        active_inst_ids = [
            key.split("::", 1)[1]
            for key, state in states.items()
            if key.startswith(f"{strategy}::") and state.get("assetQty", 0) > 0
        ]
        for inst_id in dict.fromkeys(top_inst_ids + active_inst_ids):
            source = archive_sources.get(inst_id)
            if not source:
                continue
            state_key = micro_state_key(strategy, inst_id)
            state = states.get(state_key, new_micro_state())
            signal = micro_strategy21_signal(
                {
                    "instId": inst_id,
                    "_pct24": source["signal"].get("pct24", 0),
                    "_quoteVol": source["signal"].get("quoteVolume24h", 0),
                    "bidPx": source.get("ticker", {}).get("bidPx"),
                    "askPx": source.get("ticker", {}).get("askPx"),
                },
                source["candles"],
            )
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy21_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                    await self._save_micro_state(state_key, state)
            elif open_count < CONFIG["microMaxPositions"] and signal.get("buy"):
                await self._micro_buy(inst_id, state, price, signal, strategy, state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, strategy))
        return open_count

    async def _apply_micro_strategy22(self, ranking2h, archive_sources, states, positions, open_count):
        strategy = "strategy22_2h_strength_breakout_retest"
        top_inst_ids = [signal["instId"] for signal in ranking2h[:CONFIG["microStrategy22TopN"]]]
        active_inst_ids = [
            key.split("::", 1)[1]
            for key, state in states.items()
            if key.startswith(f"{strategy}::") and state.get("assetQty", 0) > 0
        ]
        for inst_id in dict.fromkeys(top_inst_ids + active_inst_ids):
            source = archive_sources.get(inst_id)
            if not source:
                continue
            state_key = micro_state_key(strategy, inst_id)
            state = states.get(state_key, new_micro_state())
            signal = micro_strategy22_signal(
                {
                    "instId": inst_id,
                    "_pct24": source["signal"].get("pct24", 0),
                    "_quoteVol": source["signal"].get("quoteVolume24h", 0),
                    "bidPx": source.get("ticker", {}).get("bidPx"),
                    "askPx": source.get("ticker", {}).get("askPx"),
                },
                source["candles"],
            )
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy22_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                    await self._save_micro_state(state_key, state)
            elif open_count < CONFIG["microMaxPositions"] and signal.get("buy"):
                await self._micro_buy(inst_id, state, price, signal, strategy, state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, strategy))
        return open_count

    async def _apply_micro_strategy23(self, ranking1h, archive_sources, states, positions, open_count):
        strategy = "strategy23_top1h_clean_early_breakout"
        top_inst_ids = [signal["instId"] for signal in ranking1h[:CONFIG["microStrategy23TopN"]]]
        active_inst_ids = [
            key.split("::", 1)[1]
            for key, state in states.items()
            if key.startswith(f"{strategy}::") and state.get("assetQty", 0) > 0
        ]
        for inst_id in dict.fromkeys(top_inst_ids + active_inst_ids):
            source = archive_sources.get(inst_id)
            if not source:
                continue
            state_key = micro_state_key(strategy, inst_id)
            state = states.get(state_key, new_micro_state())
            signal = micro_strategy23_signal(
                {
                    "instId": inst_id,
                    "_pct24": source["signal"].get("pct24", 0),
                    "_quoteVol": source["signal"].get("quoteVolume24h", 0),
                    "bidPx": source.get("ticker", {}).get("bidPx"),
                    "askPx": source.get("ticker", {}).get("askPx"),
                },
                source["candles"],
            )
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy23_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                    await self._save_micro_state(state_key, state)
            elif open_count < CONFIG["microMaxPositions"] and signal.get("buy"):
                await self._micro_buy(inst_id, state, price, signal, strategy, state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, strategy))
        return open_count

    async def _apply_micro_strategy24(self, ranking1h, archive_sources, states, positions, open_count):
        strategy = "strategy24_top1h_delay_rank5_chg1_5"
        top_entry = {signal["instId"]: rank for rank, signal in enumerate(ranking1h[:CONFIG["microStrategy24TopN"]], start=1)}
        top_session = {signal["instId"]: rank for rank, signal in enumerate(ranking1h[:CONFIG["microStrategy24SessionTopN"]], start=1)}
        carried_inst_ids = [
            key.split("::", 1)[1]
            for key, state in states.items()
            if key.startswith(f"{strategy}::") and (state.get("assetQty", 0) > 0 or state.get("strategy24PendingEntry"))
        ]
        for inst_id in dict.fromkeys(list(top_entry.keys()) + carried_inst_ids):
            source = archive_sources.get(inst_id)
            if not source:
                continue
            state_key = micro_state_key(strategy, inst_id)
            state = states.get(state_key, new_micro_state())
            rank_1h = top_session.get(inst_id)
            signal = micro_strategy24_signal(
                {
                    "instId": inst_id,
                    "_pct24": source["signal"].get("pct24", 0),
                    "_quoteVol": source["signal"].get("quoteVolume24h", 0),
                    "bidPx": source.get("ticker", {}).get("bidPx"),
                    "askPx": source.get("ticker", {}).get("askPx"),
                },
                source["candles"],
                rank_1h=rank_1h,
            )
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy24_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                    await self._save_micro_state(state_key, state)
            elif state.get("strategy24PendingEntry"):
                pending = state.get("strategy24PendingEntry") or {}
                ready_time = pending.get("readyTime", 0)
                expires_at = pending.get("expiresAt", 0)
                if open_count < CONFIG["microMaxPositions"] and signal.get("time", 0) >= ready_time and signal.get("strategy24SessionStillTop10"):
                    signal["buy"] = True
                    signal["reason"] = "strategy24_delay1_rank5_chg1_5_confirmed"
                    state.pop("strategy24PendingEntry", None)
                    await self._micro_buy(inst_id, state, price, signal, strategy, state_key)
                    open_count += 1
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                elif signal.get("time", 0) > expires_at or not signal.get("strategy24SessionStillTop10"):
                    state.pop("strategy24PendingEntry", None)
                    await self._save_micro_state(state_key, state)
            elif signal.get("strategy24SeedOk"):
                delay_ms = CONFIG["microStrategy24DelayBars"] * micro_bar_minutes() * 60 * 1000
                state["strategy24PendingEntry"] = {
                    "time": signal["time"],
                    "readyTime": signal["time"] + delay_ms,
                    "expiresAt": signal["time"] + delay_ms + (micro_bar_minutes() * 60 * 1000),
                    "entryRank1h": rank_1h,
                    "entryChange1hPct": signal.get("pct1h", 0),
                    "entryPrice": price,
                }
                await self._save_micro_state(state_key, state)
        return open_count

    async def _apply_micro_strategy2(self, ranking1h, archive_sources, states, positions, open_count):
        top_inst_ids = [signal["instId"] for signal in ranking1h[:CONFIG["microStrategy2TopN"]]]
        active_inst_ids = [
            key.split("::", 1)[1]
            for key, state in states.items()
            if key.startswith("strategy2::") and state.get("assetQty", 0) > 0
        ]
        for inst_id in dict.fromkeys(top_inst_ids + active_inst_ids):
            source = archive_sources.get(inst_id)
            if not source:
                continue
            signal = dict(source["signal"])
            state_key = micro_state_key("strategy2", inst_id)
            state = states.get(state_key, new_micro_state())
            candles = source["candles"]
            price = candles[-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy2_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], "strategy2", state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, "strategy2"))
                    await self._save_micro_state(state_key, state)
            elif open_count < CONFIG["microMaxPositions"] and micro_strategy2_should_enter(signal):
                signal["reason"] = "strategy2_surge_momentum"
                await self._micro_buy(inst_id, state, price, signal, "strategy2", state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, "strategy2"))
        return open_count

    async def _apply_micro_strategy21_surge(self, ranking1h, archive_sources, states, positions, open_count):
        strategy = "strategy2.1_surge_momentum"
        top_inst_ids = [signal["instId"] for signal in ranking1h[:CONFIG["microStrategy21SurgeTopN"]]]
        active_inst_ids = [key.split("::", 1)[1] for key, state in states.items() if key.startswith(f"{strategy}::") and state.get("assetQty", 0) > 0]
        for inst_id in dict.fromkeys(top_inst_ids + active_inst_ids):
            source = archive_sources.get(inst_id)
            if not source:
                continue
            signal = micro_strategy21_surge_signal({**dict(source["signal"]), "bidPx": source.get("ticker", {}).get("bidPx"), "askPx": source.get("ticker", {}).get("askPx")})
            state_key = micro_state_key(strategy, inst_id)
            state = states.get(state_key, new_micro_state())
            price = source["candles"][-1]["close"]
            if state.get("assetQty", 0) > 0:
                update_micro_position_state(state, price, signal)
                if micro_strategy21_surge_should_exit(signal, state, price):
                    await self._micro_sell(inst_id, state, signal.get("exitPrice", price), signal, signal["exitReason"], strategy, state_key)
                    open_count = max(0, open_count - 1)
                else:
                    positions.append(micro_position_row(inst_id, state, price, signal, strategy))
                    await self._save_micro_state(state_key, state)
            elif open_count < CONFIG["microMaxPositions"] and signal.get("buy"):
                await self._micro_buy(inst_id, state, price, signal, strategy, state_key)
                open_count += 1
                positions.append(micro_position_row(inst_id, state, price, signal, strategy))
        return open_count


    async def _archive_micro_surge_if_due(self, ranking12h, archive_sources):
        now = datetime.now(timezone.utc)
        scan_hour = now.replace(minute=0, second=0, microsecond=0)
        if self.micro_surge_last_archive_hour == scan_hour.isoformat():
            return
        top_rows = []
        bars = CONFIG["microSurgeArchiveHours"] * micro_bars_per_hour()
        for rank, signal in enumerate(ranking12h[:CONFIG["microSurgeArchiveTopN"]], start=1):
            source = archive_sources.get(signal["instId"])
            if not source:
                continue
            candles = source["candles"][-bars:]
            top_rows.append((rank, signal, candles))
        if not top_rows:
            return
        try:
            await self._save_micro_surge_archive(scan_hour, top_rows)
            self.micro_surge_last_archive_hour = scan_hour.isoformat()
            self.micro_surge_archive_status = {
                "lastRunAt": now.isoformat(),
                "lastHour": scan_hour.isoformat(),
                "saved": len(top_rows),
                "lastError": "",
            }
        except Exception as exc:
            self.micro_surge_archive_status = {
                "lastRunAt": now.isoformat(),
                "lastHour": scan_hour.isoformat(),
                "saved": 0,
                "lastError": str(exc),
            }
            raise

    async def _save_micro_surge_archive(self, scan_hour, rows):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM crypto_micro_surge_archive WHERE scan_hour=$1", scan_hour)
                for rank, signal, candles in rows:
                    await conn.execute(
                        """INSERT INTO crypto_micro_surge_archive(
                               scan_hour,rank,inst_id,price,pct5,pct15,pct1h,pct12h,pct24,
                               quote_volume_24h,volume_ratio,distance_ma60_pct,candles,signal
                           ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14::jsonb)""",
                        scan_hour,
                        rank,
                        signal["instId"],
                        signal["price"],
                        signal["pct5"],
                        signal["pct15"],
                        signal["pct1h"],
                        signal["pct12h"],
                        signal["pct24"],
                        signal["quoteVolume24h"],
                        signal["volumeRatio"],
                        signal["distanceMa60Pct"],
                        json.dumps([compact_candle(candle) for candle in candles]),
                        json.dumps(compact_micro_signal(signal)),
                    )

    async def _load_micro_states(self):
        async with self.pool.acquire() as conn:
            records = await conn.fetch("SELECT inst_id,state FROM crypto_micro_state")
        states = {}
        for record in records:
            raw_state = record["state"]
            states[record["inst_id"]] = raw_state if isinstance(raw_state, dict) else json.loads(raw_state)
        return states

    async def _save_micro_state(self, inst_id, state):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO crypto_micro_state(inst_id,state,updated_at)
                   VALUES($1,$2::jsonb,NOW())
                   ON CONFLICT(inst_id) DO UPDATE SET state=$2::jsonb, updated_at=NOW()""",
                inst_id,
                json.dumps(state),
            )

    async def _micro_buy(self, inst_id, state, price, signal, strategy="strategy1", state_key=None):
        signal["strategy"] = strategy
        margin = CONFIG["microMarginUSDT"]
        quote = margin * CONFIG["microLeverage"]
        qty = quote / price
        state.update({
            "assetQty": qty,
            "avgEntry": price,
            "margin": margin,
            "leverage": CONFIG["microLeverage"],
            "notional": quote,
            "entryTime": signal["time"],
            "entryReason": signal["reason"],
            "peakPrice": price,
            "belowMa60Count": 0,
            "tp1Taken": False,
            "tp2Taken": False,
            "breakevenStopPrice": 0,
            "trades": state.get("trades", 0) + 1,
        })
        await self._save_micro_state(state_key or inst_id, state)
        trade_id = await self._log_micro_trade(inst_id, "BUY", price, qty, quote, signal, signal["reason"], strategy)
        await self._save_micro_trade_window(trade_id, inst_id, "BUY", "entry_pre_1h", signal["pre1hCandles"], signal)

    async def _micro_sell(self, inst_id, state, price, signal, reason, strategy="strategy1", state_key=None):
        signal["strategy"] = strategy
        current_qty = state.get("assetQty", 0)
        fraction = min(1.0, max(0.0, float(signal.get("exitFraction", 1.0))))
        qty = current_qty * fraction
        quote = qty * price
        pnl = quote - qty * state.get("avgEntry", 0)
        remaining_qty = max(0.0, current_qty - qty)
        full_exit = remaining_qty <= current_qty * 0.000001
        state["assetQty"] = 0 if full_exit else remaining_qty
        if full_exit:
            state["avgEntry"] = 0
            state["peakPrice"] = 0
            state["belowMa60Count"] = 0
            state["tp1Taken"] = False
            state["tp2Taken"] = False
            state["breakevenStopPrice"] = 0
            state["lastExitTime"] = signal["time"]
            state["closedTrades"] = state.get("closedTrades", 0) + 1
            state["wins"] = state.get("wins", 0) + (1 if pnl > 0 else 0)
            state["pendingExitContextTradeId"] = None
            state["pendingExitContextUntil"] = signal["time"] + 60 * 60 * 1000
        else:
            state["peakPrice"] = max(state.get("peakPrice", price), price)
        state["realizedPnl"] = state.get("realizedPnl", 0) + pnl
        state["trades"] = state.get("trades", 0) + 1
        await self._save_micro_state(state_key or inst_id, state)
        trade_id = await self._log_micro_trade(inst_id, "SELL", price, qty, quote, signal, reason, strategy)
        await self._save_micro_trade_window(trade_id, inst_id, "SELL", "exit_pre_1h", signal["pre1hCandles"], signal)
        if full_exit:
            state["pendingExitContextTradeId"] = trade_id
            await self._save_micro_state(state_key or inst_id, state)

    async def _log_micro_trade(self, inst_id, side, price, qty, quote, signal, reason, strategy="strategy1"):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO crypto_micro_trades(inst_id,strategy,side,price,quantity,quote_amount,ma60,volume_ratio,pct5,pct15,reason)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   RETURNING id""",
                inst_id, strategy, side, price, qty, quote, signal["ma60"], signal["volumeRatio"], signal["pct5"], signal["pct15"], reason,
            )
        return row["id"]

    async def _save_micro_trade_window(self, trade_id, inst_id, side, window_type, candles, signal):
        payload = json.dumps([compact_candle(candle) for candle in candles])
        signal_payload = json.dumps(compact_micro_signal(signal))
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO crypto_micro_trade_windows(trade_id,inst_id,side,window_type,candles,signal)
                   VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb)
                   ON CONFLICT(trade_id,window_type) DO UPDATE
                   SET captured_at=NOW(), candles=$5::jsonb, signal=$6::jsonb""",
                trade_id, inst_id, side, window_type, payload, signal_payload,
            )

    async def _maybe_capture_exit_post_window(self, inst_id, state, candles, signal):
        trade_id = state.get("pendingExitContextTradeId")
        until = state.get("pendingExitContextUntil")
        if not trade_id or not until or signal["time"] < until:
            return False
        post_candles = [candle for candle in candles if state.get("lastExitTime", 0) < candle["closeTime"] <= until]
        bars_per_hour = micro_bars_per_hour()
        if len(post_candles) < bars_per_hour:
            return False
        await self._save_micro_trade_window(trade_id, inst_id, "SELL", "exit_post_1h", post_candles[-bars_per_hour:], signal)
        state["pendingExitContextTradeId"] = None
        state["pendingExitContextUntil"] = None
        await self._save_micro_state(inst_id, state)
        return True

    async def prune_old_micro_records(self, cutoff_iso):
        cutoff = parse_datetime(cutoff_iso)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        async with self.pool.acquire() as conn:
            deleted_trades = await conn.fetchval(
                "WITH deleted AS (DELETE FROM crypto_micro_trades WHERE ts < $1 RETURNING 1) SELECT COUNT(*) FROM deleted",
                cutoff,
            )
            await conn.execute(
                """DELETE FROM crypto_micro_trade_windows w
                   WHERE NOT EXISTS (SELECT 1 FROM crypto_micro_trades t WHERE t.id=w.trade_id)"""
            )
            trade_rows = await conn.fetch(
                """SELECT inst_id,side,price,quantity,quote_amount
                   FROM crypto_micro_trades
                   ORDER BY ts ASC, id ASC"""
            )
            state_rows = await conn.fetch("SELECT inst_id,state FROM crypto_micro_state")
            states = {
                row["inst_id"]: row["state"] if isinstance(row["state"], dict) else json.loads(row["state"])
                for row in state_rows
            }
            stats = rebuild_micro_stats(trade_rows)
            reset_states = 0
            for inst_id, state in list(states.items()):
                entry_time = state.get("entryTime") or 0
                if state.get("assetQty", 0) and entry_time and entry_time < cutoff_ms:
                    state = new_micro_state()
                    reset_states += 1
                inst_stats = stats.get(inst_id, {})
                state["realizedPnl"] = inst_stats.get("realizedPnl", 0.0)
                state["trades"] = inst_stats.get("trades", 0)
                state["closedTrades"] = inst_stats.get("closedTrades", 0)
                state["wins"] = inst_stats.get("wins", 0)
                states[inst_id] = state
                await conn.execute(
                    """INSERT INTO crypto_micro_state(inst_id,state,updated_at)
                       VALUES($1,$2::jsonb,NOW())
                       ON CONFLICT(inst_id) DO UPDATE SET state=$2::jsonb, updated_at=NOW()""",
                    inst_id,
                    json.dumps(state),
                )
        await self.run_micro_once()
        return {"cutoff": cutoff.isoformat(), "deletedTrades": deleted_trades, "resetStates": reset_states}

    async def refresh_micro_strategy_performance_12h(self):
        async with self.pool.acquire() as conn:
            trade_rows = [dict(row) for row in await conn.fetch(
                "SELECT id,ts,inst_id,strategy,side,price,quantity,quote_amount FROM crypto_micro_trades ORDER BY ts ASC, id ASC"
            )]
        records = build_micro_entry_exit_records(trade_rows)
        history = build_micro_strategy_performance_12h_history(records, datetime.now(timezone.utc), CONFIG.get("microActiveStrategies", []))
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for window in history:
                    for row in window["rows"]:
                        await conn.execute(
                            """INSERT INTO crypto_micro_strategy_performance_12h(
                                   window_start,window_end,strategy,entries,closed_trades,wins,losses,open_trades,
                                   realized_pnl,avg_pnl_roe_pct,win_rate,updated_at
                               ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,NOW())
                               ON CONFLICT(window_start,strategy) DO UPDATE SET
                                   window_end=$2, entries=$4, closed_trades=$5, wins=$6, losses=$7,
                                   open_trades=$8, realized_pnl=$9, avg_pnl_roe_pct=$10,
                                   win_rate=$11, updated_at=NOW()""",
                            window["windowStart"],
                            window["windowEnd"],
                            row["strategy"],
                            row["entries"],
                            row["closedTrades"],
                            row["wins"],
                            row["losses"],
                            row["openTrades"],
                            row["realizedPnl"],
                            row["avgPnlRoePct"],
                            row["winRate"],
                        )
            rows = [dict(row) for row in await conn.fetch(
                """SELECT window_start,window_end,strategy,entries,closed_trades,wins,losses,open_trades,
                          realized_pnl,avg_pnl_roe_pct,win_rate,updated_at
                   FROM crypto_micro_strategy_performance_12h
                   ORDER BY window_start DESC, realized_pnl DESC, strategy ASC
                   LIMIT 720"""
            )]
        return format_micro_strategy_performance_12h_history(rows)

    def status(self):
        markets = []
        for symbol in CONFIG["symbols"]:
            markets.append(self.snapshots.get(symbol) or empty_snapshot(symbol, self.running, self.last_error, self.last_run_at))
        return {"running": self.running, "markets": markets, "config": CONFIG, "lastError": self.last_error, "lastRunAt": self.last_run_at, "backfill": self.backfill_status}

    def micro_status(self):
        return {
            "running": self.micro_running,
            "lastRunAt": self.micro_last_run_at,
            "lastError": self.micro_last_error,
            "candidates": self.micro_candidates,
            "ranking12h": getattr(self, "micro_ranking12h", []),
            "ranking1h": getattr(self, "micro_ranking1h", []),
            "positions": self.micro_positions,
            "top10Debug": getattr(self, "micro_top10_debug", []),
            "surgeArchive": self.micro_surge_archive_status,
            "config": CONFIG,
        }


OKX_LIVE_LOG_GLOB = os.environ.get("OKX_LIVE_PERFORMANCE_LOG_GLOB", "data/okx_*live*_log.jsonl")
OKX_LIVE_STATE_GLOB = os.environ.get("OKX_LIVE_PERFORMANCE_STATE_GLOB", "data/okx_*live*_state.json")


def _live_strategy_from_row(row):
    signal = row.get("signal") if isinstance(row.get("signal"), dict) else {}
    return row.get("strategy") or signal.get("strategy") or "top10v1_rank5_chg3_10_sl1_trail09_t12"


def read_okx_live_log_rows(log_glob: str = OKX_LIVE_LOG_GLOB):
    rows = []
    for path in sorted(Path(".").glob(log_glob)):
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row["_source"] = str(path)
            row["_line"] = line_no
            rows.append(row)
    rows.sort(key=lambda row: row.get("ts") or "")
    return rows


def read_okx_live_states(state_glob: str = OKX_LIVE_STATE_GLOB):
    states = []
    for path in sorted(Path(".").glob(state_glob)):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            state["_source"] = str(path)
            states.append(state)
        except Exception:
            continue
    return states


def build_okx_live_trade_records(log_rows, margin_default=None):
    open_lots = {}
    closed = []
    events = []
    current_margin = float(margin_default or CONFIG.get("microMarginUSDT") or 2)
    current_leverage = float(CONFIG.get("microLeverage") or 1)
    for row in sorted(log_rows, key=lambda r: r.get("ts") or ""):
        event = row.get("event")
        if event == "start":
            current_margin = float(row.get("marginUSDT") or current_margin or 2)
            current_leverage = float(row.get("leverage") or current_leverage or 1)
        if event not in {"BUY", "SELL", "NOON_STOP_MARKET_CLOSE"}:
            continue
        inst_id = row.get("instId") or row.get("inst_id")
        if not inst_id:
            continue
        ts = row.get("ts")
        if event == "BUY":
            sizing = row.get("sizing") if isinstance(row.get("sizing"), dict) else {}
            sz = float(row.get("sz") or sizing.get("roundedSz") or 0)
            ct_val = float(sizing.get("ctVal") or 0)
            fill = float(row.get("fillPrice") or row.get("price") or 0)
            notional = sz * ct_val * fill if sz and ct_val and fill else 0.0
            lot = {
                "strategy": _live_strategy_from_row(row),
                "instId": inst_id,
                "entryTime": ts,
                "entryPrice": fill,
                "sz": sz,
                "ctVal": ct_val,
                "notional": notional,
                "margin": float(row.get("marginUSDT") or current_margin or (notional / current_leverage if current_leverage else 0) or 0),
                "leverage": current_leverage,
                "orderId": row.get("orderId"),
                "hardStopAlgoId": row.get("hardStopAlgoId"),
                "hardStopPrice": row.get("hardStopPrice"),
                "entryReason": (row.get("signal") or {}).get("reason") if isinstance(row.get("signal"), dict) else row.get("reason"),
            }
            open_lots.setdefault(inst_id, []).append(lot)
            events.append({"time": ts, "event": "BUY", "strategy": lot["strategy"], "instId": inst_id, "price": fill, "pnlUsd": None, "pnlPct": None, "reason": lot["entryReason"], "orderId": lot["orderId"], "hardStopAlgoId": lot["hardStopAlgoId"]})
            continue
        lot = open_lots.get(inst_id, []).pop(0) if open_lots.get(inst_id) else None
        fill = float(row.get("fillPrice") or row.get("price") or 0)
        pnl = float(row.get("realizedPnl") or 0)
        margin = float((lot or {}).get("margin") or current_margin or 0)
        pnl_pct = (pnl / margin * 100) if margin else 0.0
        record = {
            "strategy": (lot or {}).get("strategy") or _live_strategy_from_row(row),
            "instId": inst_id,
            "entryTime": (lot or {}).get("entryTime"),
            "exitTime": ts,
            "entryPrice": (lot or {}).get("entryPrice"),
            "exitPrice": fill,
            "pnlUsd": rnd(pnl),
            "pnlPct": rnd(pnl_pct),
            "margin": margin,
            "notional": (lot or {}).get("notional"),
            "sz": row.get("sz") or (lot or {}).get("sz"),
            "exitReason": row.get("reason"),
            "entryOrderId": (lot or {}).get("orderId"),
            "exitOrderId": row.get("orderId"),
            "hardStopAlgoId": (lot or {}).get("hardStopAlgoId"),
            "source": row.get("_source"),
        }
        closed.append(record)
        events.append({"time": ts, "event": event, "strategy": record["strategy"], "instId": inst_id, "price": fill, "pnlUsd": record["pnlUsd"], "pnlPct": record["pnlPct"], "reason": record["exitReason"], "orderId": record["exitOrderId"]})
    open_positions = []
    for lots in open_lots.values():
        for lot in lots:
            open_positions.append({
                "strategy": lot["strategy"],
                "instId": lot["instId"],
                "entryTime": lot["entryTime"],
                "entryPrice": lot["entryPrice"],
                "margin": lot["margin"],
                "notional": lot["notional"],
                "sz": lot["sz"],
                "hardStopPrice": lot["hardStopPrice"],
                "hardStopAlgoId": lot["hardStopAlgoId"],
                "entryReason": lot["entryReason"],
            })
    return {"closedTrades": closed, "openPositions": open_positions, "events": events}


def summarize_okx_live_performance(log_rows, states=None):
    records = build_okx_live_trade_records(log_rows)
    closed = records["closedTrades"]
    open_positions = records["openPositions"]
    total_pnl = sum(float(r.get("pnlUsd") or 0) for r in closed)
    wins = sum(1 for r in closed if float(r.get("pnlUsd") or 0) > 0)
    losses = sum(1 for r in closed if float(r.get("pnlUsd") or 0) <= 0)
    total_margin = sum(float(r.get("margin") or 0) for r in closed)
    strategy_map = {}
    for r in closed:
        item = strategy_map.setdefault(r["strategy"], {"strategy": r["strategy"], "closedTrades": 0, "wins": 0, "losses": 0, "pnlUsd": 0.0, "margin": 0.0})
        item["closedTrades"] += 1
        item["pnlUsd"] += float(r.get("pnlUsd") or 0)
        item["margin"] += float(r.get("margin") or 0)
        if float(r.get("pnlUsd") or 0) > 0:
            item["wins"] += 1
        else:
            item["losses"] += 1
    for item in strategy_map.values():
        item["pnlUsd"] = rnd(item["pnlUsd"])
        item["pnlPct"] = rnd((item["pnlUsd"] / item["margin"] * 100) if item["margin"] else 0)
        item["winRate"] = rnd((item["wins"] / item["closedTrades"] * 100) if item["closedTrades"] else 0)
    return {
        "summary": {
            "closedTrades": len(closed),
            "openPositions": len(open_positions),
            "wins": wins,
            "losses": losses,
            "winRate": rnd((wins / len(closed) * 100) if closed else 0),
            "pnlUsd": rnd(total_pnl),
            "pnlPct": rnd((total_pnl / total_margin * 100) if total_margin else 0),
            "totalMargin": rnd(total_margin),
            "buyEvents": sum(1 for r in log_rows if r.get("event") == "BUY"),
            "sellEvents": sum(1 for r in log_rows if r.get("event") in {"SELL", "NOON_STOP_MARKET_CLOSE"}),
            "hardStopProtectedBuys": sum(1 for r in log_rows if r.get("event") == "BUY" and r.get("hardStopAlgoId")),
        },
        "byStrategy": sorted(strategy_map.values(), key=lambda x: x["strategy"]),
        "closedTrades": list(reversed(closed))[:200],
        "openPositions": open_positions,
        "events": list(reversed(records["events"]))[:200],
        "states": states or [],
    }


async def fetch_okx_account_snapshot():
    try:
        from okx_strategy22_live_pilot import OkxCredentials, OkxPrivateClient
        creds = OkxCredentials.from_env()
        async with httpx.AsyncClient(timeout=20) as client:
            okx = OkxPrivateClient(client, creds)
            data = await okx.request("GET", "/api/v5/account/balance")
        details = data.get("data", [{}])[0].get("details", [])
        usdt = next((d for d in details if d.get("ccy") == "USDT"), {})
        total_eq = float(usdt.get("eq") or usdt.get("cashBal") or 0)
        avail = float(usdt.get("availBal") or usdt.get("availEq") or 0)
        frozen = float(usdt.get("frozenBal") or 0)
        return {"ok": True, "simulated": creds.simulated, "currency": "USDT", "equity": rnd(total_eq), "available": rnd(avail), "frozen": rnd(frozen), "rawUpdatedAt": data.get("data", [{}])[0].get("uTime")}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "currency": "USDT", "equity": None, "available": None, "frozen": None}


def normalize_okx_position_snapshot(rows):
    positions = []
    for row in rows or []:
        try:
            pos = float(row.get("pos") or 0)
        except Exception:
            pos = 0.0
        if not pos:
            continue
        mark_or_last = float(row.get("markPx") or row.get("last") or row.get("avgPx") or 0)
        notional = float(row.get("notionalUsd") or 0)
        try:
            ct_val = abs(notional / (mark_or_last * abs(pos))) if mark_or_last and pos else 1.0
        except Exception:
            ct_val = 1.0
        positions.append({
            "strategy": "OKX exchange position",
            "instId": row.get("instId"),
            "entryTime": datetime.fromtimestamp(float(row.get("cTime") or row.get("uTime") or 0) / 1000, timezone.utc).isoformat(timespec="seconds") if (row.get("cTime") or row.get("uTime")) else None,
            "entryPrice": float(row.get("avgPx") or 0),
            "margin": float(row.get("margin") or 0),
            "notional": notional,
            "sz": pos,
            "markPrice": float(row.get("markPx") or 0),
            "lastPrice": float(row.get("last") or 0),
            "unrealizedPnl": float(row.get("upl") or 0),
            "unrealizedPnlPct": float(row.get("uplRatio") or 0) * 100,
            "leverage": float(row.get("lever") or 0),
            "posSide": row.get("posSide"),
            "source": "okx_private_positions",
            "entryReason": f"OKX live · mark {rnd(float(row.get('markPx') or 0))} · UPL {rnd(float(row.get('upl') or 0))} USDT",
            "hardStopAlgoId": bool(row.get("closeOrderAlgo")),
            "hardStopPrice": None,
            "contractValueApprox": ct_val,
        })
    return sorted(positions, key=lambda p: p.get("instId") or "")


async def fetch_okx_positions_snapshot():
    try:
        from okx_strategy22_live_pilot import OkxCredentials, OkxPrivateClient
        creds = OkxCredentials.from_env()
        async with httpx.AsyncClient(timeout=20) as client:
            okx = OkxPrivateClient(client, creds)
            data = await okx.positions()
        raw_positions = data.get("data", [])
        return {"ok": True, "simulated": creds.simulated, "positions": normalize_okx_position_snapshot(raw_positions), "rawCount": len(raw_positions)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "positions": []}


def normalize_okx_position_history(rows):
    history = []
    for row in rows or []:
        open_px = safe_float(row.get("openAvgPx") or row.get("avgPx") or row.get("openPx"))
        close_px = safe_float(row.get("closeAvgPx") or row.get("closePx"))
        pnl = safe_float(row.get("realizedPnl") or row.get("pnl"))
        pnl_ratio = safe_float(row.get("pnlRatio")) * 100
        margin = safe_float(row.get("margin") or row.get("imr") or row.get("mmr"))
        notional = safe_float(row.get("notionalUsd") or row.get("notional"))
        fee = safe_float(row.get("fee"))
        funding_fee = safe_float(row.get("fundingFee"))
        history.append({
            "instId": row.get("instId"),
            "openTime": datetime.fromtimestamp(safe_float(row.get("cTime")) / 1000, timezone.utc).isoformat(timespec="seconds") if row.get("cTime") else None,
            "closeTime": datetime.fromtimestamp(safe_float(row.get("uTime")) / 1000, timezone.utc).isoformat(timespec="seconds") if row.get("uTime") else None,
            "openAvgPx": open_px,
            "closeAvgPx": close_px,
            "pnlUsd": rnd(pnl),
            "pnlPct": rnd(pnl_ratio),
            "margin": rnd(margin),
            "notional": rnd(notional),
            "fee": rnd(fee),
            "fundingFee": rnd(funding_fee),
            "leverage": safe_float(row.get("lever")),
            "mgnMode": row.get("mgnMode"),
            "posSide": row.get("posSide"),
            "direction": row.get("direction") or row.get("side"),
            "source": "okx_positions_history",
        })
    return sorted(history, key=lambda r: r.get("closeTime") or r.get("openTime") or "", reverse=True)


async def fetch_okx_positions_history_snapshot(inst_id=None, limit=100):
    try:
        from okx_strategy22_live_pilot import OkxCredentials, OkxPrivateClient
        creds = OkxCredentials.from_env()
        params = {"instType": "SWAP", "limit": str(max(1, min(int(limit or 100), 100)))}
        if inst_id:
            params["instId"] = inst_id
        path = "/api/v5/account/positions-history?" + str(httpx.QueryParams(params))
        async with httpx.AsyncClient(timeout=30) as client:
            okx = OkxPrivateClient(client, creds)
            data = await okx.request("GET", path)
        raw_rows = data.get("data", [])
        return {"ok": True, "simulated": creds.simulated, "rows": normalize_okx_position_history(raw_rows), "rawCount": len(raw_rows), "limit": params["limit"], "instId": inst_id}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "rows": [], "limit": limit, "instId": inst_id}


async def okx_live_performance_payload():
    rows = read_okx_live_log_rows()
    states = read_okx_live_states()
    perf = summarize_okx_live_performance(rows, states)
    perf["account"] = await fetch_okx_account_snapshot()
    exchange_positions = await fetch_okx_positions_snapshot()
    perf["positionsHistory"] = await fetch_okx_positions_history_snapshot(limit=50)
    perf["exchangePositions"] = exchange_positions
    if exchange_positions.get("ok"):
        state_positions = {}
        for state in states:
            if state.get("completed"):
                continue
            for inst_id, item in (state.get("positions") or {}).items():
                if isinstance(item, dict):
                    state_positions[inst_id] = item
        reconciled = []
        for pos in exchange_positions.get("positions", []):
            state_item = state_positions.get(pos.get("instId")) or {}
            state_data = state_item.get("state") if isinstance(state_item.get("state"), dict) else {}
            if state_data:
                pos["strategy"] = "top10v1_rank5_chg3_10_sl1_trail09_t12"
                pos["hardStopAlgoId"] = state_item.get("hardStopAlgoId") or state_data.get("hardStopAlgoId") or pos.get("hardStopAlgoId")
                pos["hardStopPrice"] = state_data.get("hardStopLossPrice") or pos.get("hardStopPrice")
                pos["entryReason"] = state_data.get("entryReason") or pos.get("entryReason")
                pos["entryTime"] = state_item.get("openedAt") or pos.get("entryTime")
            reconciled.append(pos)
        perf["logReconstructedOpenPositions"] = perf.get("openPositions", [])
        perf["openPositions"] = reconciled
        perf.setdefault("summary", {})["openPositions"] = len(perf["openPositions"])
        perf["openPositionsSource"] = "okx_private_positions"
    else:
        perf["openPositionsSource"] = "log_reconstruction"
    perf["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    perf["logGlob"] = OKX_LIVE_LOG_GLOB
    perf["stateGlob"] = OKX_LIVE_STATE_GLOB
    return perf


crypto_bot = CryptoPaperBot()


def install_crypto_bot(app: FastAPI):
    @app.on_event("startup")
    async def crypto_startup():
        await crypto_bot.setup()
        await crypto_bot.start()

    @app.on_event("shutdown")
    async def crypto_shutdown():
        await crypto_bot.close()

    @app.get("/crypto", response_class=HTMLResponse)
    async def crypto_dashboard():
        return HTMLResponse(CRYPTO_HTML)

    @app.get("/micro", response_class=HTMLResponse)
    async def micro_dashboard():
        return HTMLResponse(MICRO_HTML)

    @app.get("/okx-live", response_class=HTMLResponse)
    async def okx_live_dashboard():
        return HTMLResponse(OKX_LIVE_HTML)

    @app.get("/top10-strategies", response_class=HTMLResponse)
    async def top10_strategies_dashboard():
        return HTMLResponse(TOP10_STRATEGY_OVERVIEW_HTML)

    @app.get("/api/crypto/top10-strategies/overview")
    async def top10_strategies_overview():
        payload = await top10_strategy_overview_payload(
            crypto_bot=crypto_bot,
            config=CONFIG,
            okx_live_performance_payload=okx_live_performance_payload,
        )
        return JSONResponse(payload)

    @app.get("/api/crypto/okx-live/performance")
    async def okx_live_performance():
        return JSONResponse(await okx_live_performance_payload())

    @app.get("/api/crypto/okx-live/positions-history")
    async def okx_live_positions_history(inst_id: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=100)):
        return JSONResponse(await fetch_okx_positions_history_snapshot(inst_id=inst_id, limit=limit))

    @app.get("/api/crypto/status")
    async def crypto_status():
        return JSONResponse(crypto_bot.status())

    @app.post("/api/crypto/start")
    async def crypto_start():
        await crypto_bot.start()
        return JSONResponse(crypto_bot.status())

    @app.post("/api/crypto/stop")
    async def crypto_stop():
        await crypto_bot.stop()
        return JSONResponse(crypto_bot.status())

    @app.post("/api/crypto/run-once")
    async def crypto_run_once():
        await crypto_bot.run_once()
        return JSONResponse(crypto_bot.status())

    @app.get("/api/crypto/micro")
    async def crypto_micro_status():
        return JSONResponse(crypto_bot.micro_status())

    @app.get("/api/crypto/micro/ranking12h")
    async def crypto_micro_ranking12h():
        return JSONResponse(getattr(crypto_bot, "micro_ranking12h", []))

    @app.get("/api/crypto/micro/ranking1h")
    async def crypto_micro_ranking1h():
        return JSONResponse(getattr(crypto_bot, "micro_ranking1h", []))

    @app.post("/api/crypto/micro/run-once")
    async def crypto_micro_run_once():
        await crypto_bot.run_micro_once()
        return JSONResponse(crypto_bot.micro_status())

    @app.get("/api/crypto/micro/trades")
    async def crypto_micro_trades(inst_id: str = Query("", max_length=30)):
        sql = "SELECT id,ts,inst_id,strategy,side,price,quantity,quote_amount,ma60,volume_ratio,pct5,pct15,reason FROM crypto_micro_trades"
        args = []
        if inst_id:
            sql += " WHERE inst_id=$1"
            args.append(inst_id.upper())
        sql += " ORDER BY ts DESC LIMIT 120"
        async with crypto_bot.pool.acquire() as conn:
            rows = [dict(row) for row in await conn.fetch(sql, *args)]
        rows = annotate_micro_trade_pnl(rows)
        for row in rows:
            row["ts"] = row["ts"].isoformat()
        return JSONResponse(rows)

    @app.get("/api/crypto/micro/trade-records")
    async def crypto_micro_trade_records():
        async with crypto_bot.pool.acquire() as conn:
            rows = [dict(row) for row in await conn.fetch(
                "SELECT id,ts,inst_id,strategy,side,price,quantity,quote_amount FROM crypto_micro_trades ORDER BY ts ASC, id ASC"
            )]
        records = build_micro_entry_exit_records(rows)[:160]
        compact_records = []
        for row in records:
            compact_records.append({
                "strategy": row["strategy"],
                "inst_id": row["inst_id"],
                "entry_time": row["entry_time"].isoformat(),
                "exit_time": row["exit_time"].isoformat() if row.get("exit_time") else None,
                "performance": row.get("pnl_roe_pct"),
                "pnl": row.get("pnl"),
                "pnl_pct": row.get("pnl_pct"),
                "pnl_roe_pct": row.get("pnl_roe_pct"),
                "status": row.get("status"),
            })
        return JSONResponse(compact_records)

    @app.get("/api/crypto/micro/performance12h")
    async def crypto_micro_performance12h():
        history = await crypto_bot.refresh_micro_strategy_performance_12h()
        return JSONResponse(history)

    @app.get("/api/crypto/micro/trade-windows")
    async def crypto_micro_trade_windows(trade_id: int = Query(..., ge=1)):
        async with crypto_bot.pool.acquire() as conn:
            records = await conn.fetch(
                """SELECT trade_id,inst_id,side,window_type,captured_at,candles,signal
                   FROM crypto_micro_trade_windows
                   WHERE trade_id=$1
                   ORDER BY window_type""",
                trade_id,
            )
        rows = [dict(row) for row in records]
        for row in rows:
            row["captured_at"] = row["captured_at"].isoformat()
            if isinstance(row["candles"], str):
                row["candles"] = json.loads(row["candles"])
            if isinstance(row["signal"], str):
                row["signal"] = json.loads(row["signal"])
        return JSONResponse(rows)

    @app.get("/api/crypto/micro/performance")
    async def crypto_micro_performance():
        async with crypto_bot.pool.acquire() as conn:
            rows = [dict(row) for row in await conn.fetch(
                "SELECT id,ts,inst_id,strategy,side,price,quantity,quote_amount,reason FROM crypto_micro_trades ORDER BY ts DESC"
            )]
        annotated = annotate_micro_trade_pnl(rows)
        groups = {}
        for row in annotated:
            strategy = row.get("strategy") or "strategy1"
            item = groups.setdefault(strategy, {"strategy": strategy, "trades": 0, "closedTrades": 0, "wins": 0, "losses": 0, "realizedPnl": 0.0})
            item["trades"] += 1
            if row["side"] == "SELL" and row.get("pnl") is not None:
                pnl = float(row["pnl"])
                item["closedTrades"] += 1
                item["realizedPnl"] += pnl
                if pnl > 0:
                    item["wins"] += 1
                else:
                    item["losses"] += 1
        result = []
        for item in groups.values():
            item["realizedPnl"] = rnd(item["realizedPnl"])
            item["winRate"] = rnd((item["wins"] / item["closedTrades"]) * 100 if item["closedTrades"] else 0)
            result.append(item)
        result.sort(key=lambda row: row["strategy"])
        return JSONResponse(result)

    @app.get("/api/crypto/micro/surge-archive")
    async def crypto_micro_surge_archive(limit: int = Query(120, ge=1, le=1000), inst_id: str = Query("", max_length=30)):
        sql = """SELECT id,scan_hour,captured_at,rank,inst_id,price,pct5,pct15,pct1h,pct12h,pct24,
                        quote_volume_24h,volume_ratio,distance_ma60_pct,candles,signal
                 FROM crypto_micro_surge_archive"""
        args = []
        if inst_id:
            sql += " WHERE inst_id=$1"
            args.append(inst_id.upper())
        sql += f" ORDER BY scan_hour DESC, rank ASC LIMIT ${len(args) + 1}"
        args.append(limit)
        async with crypto_bot.pool.acquire() as conn:
            rows = [dict(row) for row in await conn.fetch(sql, *args)]
        for row in rows:
            row["scan_hour"] = row["scan_hour"].isoformat()
            row["captured_at"] = row["captured_at"].isoformat()
            if isinstance(row["candles"], str):
                row["candles"] = json.loads(row["candles"])
            if isinstance(row["signal"], str):
                row["signal"] = json.loads(row["signal"])
        return JSONResponse(rows)

    @app.post("/api/crypto/micro/prune-old")
    async def crypto_micro_prune_old(confirm: str = Query("", max_length=32)):
        if confirm != "delete-old-micro-trades":
            return JSONResponse({"error": "confirmation required"}, status_code=400)
        result = await crypto_bot.prune_old_micro_records(CONFIG["microStrategySince"])
        return JSONResponse(result)

    @app.post("/api/crypto/backfill")
    async def crypto_backfill(days: int = Query(90, ge=1, le=365)):
        status = await crypto_bot.start_backfill(days)
        return JSONResponse(status)

    @app.get("/api/crypto/backfill")
    async def crypto_backfill_status():
        return JSONResponse(crypto_bot.backfill_status)

    @app.get("/api/crypto/trades")
    async def crypto_trades(symbol: str = Query("", max_length=20), strategy: str = Query("", max_length=80)):
        sql = "SELECT ts,symbol,strategy,side,price,quantity,quote_amount,reason FROM crypto_trades"
        args = []
        if symbol:
            sql += " WHERE symbol=$1"
            args.append(symbol.upper())
        if strategy:
            sql += " AND strategy=$2" if args else " WHERE strategy=$1"
            args.append(strategy)
        sql += " ORDER BY ts DESC LIMIT 100"
        async with crypto_bot.pool.acquire() as conn:
            rows = [dict(row) for row in await conn.fetch(sql, *args)]
        rows = annotate_trade_pnl(rows)
        for row in rows:
            row["ts"] = row["ts"].isoformat()
        return JSONResponse(rows)

    @app.get("/api/crypto/candles")
    async def crypto_candles(symbol: str = Query("BTCUSDT", max_length=20), interval: str = Query("5m", max_length=10), limit: int = Query(300, ge=1, le=2000)):
        async with crypto_bot.pool.acquire() as conn:
            rows = [
                dict(row)
                for row in await conn.fetch(
                    """SELECT symbol,interval,ts,open,high,low,close,volume,source
                       FROM crypto_candles
                       WHERE symbol=$1 AND interval=$2
                       ORDER BY ts DESC LIMIT $3""",
                    symbol.upper(),
                    interval,
                    limit,
                )
            ]
        rows.reverse()
        for row in rows:
            row["ts"] = row["ts"].isoformat()
        return JSONResponse(rows)

    @app.get("/api/crypto/performance")
    async def crypto_performance(symbol: str = Query("", max_length=20)):
        wanted_symbols = [symbol.upper()] if symbol else CONFIG["symbols"]
        async with crypto_bot.pool.acquire() as conn:
            state_rows = [
                dict(row)
                for row in await conn.fetch(
                    "SELECT symbol,strategy,state,updated_at FROM crypto_state WHERE symbol = ANY($1::text[])",
                    wanted_symbols,
                )
            ]
            candle_rows = [
                dict(row)
                for row in await conn.fetch(
                    """SELECT DISTINCT ON (symbol) symbol, close, ts
                       FROM crypto_candles
                       WHERE interval=$1 AND symbol = ANY($2::text[])
                       ORDER BY symbol, ts DESC""",
                    CONFIG["interval"],
                    wanted_symbols,
                )
            ]
        state_map = {}
        updated_map = {}
        for row in state_rows:
            raw_state = row["state"]
            key = (row["symbol"], row["strategy"])
            state_map[key] = raw_state if isinstance(raw_state, dict) else json.loads(raw_state)
            updated_map[key] = row["updated_at"]
        price_map = {row["symbol"]: float(row["close"]) for row in candle_rows}
        price_time_map = {row["symbol"]: row["ts"] for row in candle_rows}
        rows = []
        for market_symbol in wanted_symbols:
            snapshot = crypto_bot.snapshots.get(market_symbol)
            latest_price = (snapshot["lastPrice"] if snapshot else 0) or price_map.get(market_symbol, 0)
            for strategy in STRATEGIES:
                key = (market_symbol, strategy["id"])
                account = state_map.get(key) or new_account()
                item = snapshot_row(strategy, account, latest_price)
                item["symbol"] = market_symbol
                item["closedTrades"] = account.get("closedTrades", 0)
                item["updatedAt"] = updated_map[key].isoformat() if key in updated_map else None
                item["priceTime"] = price_time_map[market_symbol].isoformat() if market_symbol in price_time_map else None
                rows.append(item)
        rows.sort(key=lambda row: row["returnPct"], reverse=True)
        return JSONResponse(rows)

    @app.get("/api/crypto/backtest")
    async def crypto_backtest(days: int = Query(90, ge=1, le=365), symbol: str = Query("", max_length=20)):
        wanted_symbols = [symbol.upper()] if symbol else CONFIG["symbols"]
        since = datetime.now(timezone.utc) - timedelta(days=days)
        results = []
        async with crypto_bot.pool.acquire() as conn:
            for market_symbol in wanted_symbols:
                candles = [
                    candle_from_db(row)
                    for row in await conn.fetch(
                        """SELECT ts,open,high,low,close,volume FROM crypto_candles
                           WHERE symbol=$1 AND interval=$2 AND ts >= $3
                           ORDER BY ts ASC""",
                        market_symbol,
                        CONFIG["interval"],
                        since,
                    )
                ]
                higher = [
                    candle_from_db(row)
                    for row in await conn.fetch(
                        """SELECT ts,open,high,low,close,volume FROM crypto_candles
                           WHERE symbol=$1 AND interval=$2 AND ts >= $3
                           ORDER BY ts ASC""",
                        market_symbol,
                        CONFIG["higherInterval"],
                        since - timedelta(days=2),
                    )
                ]
                results.extend(backtest_symbol(market_symbol, candles, higher))
        results.sort(key=lambda row: row["returnPct"], reverse=True)
        return JSONResponse({"days": days, "rows": results})

    @app.get("/api/crypto/strategy")
    async def crypto_strategy_detail(symbol: str = Query(..., max_length=20), strategy: str = Query(..., max_length=80)):
        symbol = symbol.upper()
        strategy_def = next((item for item in STRATEGIES if item["id"] == strategy), None)
        if not strategy_def:
            return JSONResponse({"error": "unknown_strategy"}, status_code=404)
        async with crypto_bot.pool.acquire() as conn:
            state_row = await conn.fetchrow(
                "SELECT state,updated_at FROM crypto_state WHERE symbol=$1 AND strategy=$2",
                symbol,
                strategy,
            )
            candle_row = await conn.fetchrow(
                """SELECT close, ts FROM crypto_candles
                   WHERE symbol=$1 AND interval=$2
                   ORDER BY ts DESC LIMIT 1""",
                symbol,
                CONFIG["interval"],
            )
            trades = [
                dict(row)
                for row in await conn.fetch(
                    """SELECT ts,symbol,strategy,side,price,quantity,quote_amount,reason
                       FROM crypto_trades
                       WHERE symbol=$1 AND strategy=$2
                       ORDER BY ts DESC LIMIT 80""",
                    symbol,
                    strategy,
                )
            ]
            signals = [
                dict(row)
                for row in await conn.fetch(
                    """SELECT ts,price,signal,reason,action,equity,return_pct
                       FROM crypto_signals
                       WHERE symbol=$1 AND strategy=$2
                       ORDER BY ts DESC LIMIT 30""",
                    symbol,
                    strategy,
                )
            ]
        account = new_account()
        updated_at = None
        if state_row:
            raw_state = state_row["state"]
            account = raw_state if isinstance(raw_state, dict) else json.loads(raw_state)
            updated_at = state_row["updated_at"]
        snapshot = crypto_bot.snapshots.get(symbol)
        latest_price = (snapshot["lastPrice"] if snapshot else 0) or (float(candle_row["close"]) if candle_row else 0)
        performance = snapshot_row(strategy_def, account, latest_price)
        performance["symbol"] = symbol
        performance["closedTrades"] = account.get("closedTrades", 0)
        performance["updatedAt"] = updated_at.isoformat() if updated_at else None
        performance["priceTime"] = candle_row["ts"].isoformat() if candle_row else None
        trades = annotate_trade_pnl(trades)
        for row in trades:
            row["ts"] = row["ts"].isoformat()
        for row in signals:
            row["ts"] = row["ts"].isoformat()
        return JSONResponse({"performance": performance, "trades": trades, "signals": signals})


async def fetch_klines(client, symbol, interval, limit):
    inst_id = to_okx_inst_id(symbol)
    params = {"instId": inst_id, "bar": interval, "limit": str(limit)}
    resp = await client.get(f"{OKX_BASE}/api/v5/market/candles", params=params)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX candles error: {payload}")
    return [
        {
            "time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": okx_quote_volume(r),
            "closeTime": int(r[0]),
        }
        for r in reversed(payload["data"])
    ]


async def fetch_history_klines(client, symbol, interval, limit, after=None):
    inst_id = to_okx_inst_id(symbol)
    params = {"instId": inst_id, "bar": interval, "limit": str(limit)}
    if after:
        params["after"] = after
    resp = await client.get(f"{OKX_BASE}/api/v5/market/history-candles", params=params)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX history candles error: {payload}")
    return [
        {
            "time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),
            "closeTime": int(r[0]),
        }
        for r in reversed(payload["data"])
    ]


async def fetch_market_tickers(client, inst_type):
    resp = await client.get(f"{OKX_BASE}/api/v5/market/tickers", params={"instType": inst_type})
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX tickers error: {payload}")
    return payload["data"]


async def fetch_okx_candles_by_inst(client, inst_id, interval, limit):
    resp = await client.get(
        f"{OKX_BASE}/api/v5/market/candles",
        params={"instId": inst_id, "bar": interval, "limit": str(limit)},
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX candles error: {payload}")
    return [
        {
            "time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": okx_quote_volume(r),
            "closeTime": int(r[0]),
        }
        for r in reversed(payload["data"])
    ]


def okx_quote_volume(row):
    if len(row) > 7 and safe_float(row[7]) > 0:
        return safe_float(row[7])
    if len(row) > 6 and safe_float(row[6]) > 0:
        return safe_float(row[6])
    return safe_float(row[5])


def to_micro_candles(candles):
    if CONFIG["microInterval"] != "10m":
        return candles
    rows = []
    usable = candles[-(len(candles) // 2 * 2):]
    for index in range(0, len(usable), 2):
        first, second = usable[index], usable[index + 1]
        rows.append({
            "time": first["time"],
            "open": first["open"],
            "high": max(first["high"], second["high"]),
            "low": min(first["low"], second["low"]),
            "close": second["close"],
            "volume": first["volume"] + second["volume"],
            "closeTime": second["closeTime"],
        })
    return rows


def micro_bars_per_hour():
    if CONFIG["microInterval"] == "5m":
        return 12
    if CONFIG["microInterval"] == "10m":
        return 6
    if CONFIG["microInterval"] == "15m":
        return 4
    return 6


def micro_bar_minutes():
    if CONFIG["microInterval"] == "5m":
        return 5
    if CONFIG["microInterval"] == "10m":
        return 10
    if CONFIG["microInterval"] == "15m":
        return 15
    return 10


def micro_strategy_enabled(strategy):
    active = CONFIG.get("microActiveStrategies") or []
    return strategy in active


def micro_strategy4_signal(ticker, candles):
    base = micro_trend_signal(ticker, candles)
    base["strategy"] = "strategy4_breakout_confirmation"
    base["buy"] = False
    base["reason"] = "strategy4_watch"
    base["strategy4PrevBreakout"] = False
    base["strategy4Hold"] = False
    if len(candles) < max(72, micro_bars_per_hour() + 3):
        return base

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    ema9 = ema_series(closes, 9)
    ema21 = ema_series(closes, 21)
    if len(ema9) < 3 or len(ema21) < 3:
        return base

    prev = candles[-2]
    current = candles[-1]
    bars_per_hour = micro_bars_per_hour()
    prev_prior_high = max(c["high"] for c in candles[-(bars_per_hour + 2):-2])
    prev_base_vol = sma(volumes[-74:-14], 60) or sma(volumes[-38:-8], 30) or sma(volumes[:-2], min(30, len(volumes[:-2]))) or 0
    prev_vol_ratio = prev["volume"] / prev_base_vol if prev_base_vol else 0
    ema9_prev = ema9[-2]
    ema21_prev = ema21[-2]
    pct1h = base.get("pct1h", 0)

    prev_breakout = (
        prev["close"] > prev_prior_high
        and prev_vol_ratio >= CONFIG["microStrategy4BreakVolumeRatio"]
        and prev["close"] > ema9_prev > ema21_prev
    )
    hold = (
        current["low"] >= prev_prior_high * CONFIG["microStrategy4HoldFactor"]
        and current["close"] > prev["close"] * (1 + CONFIG["microStrategy4ConfirmGainPct"] / 100)
    )
    confirm_volume = base.get("volumeRatio", 0) >= CONFIG["microStrategy4ConfirmVolumeRatio"]
    buy_signal = prev_breakout and hold and pct1h >= CONFIG["microStrategy4MinPct1h"] and confirm_volume

    base.update({
        "buy": buy_signal,
        "reason": "strategy4_confirmed_breakout" if buy_signal else "strategy4_watch",
        "strategy4PrevBreakout": prev_breakout,
        "strategy4Hold": hold,
        "strategy4PrevVolumeRatio": rnd(prev_vol_ratio),
        "strategy4ConfirmVolumeOk": confirm_volume,
        "strategy4BreakoutLevel": rnd(prev_prior_high, 8),
        "strategy4PrevEma9": rnd(ema9_prev, 8),
        "strategy4PrevEma21": rnd(ema21_prev, 8),
    })
    return base


def micro_strategy4_should_exit(signal, state, price):
    entry = state.get("avgEntry", 0)
    if not entry:
        return False
    stop_price = entry * (1 - CONFIG["microStrategy4StopLossPct"] / 100)
    breakeven_stop = state.get("breakevenStopPrice")
    peak = max(state.get("peakPrice", price), price)
    peak_gain = ((peak - entry) / entry) * 100 if entry else 0
    giveback = ((peak - price) / peak) * 100 if peak else 0
    age_bars = (signal.get("time", 0) - state.get("entryTime", 0)) / (micro_bar_minutes() * 60 * 1000) if state.get("entryTime") else 0

    if signal.get("lastLow", price) <= stop_price:
        set_micro_exit(signal, "strategy4_stop_loss_0_8pct", 1.0, stop_price)
    elif breakeven_stop and signal.get("lastLow", price) <= breakeven_stop:
        set_micro_exit(signal, "strategy4_breakeven_stop_after_tp1", 1.0, breakeven_stop)
    elif not state.get("tp1Taken") and price >= entry * (1 + CONFIG["microStrategy4TakeProfit1Pct"] / 100):
        state["tp1Taken"] = True
        state["breakevenStopPrice"] = entry * (1 + CONFIG["microStrategy4BreakevenLockPct"] / 100)
        set_micro_exit(signal, "strategy4_tp1_take_half_move_stop_breakeven", 0.5, price)
    elif state.get("tp1Taken") and price >= entry * (1 + CONFIG["microStrategy4TakeProfit2Pct"] / 100):
        set_micro_exit(signal, "strategy4_tp2_or_runner_exit", 0.5, price)
    elif state.get("tp1Taken") and peak_gain >= CONFIG["microStrategy4TrailingStartPct"] and giveback >= CONFIG["microStrategy4TrailingGivebackPct"]:
        set_micro_exit(signal, "strategy4_trailing_runner_giveback")
    elif age_bars >= CONFIG["microStrategy4TimeStopBars"]:
        set_micro_exit(signal, "strategy4_time_stop")
    elif price < entry and signal.get("pct15", 0) <= CONFIG["microEarlyExitPct15m"]:
        set_micro_exit(signal, "strategy4_momentum_loss_15m")
    return bool(signal.get("exitReason"))





def micro_strategy41_signal(ticker, candles):
    base = micro_strategy4_signal(ticker, candles)
    base["strategy"] = "strategy4.1_breakout_confirmation"
    add_micro_slippage_snapshot(base, ticker)
    current = candles[-1]
    candle_range = current["high"] - current["low"]
    upper_wick_ratio = ((current["high"] - max(current["open"], current["close"])) / candle_range) if candle_range > 0 else 0
    breakout_level = base.get("strategy4BreakoutLevel") or base.get("priorHigh") or 0
    breakout_stretch_pct = ((current["close"] - breakout_level) / breakout_level) * 100 if breakout_level else 0
    spread_pct = base.get("spreadPct")
    spread_ok = spread_pct is None or spread_pct <= CONFIG["microStrategy41MaxSpreadPct"]
    heat_ok = (
        base.get("pct1h", 0) <= CONFIG["microStrategy41MaxPct1h"]
        and base.get("pct15", 0) <= CONFIG["microStrategy41MaxPct15m"]
        and base.get("volumeRatio", 0) <= CONFIG["microStrategy41MaxVolumeRatio"]
        and base.get("distanceMa60Pct", 0) <= CONFIG["microMaxDistanceMa60Pct"]
    )
    structure_ok = (
        base.get("ma20", 0) >= base.get("ma60", 0)
        and base.get("ma60Slope", 0) >= 0
        and upper_wick_ratio <= CONFIG["microStrategy41MaxUpperWickRatio"]
        and breakout_stretch_pct <= CONFIG["microStrategy41MaxBreakoutStretchPct"]
        and not base.get("chaseRisk")
    )
    buy_signal = bool(base.get("buy") and heat_ok and structure_ok and spread_ok)
    base.update({
        "buy": buy_signal,
        "reason": "strategy4.1_confirmed_breakout_filtered" if buy_signal else "strategy4.1_watch",
        "strategy41HeatOk": heat_ok,
        "strategy41StructureOk": structure_ok,
        "strategy41SpreadOk": spread_ok,
        "strategy41UpperWickRatio": rnd(upper_wick_ratio),
        "strategy41BreakoutStretchPct": rnd(breakout_stretch_pct),
    })
    return base


def micro_strategy41_should_exit(signal, state, price):
    return micro_strategy4_should_exit(signal, state, price)


def add_micro_slippage_snapshot(signal, ticker):
    price = signal.get("price") or 0
    bid = safe_float(ticker.get("bidPx"))
    ask = safe_float(ticker.get("askPx"))
    if price and bid > 0 and ask > 0:
        signal["bestBid"] = rnd(bid, 8)
        signal["bestAsk"] = rnd(ask, 8)
        signal["spreadPct"] = rnd(((ask - bid) / price) * 100)
        signal["buySlippagePct"] = rnd(((ask - price) / price) * 100)
        signal["sellSlippagePct"] = rnd(((price - bid) / price) * 100)
    return signal


def micro_strategy9_signal(ticker, candles):
    base = micro_trend_signal(ticker, candles)
    base["strategy"] = "strategy9_ema9_bounce_low_heat"
    base["buy"] = False
    base["reason"] = "strategy9_watch"
    base["strategy9TrendFilter"] = False
    base["strategy9BounceFilter"] = False
    add_micro_slippage_snapshot(base, ticker)
    bars_per_hour = micro_bars_per_hour()
    if len(candles) < max(bars_per_hour * 2 + 1, 60):
        return base
    closes = [c["close"] for c in candles]
    ema9 = ema_series(closes, 9)
    ema21 = ema_series(closes, 21)
    if len(ema9) < 2 or len(ema21) < 2:
        return base
    prev = candles[-2]
    current = candles[-1]
    trend_filter = (
        CONFIG["microStrategy9MinPct1h"] <= base.get("pct1h", 0) <= CONFIG["microStrategy9MaxPct1h"]
        and base.get("pct15", 0) <= CONFIG["microStrategy9MaxPct15m"]
    )
    bounce_filter = (
        prev["low"] <= ema9[-2] * (1 + CONFIG["microStrategy9Ema9TouchPct"] / 100)
        and prev["close"] >= ema21[-2] * (1 - CONFIG["microStrategy9Ema21SlackPct"] / 100)
        and current["close"] > current["open"]
        and current["close"] > ema9[-1]
        and ema9[-1] >= ema21[-1]
        and CONFIG["microStrategy9MinVolumeRatio"] <= base.get("volumeRatio", 0) <= CONFIG["microStrategy9MaxVolumeRatio"]
    )
    buy_signal = trend_filter and bounce_filter
    base.update({
        "buy": buy_signal,
        "reason": "strategy9_ema9_bounce_low_heat" if buy_signal else "strategy9_watch",
        "strategy9TrendFilter": trend_filter,
        "strategy9BounceFilter": bounce_filter,
        "strategy9Ema9": rnd(ema9[-1], 8),
        "strategy9Ema21": rnd(ema21[-1], 8),
        "strategy9PrevEma9": rnd(ema9[-2], 8),
        "strategy9PrevEma21": rnd(ema21[-2], 8),
        "strategy9Params": {
            "topN": CONFIG["microStrategy9TopN"],
            "min1": CONFIG["microStrategy9MinPct1h"],
            "max1": CONFIG["microStrategy9MaxPct1h"],
            "max15": CONFIG["microStrategy9MaxPct15m"],
            "touch": CONFIG["microStrategy9Ema9TouchPct"],
            "volMin": CONFIG["microStrategy9MinVolumeRatio"],
            "volMax": CONFIG["microStrategy9MaxVolumeRatio"],
        },
    })
    return base


def micro_strategy18_signal(ticker, candles):
    base = micro_trend_signal(ticker, candles)
    base["strategy"] = "s18_top2h_retest_runner"
    base["buy"] = False
    base["reason"] = "strategy18_watch"
    base["strategy18PrevBreakout"] = False
    base["strategy18Retest"] = False
    base["strategy18TrendFilter"] = False
    base["strategy18CandleFilter"] = False
    add_micro_slippage_snapshot(base, ticker)
    bars_per_hour = micro_bars_per_hour()
    if len(candles) < max(bars_per_hour * 3 + 4, 72):
        return base
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    ema9 = ema_series(closes, 9)
    ema21 = ema_series(closes, 21)
    if len(ema9) < 3 or len(ema21) < 3:
        return base
    prev = candles[-2]
    current = candles[-1]
    breakout_level = max(c["high"] for c in candles[-(bars_per_hour + 3):-3])
    prev_base_vol = sma(volumes[-74:-14], 60) or sma(volumes[-38:-8], 30) or sma(volumes[:-2], min(30, len(volumes[:-2]))) or 0
    prev_vol_ratio = prev["volume"] / prev_base_vol if prev_base_vol else 0
    prev_breakout = (
        prev["close"] > breakout_level
        and prev_vol_ratio >= CONFIG["microStrategy18BreakVolumeRatio"]
        and prev["close"] > ema9[-2] >= ema21[-2]
    )
    retest = (
        current["low"] <= breakout_level * (1 + CONFIG["microStrategy18RetestTolerancePct"] / 100)
        and current["close"] >= breakout_level * (1 + CONFIG["microStrategy18HoldPct"] / 100)
    )
    trend_filter = (
        base.get("pct2h", 0) >= CONFIG["microStrategy18MinPct2h"]
        and base.get("pct1h", 0) <= CONFIG["microStrategy18MaxPct1h"]
        and base.get("pct15", 0) <= CONFIG["microStrategy18MaxPct15m"]
    )
    candle_filter = (
        current["close"] > current["open"]
        and current["close"] > ema9[-1]
        and base.get("volumeRatio", 0) >= CONFIG["microStrategy18ConfirmVolumeRatio"]
    )
    buy_signal = prev_breakout and retest and trend_filter and candle_filter
    base.update({
        "buy": buy_signal,
        "reason": "s18_top2h_retest_runner" if buy_signal else "strategy18_watch",
        "strategy18PrevBreakout": prev_breakout,
        "strategy18Retest": retest,
        "strategy18TrendFilter": trend_filter,
        "strategy18CandleFilter": candle_filter,
        "strategy18BreakoutLevel": rnd(breakout_level, 8),
        "strategy18PrevVolumeRatio": rnd(prev_vol_ratio),
        "strategy18Ema9": rnd(ema9[-1], 8),
        "strategy18Ema21": rnd(ema21[-1], 8),
        "strategy18Params": {
            "topN": CONFIG["microStrategy18TopN"],
            "min2": CONFIG["microStrategy18MinPct2h"],
            "max1": CONFIG["microStrategy18MaxPct1h"],
            "max15": CONFIG["microStrategy18MaxPct15m"],
            "bvol": CONFIG["microStrategy18BreakVolumeRatio"],
            "cvol": CONFIG["microStrategy18ConfirmVolumeRatio"],
            "tol": CONFIG["microStrategy18RetestTolerancePct"],
        },
    })
    return base


def micro_strategy9_should_exit(signal, state, price):
    return micro_lab_runner_should_exit(signal, state, price, 9)


def micro_strategy18_should_exit(signal, state, price):
    return micro_lab_runner_should_exit(signal, state, price, 18)


def micro_strategy20_signal(ticker, candles):
    base = micro_trend_signal(ticker, candles)
    base["strategy"] = "strategy20_6h12h_cool_vwap_reclaim"
    base["buy"] = False
    base["reason"] = "strategy20_watch"
    base["strategy20TrendFilter"] = False
    base["strategy20ReclaimFilter"] = False
    add_micro_slippage_snapshot(base, ticker)
    bars_per_hour = micro_bars_per_hour()
    if len(candles) < max(bars_per_hour * 12 + 1, 145):
        return base
    closes = [c["close"] for c in candles]
    ema9 = ema_series(closes, 9)
    ema21 = ema_series(closes, 21)
    if len(ema9) < 2 or len(ema21) < 2:
        return base
    prev = candles[-2]
    current = candles[-1]
    current_vwap = vwap(candles, 24) or current["close"]
    prev_vwap = vwap(candles[:-1], 24) or prev["close"]
    high_low_range = current["high"] - current["low"]
    upper_wick_ratio = (current["high"] - current["close"]) / high_low_range if high_low_range > 0 else 0
    trend_filter = (
        base.get("pct12h", 0) >= CONFIG["microStrategy20MinPct12h"]
        and base.get("pct6h", 0) >= CONFIG["microStrategy20MinPct6h"]
        and base.get("pct3h", 0) >= CONFIG["microStrategy20MinPct3h"]
        and CONFIG["microStrategy20MinPct1h"] <= base.get("pct1h", 0) <= CONFIG["microStrategy20MaxPct1h"]
        and base.get("pct15", 0) <= CONFIG["microStrategy20MaxPct15m"]
    )
    reclaim_filter = (
        prev["low"] <= max(ema21[-2], prev_vwap) * (1 + CONFIG["microStrategy20ReclaimBufferPct"] / 100)
        and current["close"] > current["open"]
        and current["close"] > ema9[-1]
        and current["close"] > current_vwap
        and ema9[-1] >= ema21[-1]
        and CONFIG["microStrategy20MinVolumeRatio"] <= base.get("volumeRatio", 0) <= CONFIG["microStrategy20MaxVolumeRatio"]
        and upper_wick_ratio <= CONFIG["microStrategy20MaxUpperWickRatio"]
    )
    buy_signal = trend_filter and reclaim_filter
    base.update({
        "buy": buy_signal,
        "reason": "strategy20_6h12h_cool_vwap_reclaim" if buy_signal else "strategy20_watch",
        "strategy20TrendFilter": trend_filter,
        "strategy20ReclaimFilter": reclaim_filter,
        "strategy20Vwap": rnd(current_vwap, 8),
        "strategy20PrevVwap": rnd(prev_vwap, 8),
        "strategy20Ema9": rnd(ema9[-1], 8),
        "strategy20Ema21": rnd(ema21[-1], 8),
        "strategy20UpperWickRatio": rnd(upper_wick_ratio),
    })
    return base



def micro_strategy21_signal(ticker, candles):
    base = micro_trend_signal(ticker, candles)
    base["strategy"] = "strategy21_multi_tf_intersection_ema9_bounce"
    base["buy"] = False
    base["reason"] = "strategy21_watch"
    base["strategy21TrendFilter"] = False
    base["strategy21BounceFilter"] = False
    add_micro_slippage_snapshot(base, ticker)
    bars_per_hour = micro_bars_per_hour()
    if len(candles) < max(bars_per_hour * 12 + 1, 145):
        return base
    closes = [c["close"] for c in candles]
    ema9 = ema_series(closes, 9)
    ema21 = ema_series(closes, 21)
    if len(ema9) < 2 or len(ema21) < 2:
        return base
    prev = candles[-2]
    current = candles[-1]
    body_pct = ((current["close"] / current["open"]) - 1) * 100 if current["open"] else 0
    trend_filter = (
        base.get("pct12h", 0) >= CONFIG["microStrategy21MinPct12h"]
        and base.get("pct6h", 0) >= CONFIG["microStrategy21MinPct6h"]
        and base.get("pct3h", 0) >= CONFIG["microStrategy21MinPct3h"]
        and base.get("pct1h", 0) <= CONFIG["microStrategy21MaxPct1h"]
        and base.get("pct15", 0) <= CONFIG["microStrategy21MaxPct15m"]
    )
    bounce_filter = (
        prev["low"] <= ema9[-2] * (1 + CONFIG["microStrategy21Ema9TouchPct"] / 100)
        and prev["close"] >= ema21[-2] * (1 - CONFIG["microStrategy21Ema21SlackPct"] / 100)
        and current["close"] > current["open"]
        and body_pct >= CONFIG["microStrategy21MinBodyPct"]
        and current["close"] > ema9[-1]
        and ema9[-1] >= ema21[-1]
        and CONFIG["microStrategy21MinVolumeRatio"] <= base.get("volumeRatio", 0) <= CONFIG["microStrategy21MaxVolumeRatio"]
    )
    buy_signal = trend_filter and bounce_filter
    base.update({"buy": buy_signal, "reason": "strategy21_multi_tf_ema9_bounce" if buy_signal else "strategy21_watch", "strategy21TrendFilter": trend_filter, "strategy21BounceFilter": bounce_filter, "strategy21BodyPct": rnd(body_pct), "strategy21Ema9": rnd(ema9[-1], 8), "strategy21Ema21": rnd(ema21[-1], 8), "strategy21PrevEma9": rnd(ema9[-2], 8), "strategy21PrevEma21": rnd(ema21[-2], 8)})
    return base


def micro_strategy23_signal(ticker, candles):
    base = micro_trend_signal(ticker, candles)
    base["strategy"] = "strategy23_top1h_clean_early_breakout"
    base["buy"] = False
    base["reason"] = "strategy23_watch"
    base["strategy23TrendFilter"] = False
    base["strategy23BreakoutFilter"] = False
    add_micro_slippage_snapshot(base, ticker)
    bars_per_hour = micro_bars_per_hour()
    if len(candles) < max(bars_per_hour * 3 + 1, 72):
        return base
    closes = [c["close"] for c in candles]
    ema9 = ema_series(closes, 9)
    ema21 = ema_series(closes, 21)
    if len(ema9) < 1 or len(ema21) < 1:
        return base
    current = candles[-1]
    breakout_level = max(c["high"] for c in candles[-(bars_per_hour + 1):-1])
    high_low_range = current["high"] - current["low"]
    upper_wick_ratio = (current["high"] - current["close"]) / high_low_range if high_low_range > 0 else 0
    body_pct = ((current["close"] / current["open"]) - 1) * 100 if current["open"] else 0
    stretch_pct = ((current["close"] / breakout_level) - 1) * 100 if breakout_level else 0
    trend_filter = CONFIG["microStrategy23MinPct1h"] <= base.get("pct1h", 0) <= CONFIG["microStrategy23MaxPct1h"] and base.get("pct3h", 0) >= CONFIG["microStrategy23MinPct3h"] and base.get("pct15", 0) <= CONFIG["microStrategy23MaxPct15m"]
    breakout_filter = current["close"] > breakout_level and current["close"] > current["open"] and body_pct >= CONFIG["microStrategy23MinBodyPct"] and current["close"] > ema9[-1] >= ema21[-1] and CONFIG["microStrategy23MinVolumeRatio"] <= base.get("volumeRatio", 0) <= CONFIG["microStrategy23MaxVolumeRatio"] and upper_wick_ratio <= CONFIG["microStrategy23MaxUpperWickRatio"] and 0 <= stretch_pct <= CONFIG["microStrategy23MaxBreakoutStretchPct"]
    buy_signal = trend_filter and breakout_filter
    base.update({"buy": buy_signal, "reason": "strategy23_top1h_clean_breakout" if buy_signal else "strategy23_watch", "strategy23TrendFilter": trend_filter, "strategy23BreakoutFilter": breakout_filter, "strategy23BreakoutLevel": rnd(breakout_level, 8), "strategy23UpperWickRatio": rnd(upper_wick_ratio), "strategy23BodyPct": rnd(body_pct), "strategy23StretchPct": rnd(stretch_pct), "strategy23Ema9": rnd(ema9[-1], 8), "strategy23Ema21": rnd(ema21[-1], 8)})
    return base


def micro_strategy24_signal(ticker, candles, rank_1h=None):
    base = micro_trend_signal(ticker, candles)
    base["strategy"] = "strategy24_top1h_delay_rank5_chg1_5"
    base["buy"] = False
    base["reason"] = "strategy24_watch"
    add_micro_slippage_snapshot(base, ticker)
    entry_rank_ok = rank_1h is not None and rank_1h <= CONFIG["microStrategy24TopN"]
    entry_change_ok = CONFIG["microStrategy24MinPct1h"] <= base.get("pct1h", 0) <= CONFIG["microStrategy24MaxPct1h"]
    session_still_top10 = rank_1h is not None and rank_1h <= CONFIG["microStrategy24SessionTopN"]
    seed_ok = entry_rank_ok and entry_change_ok
    base.update({
        "strategy24SeedOk": seed_ok,
        "strategy24EntryRankOk": entry_rank_ok,
        "strategy24EntryChangeOk": entry_change_ok,
        "strategy24SessionStillTop10": session_still_top10,
        "strategy24Rank1h": rank_1h,
        "strategy24Params": {
            "delayBars": CONFIG["microStrategy24DelayBars"],
            "topN": CONFIG["microStrategy24TopN"],
            "sessionTopN": CONFIG["microStrategy24SessionTopN"],
            "min1h": CONFIG["microStrategy24MinPct1h"],
            "max1h": CONFIG["microStrategy24MaxPct1h"],
            "sl": CONFIG["microStrategy24StopLossPct"],
            "beAfter": CONFIG["microStrategy24BreakevenAfterPct"],
            "trailStart": CONFIG["microStrategy24TrailingStartPct"],
            "trailGiveback": CONFIG["microStrategy24TrailingGivebackPct"],
            "timeStopBars": CONFIG["microStrategy24TimeStopBars"],
        },
    })
    return base


def micro_strategy24_should_exit(signal, state, price):
    entry = state.get("avgEntry", 0)
    if not entry:
        return False
    stop_pct = CONFIG["microStrategy24StopLossPct"]
    stop_price = entry * (1 - stop_pct / 100)
    peak = max(state.get("peakPrice", price), price)
    peak_gain = ((peak - entry) / entry) * 100 if entry else 0
    trail_stop = None
    if peak_gain >= CONFIG["microStrategy24BreakevenAfterPct"]:
        trail_stop = entry
    if peak_gain >= CONFIG["microStrategy24TrailingStartPct"]:
        trailing = peak * (1 - CONFIG["microStrategy24TrailingGivebackPct"] / 100)
        trail_stop = max(trail_stop or stop_price, trailing)
    active_stop = max(stop_price, trail_stop or stop_price)
    age_bars = (signal.get("time", 0) - state.get("entryTime", 0)) / (micro_bar_minutes() * 60 * 1000) if state.get("entryTime") else 0
    if signal.get("lastLow", price) <= active_stop:
        if active_stop > stop_price:
            set_micro_exit(signal, "strategy24_breakeven_or_trailing_stop", 1.0, active_stop)
        else:
            set_micro_exit(signal, "strategy24_stop_loss_1_5pct", 1.0, stop_price)
    elif age_bars >= CONFIG["microStrategy24TimeStopBars"]:
        set_micro_exit(signal, "strategy24_time_stop")
    return bool(signal.get("exitReason"))


def micro_lab_runner_should_exit(signal, state, price, strategy_number):
    entry = state.get("avgEntry", 0)
    if not entry:
        return False
    prefix = f"microStrategy{strategy_number}"
    reason_prefix = f"strategy{strategy_number}"
    stop_pct = CONFIG[f"{prefix}StopLossPct"]
    stop_price = entry * (1 - stop_pct / 100)
    breakeven_stop = state.get("breakevenStopPrice")
    peak = max(state.get("peakPrice", price), price)
    peak_gain = ((peak - entry) / entry) * 100 if entry else 0
    giveback = ((peak - price) / peak) * 100 if peak else 0
    age_bars = (signal.get("time", 0) - state.get("entryTime", 0)) / (micro_bar_minutes() * 60 * 1000) if state.get("entryTime") else 0
    pnl = ((price - entry) / entry) * 100 if entry else 0
    if signal.get("lastLow", price) <= stop_price:
        set_micro_exit(signal, f"{reason_prefix}_stop_loss_{str(stop_pct).replace('.', '_')}pct", 1.0, stop_price)
    elif breakeven_stop and signal.get("lastLow", price) <= breakeven_stop:
        set_micro_exit(signal, f"{reason_prefix}_breakeven_stop_after_tp1", 1.0, breakeven_stop)
    elif not state.get("tp1Taken") and price >= entry * (1 + CONFIG[f"{prefix}TakeProfit1Pct"] / 100):
        state["tp1Taken"] = True
        state["breakevenStopPrice"] = entry * (1 + CONFIG[f"{prefix}BreakevenLockPct"] / 100)
        set_micro_exit(signal, f"{reason_prefix}_tp1_partial_move_stop_breakeven", CONFIG[f"{prefix}TakeProfit1Fraction"], price)
    elif state.get("tp1Taken") and price >= entry * (1 + CONFIG[f"{prefix}TakeProfit2Pct"] / 100):
        set_micro_exit(signal, f"{reason_prefix}_tp2_or_runner_exit", 1.0, price)
    elif state.get("tp1Taken") and peak_gain >= CONFIG[f"{prefix}TrailingStartPct"] and giveback >= CONFIG[f"{prefix}TrailingGivebackPct"]:
        set_micro_exit(signal, f"{reason_prefix}_trailing_runner_giveback")
    elif age_bars >= CONFIG[f"{prefix}SoftTimeStopBars"]:
        if pnl >= CONFIG[f"{prefix}MinProgressPct"] and price >= signal.get("ma20", price) and age_bars < CONFIG[f"{prefix}HardTimeStopBars"]:
            return False
        set_micro_exit(signal, f"{reason_prefix}_time_stop")
    elif price < signal.get("ma20", price) and price < entry:
        set_micro_exit(signal, f"{reason_prefix}_ema_exit")
    return bool(signal.get("exitReason"))


def micro_strategy20_should_exit(signal, state, price):
    return micro_lab_runner_should_exit(signal, state, price, 20)


def micro_strategy21_should_exit(signal, state, price):
    return micro_lab_runner_should_exit(signal, state, price, 21)


def micro_strategy23_should_exit(signal, state, price):
    return micro_lab_runner_should_exit(signal, state, price, 23)


def micro_strategy22_signal(ticker, candles):
    base = micro_trend_signal(ticker, candles)
    base["strategy"] = "strategy22_2h_strength_breakout_retest"
    base["buy"] = False
    base["reason"] = "strategy22_watch"
    base["strategy22PrevBreakout"] = False
    base["strategy22Retest"] = False
    add_micro_slippage_snapshot(base, ticker)
    bars_per_hour = micro_bars_per_hour()
    if len(candles) < max(bars_per_hour * 3 + 4, 72):
        return base

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    ema9 = ema_series(closes, 9)
    ema21 = ema_series(closes, 21)
    if len(ema9) < 3 or len(ema21) < 3:
        return base

    prev = candles[-2]
    current = candles[-1]
    breakout_level = max(c["high"] for c in candles[-(bars_per_hour + 3):-3])
    prev_base_vol = sma(volumes[-74:-14], 60) or sma(volumes[-38:-8], 30) or sma(volumes[:-2], min(30, len(volumes[:-2]))) or 0
    prev_vol_ratio = prev["volume"] / prev_base_vol if prev_base_vol else 0
    high_low_range = current["high"] - current["low"]
    upper_wick_ratio = (current["high"] - current["close"]) / high_low_range if high_low_range > 0 else 0
    prev_breakout = (
        prev["close"] > breakout_level
        and prev_vol_ratio >= CONFIG["microStrategy22BreakVolumeRatio"]
        and prev["close"] > ema9[-2] >= ema21[-2]
    )
    retest = (
        current["low"] <= breakout_level * (1 + CONFIG["microStrategy22RetestTolerancePct"] / 100)
        and current["close"] >= breakout_level * (1 + CONFIG["microStrategy22HoldPct"] / 100)
    )
    trend_filter = (
        base.get("pct2h", 0) >= CONFIG["microStrategy22MinPct2h"]
        and base.get("pct3h", 0) >= CONFIG["microStrategy22MinPct3h"]
        and base.get("pct1h", 0) <= CONFIG["microStrategy22MaxPct1h"]
        and base.get("pct15", 0) <= CONFIG["microStrategy22MaxPct15m"]
    )
    candle_filter = (
        current["close"] > current["open"]
        and current["close"] > ema9[-1]
        and base.get("volumeRatio", 0) >= CONFIG["microStrategy22ConfirmVolumeRatio"]
        and upper_wick_ratio <= CONFIG["microStrategy22MaxUpperWickRatio"]
    )
    buy_signal = prev_breakout and retest and trend_filter and candle_filter
    base.update({
        "buy": buy_signal,
        "reason": "strategy22_2h_breakout_retest" if buy_signal else "strategy22_watch",
        "strategy22PrevBreakout": prev_breakout,
        "strategy22Retest": retest,
        "strategy22TrendFilter": trend_filter,
        "strategy22CandleFilter": candle_filter,
        "strategy22BreakoutLevel": rnd(breakout_level, 8),
        "strategy22PrevVolumeRatio": rnd(prev_vol_ratio),
        "strategy22UpperWickRatio": rnd(upper_wick_ratio),
        "strategy22Params": {
            "topN": CONFIG["microStrategy22TopN"],
            "min2": CONFIG["microStrategy22MinPct2h"],
            "min3": CONFIG["microStrategy22MinPct3h"],
            "max1": CONFIG["microStrategy22MaxPct1h"],
            "max15": CONFIG["microStrategy22MaxPct15m"],
            "bvol": CONFIG["microStrategy22BreakVolumeRatio"],
            "cvol": CONFIG["microStrategy22ConfirmVolumeRatio"],
            "tol": CONFIG["microStrategy22RetestTolerancePct"],
        },
    })
    return base


def micro_strategy22_should_exit(signal, state, price):
    entry = state.get("avgEntry", 0)
    if not entry:
        return False
    stop_price = entry * (1 - CONFIG["microStrategy22StopLossPct"] / 100)
    breakeven_stop = state.get("breakevenStopPrice")
    peak = max(state.get("peakPrice", price), price)
    peak_gain = ((peak - entry) / entry) * 100 if entry else 0
    giveback = ((peak - price) / peak) * 100 if peak else 0
    age_bars = (signal.get("time", 0) - state.get("entryTime", 0)) / (micro_bar_minutes() * 60 * 1000) if state.get("entryTime") else 0
    pnl = ((price - entry) / entry) * 100 if entry else 0

    if signal.get("lastLow", price) <= stop_price:
        set_micro_exit(signal, "strategy22_stop_loss_0_7pct", 1.0, stop_price)
    elif breakeven_stop and signal.get("lastLow", price) <= breakeven_stop:
        set_micro_exit(signal, "strategy22_breakeven_stop_after_tp1", 1.0, breakeven_stop)
    elif not state.get("tp1Taken") and price >= entry * (1 + CONFIG["microStrategy22TakeProfit1Pct"] / 100):
        state["tp1Taken"] = True
        state["breakevenStopPrice"] = entry * (1 + CONFIG["microStrategy22BreakevenLockPct"] / 100)
        set_micro_exit(signal, "strategy22_tp1_partial_move_stop_breakeven", CONFIG["microStrategy22TakeProfit1Fraction"], price)
    elif state.get("tp1Taken") and price >= entry * (1 + CONFIG["microStrategy22TakeProfit2Pct"] / 100):
        set_micro_exit(signal, "strategy22_tp2_or_runner_exit", 1.0, price)
    elif state.get("tp1Taken") and peak_gain >= CONFIG["microStrategy22TrailingStartPct"] and giveback >= CONFIG["microStrategy22TrailingGivebackPct"]:
        set_micro_exit(signal, "strategy22_trailing_runner_giveback")
    elif age_bars >= CONFIG["microStrategy22SoftTimeStopBars"]:
        if pnl >= CONFIG["microStrategy22MinProgressPct"] and price >= signal.get("ma20", price) and age_bars < CONFIG["microStrategy22HardTimeStopBars"]:
            return False
        set_micro_exit(signal, "strategy22_time_stop")
    elif price < signal.get("ma20", price) and price < entry:
        set_micro_exit(signal, "strategy22_ema_exit")
    return bool(signal.get("exitReason"))

def shortlist_micro_tickers(tickers):
    rows = []
    for ticker in tickers:
        inst_id = ticker.get("instId", "")
        parts = inst_id.split("-")
        if not is_micro_usdt_inst(parts):
            continue
        quote_vol = safe_float(ticker.get("volCcy24h"))
        if quote_vol < CONFIG["microMinQuoteVolume24h"] or quote_vol > CONFIG["microMaxQuoteVolume24h"]:
            continue
        last = safe_float(ticker.get("last"))
        open24h = safe_float(ticker.get("open24h"))
        if last <= 0 or open24h <= 0:
            continue
        pct24 = ((last - open24h) / open24h) * 100
        if pct24 < -15 or pct24 > 120:
            continue
        rows.append({**ticker, "_quoteVol": quote_vol, "_pct24": pct24})
    rows.sort(key=lambda row: row["_quoteVol"], reverse=True)
    return rows[:CONFIG["microScanLimit"]]


def is_micro_usdt_inst(parts):
    if len(parts) == 2:
        base, quote = parts
        return quote == "USDT" and base not in MICRO_EXCLUDED_BASES and base not in MICRO_EXCLUDED_SYNTHETIC_BASES
    if len(parts) == 3:
        base, quote, contract = parts
        return quote == "USDT" and contract == "SWAP" and base not in MICRO_EXCLUDED_BASES and base not in MICRO_EXCLUDED_SYNTHETIC_BASES
    return False


def micro_trend_signal(ticker, candles):
    bars_per_hour = micro_bars_per_hour()
    bars_15m = max(1, round(bars_per_hour / 4))
    bars_2h = bars_per_hour * 2
    bars_3h = bars_per_hour * 3
    bars_6h = bars_per_hour * 6
    bars_12h = bars_per_hour * 12
    close = candles[-1]["close"]
    last_low = candles[-1]["low"]
    prev_close = candles[-2]["close"]
    close_15m = candles[-(bars_15m + 1)]["close"] if len(candles) > bars_15m else prev_close
    close_1h = candles[-(bars_per_hour + 1)]["close"] if len(candles) > bars_per_hour else prev_close
    close_2h = candles[-(bars_2h + 1)]["close"] if len(candles) > bars_2h else candles[0]["close"]
    close_3h = candles[-(bars_3h + 1)]["close"] if len(candles) > bars_3h else candles[0]["close"]
    close_6h = candles[-(bars_6h + 1)]["close"] if len(candles) > bars_6h else candles[0]["close"]
    close_12h = candles[-(bars_12h + 1)]["close"] if len(candles) > bars_12h else candles[0]["close"]
    pct5 = ((close - prev_close) / prev_close) * 100 if prev_close else 0
    pct15 = ((close - close_15m) / close_15m) * 100 if close_15m else 0
    pct1h = ((close - close_1h) / close_1h) * 100 if close_1h else 0
    pct2h = ((close - close_2h) / close_2h) * 100 if close_2h else 0
    pct3h = ((close - close_3h) / close_3h) * 100 if close_3h else 0
    pct6h = ((close - close_6h) / close_6h) * 100 if close_6h else 0
    pct12h = ((close - close_12h) / close_12h) * 100 if close_12h else 0
    volumes = [c["volume"] for c in candles]
    recent_vol = sma(volumes, 6) or candles[-1]["volume"]
    mid_vol = sma(volumes[-18:-6], 12) or 0
    base_vol = sma(volumes[-72:-12], 60) or sma(volumes[-36:-6], 30) or 0
    volume_ratio = recent_vol / base_vol if base_vol else 0
    volume_accel = recent_vol / mid_vol if mid_vol else 0
    prior_high = max(c["high"] for c in candles[-(bars_per_hour + 1):-1])
    closes = [c["close"] for c in candles]
    ma5 = sma(closes, 5) or close
    ma20 = sma(closes, 20) or close
    ma60 = sma(closes, 60) or close
    distance_ma60 = ((close - ma60) / ma60) * 100 if ma60 else 0
    ma20_prev = sma(closes[:-12], 20) or ma20
    ma60_prev = sma(closes[:-12], 60) or ma60
    ma60_prev24 = sma(closes[:-24], 60) or ma60
    ma20_slope = ((ma20 - ma20_prev) / ma20_prev) * 100 if ma20_prev else 0
    ma60_slope = ((ma60 - ma60_prev) / ma60_prev) * 100 if ma60_prev else 0
    ma60_slope24 = ((ma60 - ma60_prev24) / ma60_prev24) * 100 if ma60_prev24 else 0
    stacked = close > ma20 >= ma60 and ma5 > ma60
    ma_crossing_up = ma20 >= ma60 or (ma20 >= ma60 * 0.995 and ma20_slope > ma60_slope)
    compact_range = (max(c["high"] for c in candles[-37:-1]) - min(c["low"] for c in candles[-37:-1])) / close * 100 if close else 999
    breakout = close > prior_high
    quiet_lift = compact_range < 4 and volume_ratio >= CONFIG["microEarlyVolumeRatio"] and volume_accel >= 1.05 and close > ma20
    volume_rising = volume_ratio >= CONFIG["microTrendVolumeRatio"] or quiet_lift
    entry_volume_ok = CONFIG["microEntryMinVolumeRatio"] <= volume_ratio <= CONFIG["microEntryMaxVolumeRatio"]
    chase_risk = pct1h > CONFIG["microNoChasePct1h"] and compact_range > CONFIG["microNoChaseRangePct"]
    not_overextended = (
        pct1h <= CONFIG["microTrendMaxPct1h"]
        and pct15 <= CONFIG["microTrendMaxPct15m"]
        and distance_ma60 <= CONFIG["microMaxDistanceMa60Pct"]
        and pct15 <= CONFIG["microEntryMaxPct15m"]
        and compact_range <= CONFIG["microEntryMaxRangePct"]
        and not chase_risk
    )
    trend_ok = (
        close > ma60
        and ma_crossing_up
        and ma60_slope > 0
        and ma60_slope24 >= 0
        and pct1h >= CONFIG["microTrendMinPct1h"]
        and pct15 >= CONFIG["microTrendMinPct15m"]
        and entry_volume_ok
        and not_overextended
    )
    buy = (
        trend_ok
        and breakout
    )
    trend_score = (pct1h * 1.2) + (pct15 * 0.8) + (volume_ratio * 2) + (volume_accel * 1.5) + (ma20_slope * 2) + (ma60_slope * 4) + (ma60_slope24 * 2)
    exit_reason = ""
    if ma20 < ma60:
        exit_reason = "ma20_below_ma60"
    return {
        "instId": ticker["instId"],
        "price": rnd(close, 8),
        "lastLow": rnd(last_low, 8),
        "pct5": rnd(pct5),
        "pct15": rnd(pct15),
        "pct1h": rnd(pct1h),
        "pct2h": rnd(pct2h),
        "pct3h": rnd(pct3h),
        "pct6h": rnd(pct6h),
        "pct12h": rnd(pct12h),
        "pct24": rnd(ticker.get("_pct24", 0)),
        "quoteVolume24h": rnd(ticker.get("_quoteVol", 0)),
        "volumeRatio": rnd(volume_ratio),
        "volumeAccel": rnd(volume_accel),
        "compactRangePct": rnd(compact_range),
        "ma5": rnd(ma5, 8),
        "ma20": rnd(ma20, 8),
        "ma60": rnd(ma60, 8),
        "distanceMa60Pct": rnd(distance_ma60),
        "ma20Slope": rnd(ma20_slope),
        "ma60Slope": rnd(ma60_slope),
        "ma60Slope24": rnd(ma60_slope24),
        "stacked": stacked,
        "breakout": breakout,
        "priorHigh": rnd(prior_high, 8),
        "quietLift": quiet_lift,
        "volumeRising": volume_rising,
        "entryVolumeOk": entry_volume_ok,
        "entryVolumeTooHot": volume_ratio > CONFIG["microEntryMaxVolumeRatio"],
        "chaseRisk": chase_risk,
        "trendOk": trend_ok,
        "notOverextended": not_overextended,
        "trendScore": rnd(trend_score),
        "exitReason": exit_reason,
        "buy": buy,
        "time": candles[-1]["closeTime"],
        "pre1hCandles": candles[-(bars_per_hour + 1):-1],
        "reason": "ma_stack_volume_trend" if buy else "watch",
    }


def update_micro_position_state(state, price, signal):
    state["peakPrice"] = max(state.get("peakPrice", state.get("avgEntry", price)), price)
    state["belowMa60Count"] = state.get("belowMa60Count", 0) + 1 if price < signal["ma60"] else 0


def micro_entry_confirmed(state, signal, price):
    pending = state.get("pendingEntry") or {}
    breakout_level = pending.get("breakoutLevel")
    if not breakout_level:
        return False
    if signal["time"] <= pending.get("time", 0):
        return False
    if signal["time"] > pending.get("expiresAt", 0):
        return False
    current_breakout_level = signal.get("priorHigh") or breakout_level
    confirm_price = max(breakout_level, current_breakout_level) * (1 + CONFIG["microConfirmBreakoutBufferPct"] / 100)
    return (
        price >= confirm_price
        and signal.get("breakout")
        and signal.get("trendOk")
        and signal.get("entryVolumeOk")
        and signal.get("notOverextended")
    )


def micro_top10_quality_score(params, base, candles, rank_1h, entry_change_1h):
    current = candles[-1]
    close = float(current["close"])
    open_ = float(current["open"])
    high = float(current["high"])
    low = float(current["low"])
    candle_range = max(high - low, close * 0.0001)
    upper_wick_ratio = (high - close) / candle_range
    body_ratio = abs(close - open_) / candle_range
    close_position = (close - low) / candle_range
    closes = [c["close"] for c in candles]
    ema9_values = ema_series(closes, 9)
    ema21_values = ema_series(closes, 21)
    ema9 = ema9_values[-1] if ema9_values else None
    ema21 = ema21_values[-1] if ema21_values else None
    atr_value = atr(candles, 14)
    atr_pct = (atr_value / close) * 100 if atr_value and close else None
    score = 0.0
    if rank_1h is not None:
        score += max(0, 6 - int(rank_1h)) * float(params.get("quality_rank_weight", 8.0))
    score += max(
        0,
        float(params.get("quality_change_peak_score", 25.0))
        - abs(float(entry_change_1h or 0) - float(params.get("quality_change_peak_pct", 5.0))) * float(params.get("quality_change_penalty", 7.0)),
    )
    score += min(
        float(params.get("quality_volume_cap_score", 20.0)),
        max(0.0, float(base.get("volumeRatio", 0) or 0)) * float(params.get("quality_volume_weight", 8.0)),
    )
    if ema9 is not None and ema21 is not None and ema9 > ema21:
        score += float(params.get("quality_ema_bonus", 12.0))
    if close > open_:
        score += float(params.get("quality_green_bonus", 8.0))
    if upper_wick_ratio <= float(params.get("quality_max_upper_wick_ratio", 0.25)):
        score += float(params.get("quality_upper_wick_bonus", 8.0))
    if close_position >= float(params.get("quality_min_close_position", 0.60)):
        score += float(params.get("quality_close_pos_bonus", 6.0))
    if body_ratio >= float(params.get("quality_min_body_ratio", 0.25)):
        score += float(params.get("quality_body_bonus", 5.0))
    if atr_pct is not None and atr_pct <= float(params.get("quality_atr_bonus_max_pct", 1.8)):
        score += float(params.get("quality_atr_bonus", 5.0))
    return {
        "score": score,
        "upperWickRatio": upper_wick_ratio,
        "bodyRatio": body_ratio,
        "closePosition": close_position,
        "ema9": ema9,
        "ema21": ema21,
        "atrPct": atr_pct,
    }


def micro_top10_optimized_signal(ticker, candles, strategy, rank_1h=None, collector_change_1h_pct=None, session_age_bars=0):
    params = MICRO_TOP10_OPTIMIZED_STRATEGIES[strategy]
    base = micro_trend_signal(ticker, candles)
    base["strategy"] = strategy
    base["buy"] = False
    base["reason"] = "top10_watch"
    base["rank1h"] = rank_1h
    base["top10SessionAgeBars"] = session_age_bars
    add_micro_slippage_snapshot(base, ticker)
    if len(candles) < max(13, micro_bars_per_hour() + 1):
        return base
    entry_change_1h = base.get("pct1h", 0) if collector_change_1h_pct is None else float(collector_change_1h_pct or 0)
    current_change_1h = float(base.get("pct1h", 0) or 0)
    min_current_change = float(params.get("min_current_change_1h_pct", 0.0) or 0.0)
    min_volume_ratio = float(params.get("min_volume_ratio", 0.0) or 0.0)
    rank_ok = rank_1h is not None and int(rank_1h) <= int(params["max_rank"])
    heat_ok = params["min_change_1h_pct"] <= entry_change_1h <= params["max_change_1h_pct"]
    current_change_ok = current_change_1h >= min_current_change
    reclaim_ok = True
    if params.get("require_change_reclaim"):
        reclaim_ok = current_change_1h >= entry_change_1h - 1.0
    volume_ok = float(base.get("volumeRatio", 0) or 0) >= min_volume_ratio
    # ⭐ PARITY FIX: optimizer enters at EXACTLY delay_bars after session start, not any bar after
    # This prevents multiple entry attempts per session and matches scan_top10_training_strategies.py logic
    delay_exact = int(session_age_bars or 0) == int(params.get("entry_delay_bars", 0))
    delay_ok = delay_exact
    base["top10DelayExact"] = delay_exact
    base["top10DelayOk"] = delay_ok  # keep for backward compat

    # ⭐ 新增：上影線過濾
    max_upper_wick_pct = float(params.get("max_upper_wick_pct", 99.9) or 99.9)
    last_bar = candles[-1] if candles else {}
    upper_wick_ok = True
    if max_upper_wick_pct < 99.9:
        high = float(last_bar.get("high", 0) or 0)
        low = float(last_bar.get("low", 0) or 0)
        close = float(last_bar.get("close", 0) or 0)
        open_ = float(last_bar.get("open", 0) or 0)
        if high > 0 and high != low:
            body = abs(close - open_)
            total_range = high - low
            upper_wick = high - max(close, open_)
            upper_wick_pct = (upper_wick / total_range) * 100
            upper_wick_ok = upper_wick_pct <= max_upper_wick_pct
            base["top10UpperWickPct"] = rnd(upper_wick_pct)
        else:
            upper_wick_ok = True
            base["top10UpperWickPct"] = 0.0
    base["top10MaxUpperWickPct"] = max_upper_wick_pct
    base["top10UpperWickOk"] = upper_wick_ok

    require_green_confirm = params.get("require_green_confirm", False)
    green_confirm_ok = True
    if require_green_confirm:
        last_close = float(last_bar.get("close", 0) or 0)
        last_open = float(last_bar.get("open", 0) or 0)
        green_confirm_ok = last_close >= last_open
        base["top10GreenConfirmOk"] = green_confirm_ok
    else:
        base["top10GreenConfirmOk"] = True

    quality_threshold = params.get("quality_score_threshold")
    quality = None
    quality_ok = True
    if quality_threshold is not None:
        quality = micro_top10_quality_score(params, base, candles, rank_1h, entry_change_1h)
        quality_ok = quality["score"] >= float(quality_threshold)

    base.update({
        "collectorChange1hPct": rnd(entry_change_1h),
        "top10CurrentChange1hPct": rnd(current_change_1h),
        "top10RankOk": rank_ok,
        "top10HeatOk": heat_ok,
        "top10CurrentChangeOk": current_change_ok,
        "top10ReclaimOk": reclaim_ok,
        "top10VolumeOk": volume_ok,
        "top10DelayOk": delay_ok,
        "top10UpperWickOk": upper_wick_ok,
        "top10GreenConfirmOk": green_confirm_ok,
        "top10QualityScoreOk": quality_ok,
        "top10EntryDelayBars": params.get("entry_delay_bars", 0),
        "top10EntryMaxRank": params["max_rank"],
        "top10MinChange1hPct": params["min_change_1h_pct"],
        "top10MaxChange1hPct": params["max_change_1h_pct"],
        "top10MinCurrentChange1hPct": min_current_change,
        "top10MinVolumeRatio": min_volume_ratio,
        "top10MaxUpperWickPct": max_upper_wick_pct,
        "top10RequireGreenConfirm": require_green_confirm,
        "top10QualityScoreThreshold": quality_threshold,
    })
    if quality is not None:
        base.update({
            "top10QualityScore": rnd(quality["score"]),
            "top10QualityUpperWickRatio": rnd(quality["upperWickRatio"]),
            "top10QualityBodyRatio": rnd(quality["bodyRatio"]),
            "top10QualityClosePosition": rnd(quality["closePosition"]),
            "top10QualityEma9": rnd(quality["ema9"], 8) if quality["ema9"] is not None else None,
            "top10QualityEma21": rnd(quality["ema21"], 8) if quality["ema21"] is not None else None,
            "top10QualityAtrPct": rnd(quality["atrPct"]) if quality["atrPct"] is not None else None,
        })

    # ⭐ 新增：reclaim_entry_price 邏輯
    # 如果需要回踩確認，在 buy=True 時設定 pending_reclaim 狀態
    # 真正觸發進場會在下一根 K 線確認價格是否回到進場價
    base["top10ReclaimEntryRequired"] = params.get("reclaim_entry_price", False)
    if base["top10ReclaimEntryRequired"]:
        base["top10ReclaimEntryPrice"] = float(last_bar.get("close", 0) or 0)

    # ⭐ 新增：spread filter (max_spread_pct)
    max_spread_pct = float(params.get("max_spread_pct", 99.9) or 99.9)
    spread_ok = True
    if max_spread_pct < 99.9:
        bid = float(ticker.get("bidPx", 0) or 0)
        ask = float(ticker.get("askPx", 0) or 0)
        mid = (bid + ask) / 2 if (bid and ask) else 0
        if mid > 0:
            spread_pct = ((ask - bid) / mid) * 100
            spread_ok = spread_pct <= max_spread_pct
            base["top10SpreadPct"] = rnd(spread_pct)
        else:
            spread_ok = True
            base["top10SpreadPct"] = 0.0
    base["top10MaxSpreadPct"] = max_spread_pct
    base["top10SpreadOk"] = spread_ok

    # ⭐ 新增：trend filter (pct2h/pct3h positive)
    min_pct2h = float(params.get("min_pct2h_pct", -99.9) or -99.9)
    min_pct3h = float(params.get("min_pct3h_pct", -99.9) or -99.9)
    pct2h_ok = True
    pct3h_ok = True
    pct2h_val = base.get("pct2h", base.get("pct2h_pct", 0.0))
    pct3h_val = base.get("pct3h", base.get("pct3h_pct", 0.0))
    if min_pct2h > -99.9:
        pct2h_ok = float(pct2h_val or 0) >= min_pct2h
    if min_pct3h > -99.9:
        pct3h_ok = float(pct3h_val or 0) >= min_pct3h
    base["top10Pct2h"] = rnd(pct2h_val)
    base["top10Pct3h"] = rnd(pct3h_val)
    base["top10MinPct2hPct"] = min_pct2h
    base["top10MinPct3hPct"] = min_pct3h
    base["top10Pct2hOk"] = pct2h_ok
    base["top10Pct3hOk"] = pct3h_ok

    if rank_ok and heat_ok and current_change_ok and reclaim_ok and volume_ok and delay_ok and quality_ok and upper_wick_ok and green_confirm_ok and spread_ok and pct2h_ok and pct3h_ok:
        if params.get("reclaim_entry_price", False):
            # 不立即買入，設定 pending 狀態等待回踩
            base["buy"] = False
            base["reason"] = f"{params['version']}_top10_pending_reclaim"
            base["top10PendingReclaim"] = True
        else:
            base["buy"] = True
            base["reason"] = f"{params['version']}_top10_entry"
    return base


def _fmt_pct_for_reason(value):
    text = f"{float(value):g}".replace(".", "_")
    return text


def micro_top10_optimized_should_exit(signal, state, price, strategy):
    params = MICRO_TOP10_OPTIMIZED_STRATEGIES[strategy]
    version = params["version"]
    entry = state.get("avgEntry", 0)
    if not entry:
        return False
    stop_price = entry * (1 - params["stop_loss_pct"] / 100)
    peak = max(state.get("peakPrice", price), price)
    peak_gain = ((peak - entry) / entry) * 100 if entry else 0
    giveback = ((peak - price) / peak) * 100 if peak else 0
    active_stop = stop_price
    if peak_gain >= params["breakeven_after_pct"]:
        active_stop = max(active_stop, entry)
    if peak_gain >= params["trailing_start_pct"]:
        active_stop = max(active_stop, peak * (1 - params["trailing_giveback_pct"] / 100))
    if signal.get("lastLow", price) <= active_stop:
        if active_stop <= stop_price + 1e-12:
            reason = f"{version}_stop_loss_{_fmt_pct_for_reason(params['stop_loss_pct'])}pct"
        else:
            reason = f"{version}_breakeven_or_trailing_stop"
        set_micro_exit(signal, reason, 1.0, active_stop)
        return True
    entry_time = state.get("entryTime")
    held_bars = (signal.get("time", 0) - entry_time) / (micro_bar_minutes() * 60 * 1000) if entry_time is not None else 0
    if held_bars >= params["time_stop_bars"]:
        set_micro_exit(signal, f"{version}_time_stop", 1.0, price)
        return True
    return False


def set_micro_exit(signal, reason, fraction=1.0, price=None):
    signal["exitReason"] = reason
    signal["exitFraction"] = fraction
    if price is not None:
        signal["exitPrice"] = price


def micro_should_exit(signal, state, price):
    entry = state.get("avgEntry", 0)
    if not entry:
        return False
    stop_price = entry * (1 - CONFIG["microStopLossPct"] / 100)
    breakeven_stop = state.get("breakevenStopPrice")
    peak = max(state.get("peakPrice", price), price)
    peak_gain = ((peak - entry) / entry) * 100
    giveback = ((peak - price) / peak) * 100 if peak else 0

    if signal.get("lastLow", price) <= stop_price:
        set_micro_exit(signal, "stop_loss_1pct", 1.0, stop_price)
    elif breakeven_stop and signal.get("lastLow", price) <= breakeven_stop:
        set_micro_exit(signal, "breakeven_stop_after_tp1", 1.0, breakeven_stop)
    elif not state.get("tp1Taken") and price >= entry * (1 + CONFIG["microTakeProfit1Pct"] / 100):
        state["tp1Taken"] = True
        state["breakevenStopPrice"] = entry * (1 + CONFIG["microBreakevenLockPct"] / 100)
        set_micro_exit(signal, "tp1_take_half_move_stop_breakeven", 0.5, price)
    elif state.get("tp1Taken") and not state.get("tp2Taken") and price >= entry * (1 + CONFIG["microTakeProfit2Pct"] / 100):
        state["tp2Taken"] = True
        set_micro_exit(signal, "tp2_take_quarter_keep_runner", 0.5, price)
    elif entry and price < entry and signal.get("pct15", 0) <= CONFIG["microEarlyExitPct15m"]:
        set_micro_exit(signal, "early_momentum_loss_15m")
    elif state.get("belowMa60Count", 0) >= 2:
        set_micro_exit(signal, "two_closes_below_ma60")
    elif peak_gain >= CONFIG["microTrailingStartPct"] and giveback >= CONFIG["microTrailingGivebackPct"]:
        set_micro_exit(signal, "trailing_runner_giveback")
    return bool(signal.get("exitReason"))


def micro_strategy2_should_enter(signal):
    return (
        signal.get("pct1h", 0) >= CONFIG["microStrategy2MinPct1h"]
        and signal.get("pct1h", 0) <= CONFIG["microStrategy2MaxPct1h"]
        and signal.get("pct15", 0) >= CONFIG["microStrategy2MinPct15m"]
        and CONFIG["microStrategy2MinVolumeRatio"] <= signal.get("volumeRatio", 0) <= CONFIG["microStrategy2MaxVolumeRatio"]
        and signal.get("price", 0) > signal.get("ma20", 0)
    )


def micro_strategy2_should_exit(signal, state, price):
    entry = state.get("avgEntry", 0)
    if not entry:
        return False
    stop_price = entry * (1 - CONFIG["microStrategy2StopLossPct"] / 100)
    if signal.get("lastLow", price) <= stop_price:
        set_micro_exit(signal, "strategy2_stop_loss_1pct", 1.0, stop_price)
        return True
    age_minutes = (signal.get("time", 0) - state.get("entryTime", 0)) / 60000 if state.get("entryTime") else 0
    peak = state.get("peakPrice", price)
    peak_gain = ((peak - entry) / entry) * 100 if entry else 0
    giveback = ((peak - price) / peak) * 100 if peak else 0
    if age_minutes >= CONFIG["microStrategy2NoFollowMinutes"] and peak_gain < CONFIG["microStrategy2NoFollowMinGainPct"]:
        set_micro_exit(signal, "strategy2_no_follow_through")
        return True
    if peak_gain >= CONFIG["microStrategy2TrailingStartPct"] and giveback >= CONFIG["microStrategy2TrailingGivebackPct"]:
        set_micro_exit(signal, "strategy2_trailing_giveback")
        return True
    if price < entry and signal.get("pct15", 0) <= CONFIG["microEarlyExitPct15m"]:
        set_micro_exit(signal, "strategy2_momentum_loss_15m")
        return True
    return False




def micro_strategy21_surge_signal(signal):
    out = dict(signal)
    out["strategy"] = "strategy2.1_surge_momentum"
    out["buy"] = False
    out["reason"] = "strategy2.1_watch"
    add_micro_slippage_snapshot(out, signal)
    spread_pct = out.get("spreadPct")
    spread_ok = spread_pct is None or spread_pct <= CONFIG["microStrategy21SurgeMaxSpreadPct"]
    heat_ok = (
        CONFIG["microStrategy21SurgeMinPct1h"] <= out.get("pct1h", 0) <= CONFIG["microStrategy21SurgeMaxPct1h"]
        and CONFIG["microStrategy21SurgeMinPct15m"] <= out.get("pct15", 0) <= CONFIG["microStrategy21SurgeMaxPct15m"]
        and CONFIG["microStrategy21SurgeMinVolumeRatio"] <= out.get("volumeRatio", 0) <= CONFIG["microStrategy21SurgeMaxVolumeRatio"]
        and out.get("distanceMa60Pct", 0) <= CONFIG["microStrategy21SurgeMaxDistanceMa60Pct"]
    )
    structure_ok = (
        out.get("price", 0) > out.get("ma20", 0) >= out.get("ma60", 0)
        and out.get("ma60Slope", 0) >= 0
        and out.get("notOverextended", False)
        and not out.get("chaseRisk", False)
    )
    buy_signal = bool(heat_ok and structure_ok and spread_ok)
    out.update({
        "buy": buy_signal,
        "reason": "strategy2.1_filtered_surge_momentum" if buy_signal else "strategy2.1_watch",
        "strategy21SurgeHeatOk": heat_ok,
        "strategy21SurgeStructureOk": structure_ok,
        "strategy21SurgeSpreadOk": spread_ok,
    })
    return out


def micro_strategy21_surge_should_exit(signal, state, price):
    entry = state.get("avgEntry", 0)
    if not entry:
        return False
    stop_price = entry * (1 - CONFIG["microStrategy21SurgeStopLossPct"] / 100)
    if signal.get("lastLow", price) <= stop_price:
        set_micro_exit(signal, "strategy2.1_stop_loss_0_7pct", 1.0, stop_price)
        return True
    age_minutes = (signal.get("time", 0) - state.get("entryTime", 0)) / 60000 if state.get("entryTime") else 0
    peak = state.get("peakPrice", price)
    peak_gain = ((peak - entry) / entry) * 100 if entry else 0
    giveback = ((peak - price) / peak) * 100 if peak else 0
    if age_minutes >= CONFIG["microStrategy21SurgeNoFollowMinutes"] and peak_gain < CONFIG["microStrategy21SurgeNoFollowMinGainPct"]:
        set_micro_exit(signal, "strategy2.1_no_follow_through")
        return True
    if peak_gain >= CONFIG["microStrategy21SurgeTrailingStartPct"] and giveback >= CONFIG["microStrategy21SurgeTrailingGivebackPct"]:
        set_micro_exit(signal, "strategy2.1_trailing_giveback")
        return True
    if price < entry and signal.get("pct15", 0) <= CONFIG["microEarlyExitPct15m"]:
        set_micro_exit(signal, "strategy2.1_momentum_loss_15m")
        return True
    return False


def micro_state_key(strategy, inst_id):
    return inst_id if strategy == "strategy1" else f"{strategy}::{inst_id}"


def new_micro_state():
    return {"assetQty": 0.0, "avgEntry": 0.0, "margin": 0.0, "leverage": CONFIG["microLeverage"], "notional": 0.0, "peakPrice": 0.0, "belowMa60Count": 0, "realizedPnl": 0.0, "trades": 0, "closedTrades": 0, "wins": 0}


def micro_position_row(inst_id, state, price, signal, strategy="strategy1"):
    entry = state.get("avgEntry", 0)
    qty = state.get("assetQty", 0)
    value = qty * price
    unreal = (price - entry) * qty if entry else 0
    margin = state.get("margin") or (value / (state.get("leverage") or CONFIG["microLeverage"]) if value else CONFIG["microMarginUSDT"])
    return {
        "instId": inst_id,
        "strategy": strategy,
        "price": rnd(price, 8),
        "avgEntry": rnd(entry, 8),
        "quantity": rnd(qty, 8),
        "margin": rnd(margin),
        "leverage": rnd(state.get("leverage", CONFIG["microLeverage"])),
        "notional": rnd(value),
        "positionValue": rnd(value),
        "unrealizedPnl": rnd(unreal),
        "unrealizedPnlPct": rnd(((price - entry) / entry) * 100 if entry else 0),
        "unrealizedRoePct": rnd((unreal / margin) * 100 if margin else 0),
        "ma20": signal["ma20"],
        "ma60": signal["ma60"],
        "distanceToMa20Pct": rnd(((price - signal["ma20"]) / signal["ma20"]) * 100 if signal["ma20"] else 0),
        "distanceToMa60Pct": rnd(((price - signal["ma60"]) / signal["ma60"]) * 100 if signal["ma60"] else 0),
        "peakPrice": rnd(state.get("peakPrice", price), 8),
        "givebackPct": rnd(((state.get("peakPrice", price) - price) / state.get("peakPrice", price)) * 100 if state.get("peakPrice", price) else 0),
        "belowMa60Count": state.get("belowMa60Count", 0),
        "realizedPnl": rnd(state.get("realizedPnl", 0)),
        "trades": state.get("trades", 0),
        "closedTrades": state.get("closedTrades", 0),
        "winRate": rnd((state.get("wins", 0) / state.get("closedTrades", 0)) * 100 if state.get("closedTrades", 0) else 0),
    }


def build_micro_entry_exit_records(rows):
    """Pair micro BUY/SELL rows into compact entry/exit performance records.

    Rows may be in either ascending or descending time order. Partial exits are
    accumulated into one record and marked closed when the original quantity is
    fully exited.
    """
    ordered = sorted(rows, key=lambda row: (row["ts"], row.get("id", 0)))
    records = []
    open_lots = {}
    for row in ordered:
        key = (row.get("strategy") or "strategy1", row["inst_id"])
        if row["side"] == "BUY":
            open_lots[key] = {
                "strategy": key[0],
                "inst_id": key[1],
                "entry_time": row["ts"],
                "exit_time": None,
                "entry_price": float(row["price"]),
                "exit_price": None,
                "quantity": float(row["quantity"]),
                "remaining_qty": float(row["quantity"]),
                "quote_amount": float(row.get("quote_amount") or 0),
                "pnl": 0.0,
                "pnl_pct": None,
                "pnl_roe_pct": None,
                "status": "open",
            }
        elif row["side"] == "SELL" and key in open_lots:
            lot = open_lots[key]
            entry = lot["entry_price"]
            exit_price = float(row["price"])
            qty = min(float(row["quantity"]), lot["remaining_qty"])
            pnl = (exit_price - entry) * qty
            lot["pnl"] += pnl
            lot["remaining_qty"] -= qty
            lot["exit_time"] = row["ts"]
            lot["exit_price"] = exit_price
            closed = lot["remaining_qty"] <= max(lot["quantity"] * 0.000001, 1e-12)
            if closed:
                invested = lot["entry_price"] * lot["quantity"]
                margin = lot["quote_amount"] / CONFIG["microLeverage"] if CONFIG["microLeverage"] else 0
                lot["status"] = "closed"
                lot["pnl"] = rnd(lot["pnl"])
                lot["pnl_pct"] = rnd((lot["pnl"] / invested) * 100 if invested else 0)
                lot["pnl_roe_pct"] = rnd((lot["pnl"] / margin) * 100 if margin else 0)
                records.append(lot)
                open_lots.pop(key, None)
    for lot in open_lots.values():
        lot["pnl"] = None
        records.append(lot)
    records.sort(key=lambda row: row["exit_time"] or row["entry_time"], reverse=True)
    return records


def summarize_micro_strategy_performance_12h(records, since):
    groups = {}
    for row in records:
        entry_time = row["entry_time"]
        exit_time = row.get("exit_time")
        if entry_time < since and (not exit_time or exit_time < since):
            continue
        strategy = row.get("strategy") or "strategy1"
        item = groups.setdefault(strategy, {
            "strategy": strategy,
            "entries": 0,
            "closedTrades": 0,
            "wins": 0,
            "losses": 0,
            "openTrades": 0,
            "realizedPnl": 0.0,
            "avgPnlRoePct": 0.0,
        })
        if entry_time >= since:
            item["entries"] += 1
        if row.get("status") == "closed" and exit_time and exit_time >= since:
            pnl = float(row.get("pnl") or 0)
            item["closedTrades"] += 1
            item["realizedPnl"] += pnl
            item["avgPnlRoePct"] += float(row.get("pnl_roe_pct") or 0)
            if pnl > 0:
                item["wins"] += 1
            else:
                item["losses"] += 1
        elif row.get("status") == "open":
            item["openTrades"] += 1
    result = []
    for item in groups.values():
        closed = item["closedTrades"]
        item["realizedPnl"] = rnd(item["realizedPnl"])
        item["winRate"] = rnd((item["wins"] / closed) * 100 if closed else 0)
        item["avgPnlRoePct"] = rnd(item["avgPnlRoePct"] / closed if closed else 0)
        result.append(item)
    result.sort(key=lambda row: (row["realizedPnl"], row["winRate"], row["closedTrades"]), reverse=True)
    return result



def floor_micro_12h_window(dt):
    """Floor to the canonical LIGHTOARTS 12h boundary: 09:00/21:00 Asia/Taipei."""
    dt_tpe = dt.astimezone(TW_TZ)
    if dt_tpe.hour < 9:
        boundary = (dt_tpe - timedelta(days=1)).replace(hour=21, minute=0, second=0, microsecond=0)
    elif dt_tpe.hour < 21:
        boundary = dt_tpe.replace(hour=9, minute=0, second=0, microsecond=0)
    else:
        boundary = dt_tpe.replace(hour=21, minute=0, second=0, microsecond=0)
    return boundary.astimezone(timezone.utc)


def latest_completed_micro_report_window_start(dt):
    """Return the previous completed 12h report window start for 09:00/21:00 Taipei reports."""
    latest_slot_end = floor_micro_12h_window(dt)
    return latest_slot_end - timedelta(hours=12)


def micro_report_slot_label(window_end):
    return window_end.astimezone(TW_TZ).isoformat(timespec="minutes")


def summarize_micro_strategy_performance_window(records, window_start, window_end, strategies=None):
    groups = {}
    for strategy in strategies or []:
        groups.setdefault(strategy, {
            "strategy": strategy,
            "entries": 0,
            "closedTrades": 0,
            "wins": 0,
            "losses": 0,
            "openTrades": 0,
            "realizedPnl": 0.0,
            "avgPnlRoePct": 0.0,
        })
    for row in records:
        entry_time = row["entry_time"]
        exit_time = row.get("exit_time")
        if entry_time >= window_end or (exit_time and exit_time < window_start) or (not exit_time and entry_time < window_start):
            continue
        strategy = row.get("strategy") or "strategy1"
        item = groups.setdefault(strategy, {
            "strategy": strategy,
            "entries": 0,
            "closedTrades": 0,
            "wins": 0,
            "losses": 0,
            "openTrades": 0,
            "realizedPnl": 0.0,
            "avgPnlRoePct": 0.0,
        })
        if window_start <= entry_time < window_end:
            item["entries"] += 1
        if row.get("status") == "closed" and exit_time and window_start <= exit_time < window_end:
            pnl = float(row.get("pnl") or 0)
            item["closedTrades"] += 1
            item["realizedPnl"] += pnl
            item["avgPnlRoePct"] += float(row.get("pnl_roe_pct") or 0)
            if pnl > 0:
                item["wins"] += 1
            else:
                item["losses"] += 1
        elif row.get("status") == "open" and entry_time < window_end:
            item["openTrades"] += 1
    result = []
    for item in groups.values():
        closed = item["closedTrades"]
        item["realizedPnl"] = rnd(item["realizedPnl"])
        item["winRate"] = rnd((item["wins"] / closed) * 100 if closed else 0)
        item["avgPnlRoePct"] = rnd(item["avgPnlRoePct"] / closed if closed else 0)
        result.append(item)
    result.sort(key=lambda row: (row["realizedPnl"], row["winRate"], row["closedTrades"], row["strategy"]), reverse=True)
    return result


def build_micro_strategy_performance_12h_history(records, now, strategies=None, max_windows=60):
    now = now.astimezone(timezone.utc)
    if records:
        first_time = min(row["entry_time"] for row in records).astimezone(timezone.utc)
        start = latest_completed_micro_report_window_start(first_time + timedelta(hours=12))
    else:
        start = latest_completed_micro_report_window_start(now)
    current_start = latest_completed_micro_report_window_start(now)
    windows = []
    cursor = current_start
    while cursor >= start and len(windows) < max_windows:
        window_end = cursor + timedelta(hours=12)
        rows = summarize_micro_strategy_performance_window(records, cursor, window_end, strategies)
        windows.append({
            "windowStart": cursor,
            "windowEnd": window_end,
            "snapshotSlotTaipei": micro_report_slot_label(window_end),
            "windowStartTaipei": cursor.astimezone(TW_TZ).isoformat(timespec="minutes"),
            "windowEndTaipei": window_end.astimezone(TW_TZ).isoformat(timespec="minutes"),
            "isCurrent": cursor == current_start,
            "rows": rows,
        })
        cursor -= timedelta(hours=12)
    return windows


def _micro_perf_window_has_data(row):
    return (
        int(row.get("entries") or 0) > 0
        or int(row.get("closedTrades") or 0) > 0
        or int(row.get("openTrades") or 0) > 0
        or abs(float(row.get("realizedPnl") or 0)) > 0
    )


def _coerce_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def group_micro_strategy_performance_12h_by_strategy(windows):
    strategies = {}
    for window in windows:
        for row in window.get("rows", []):
            if not _micro_perf_window_has_data(row):
                continue
            strategy = row.get("strategy") or "strategy1"
            item = strategies.setdefault(strategy, {"strategy": strategy, "windows": []})
            item["windows"].append({
                "windowStart": window["windowStart"],
                "windowEnd": window["windowEnd"],
                "isCurrent": window.get("isCurrent", False),
                "entries": row.get("entries", 0),
                "closedTrades": row.get("closedTrades", 0),
                "wins": row.get("wins", 0),
                "losses": row.get("losses", 0),
                "openTrades": row.get("openTrades", 0),
                "realizedPnl": row.get("realizedPnl", 0),
                "avgPnlRoePct": row.get("avgPnlRoePct", 0),
                "winRate": row.get("winRate", 0),
            })
    margin = CONFIG.get("microMarginUSDT") or 0
    for item in strategies.values():
        total_closed = sum(int(row.get("closedTrades") or 0) for row in item["windows"])
        total_pnl = sum(float(row.get("realizedPnl") or 0) for row in item["windows"])
        cumulative_return = (total_pnl / (total_closed * margin)) * 100 if total_closed and margin else 0
        starts = [_coerce_datetime(row.get("windowStart")) for row in item["windows"]]
        ends = [_coerce_datetime(row.get("windowEnd")) for row in item["windows"]]
        starts = [dt for dt in starts if dt]
        ends = [dt for dt in ends if dt]
        elapsed_days = max(((max(ends) - min(starts)).total_seconds() / 86400) if starts and ends else 0, 0.5)
        if cumulative_return <= -100:
            annualized_return = -100
        elif total_closed:
            annualized_return = ((1 + cumulative_return / 100) ** (365 / elapsed_days) - 1) * 100
        else:
            annualized_return = 0
        item["closedTrades"] = total_closed
        item["realizedPnl"] = rnd(total_pnl)
        item["cumulativeReturnPct"] = rnd(cumulative_return)
        item["annualizedReturnPct"] = rnd(annualized_return)
        item["elapsedDays"] = rnd(elapsed_days)
    return sorted(strategies.values(), key=lambda item: item["strategy"])


def format_micro_strategy_performance_12h_history(rows):
    windows = []
    by_start = {}
    for row in rows:
        start = row["window_start"]
        window_end = row["window_end"]
        if start != floor_micro_12h_window(start) or window_end != start + timedelta(hours=12):
            continue
        item = by_start.get(start)
        if item is None:
            window_end = row["window_end"]
            item = {
                "windowStart": start.isoformat(),
                "windowEnd": window_end.isoformat(),
                "snapshotSlotTaipei": micro_report_slot_label(window_end),
                "windowStartTaipei": start.astimezone(TW_TZ).isoformat(timespec="minutes"),
                "windowEndTaipei": window_end.astimezone(TW_TZ).isoformat(timespec="minutes"),
                "isCurrent": start == latest_completed_micro_report_window_start(datetime.now(timezone.utc)),
                "rows": [],
            }
            by_start[start] = item
            windows.append(item)
        item["rows"].append({
            "strategy": row["strategy"],
            "entries": row["entries"],
            "closedTrades": row["closed_trades"],
            "wins": row["wins"],
            "losses": row["losses"],
            "openTrades": row["open_trades"],
            "realizedPnl": rnd(float(row["realized_pnl"])),
            "avgPnlRoePct": rnd(float(row["avg_pnl_roe_pct"])),
            "winRate": rnd(float(row["win_rate"])),
        })
    current = windows[0] if windows else None
    return {"current": current, "history": windows, "byStrategy": group_micro_strategy_performance_12h_by_strategy(windows)}

def annotate_micro_trade_pnl(rows):
    annotated = []
    open_lots = {}
    for row in reversed(rows):
        key = (row.get("strategy") or "strategy1", row["inst_id"])
        item = dict(row)
        item["pnl"] = None
        item["pnlPct"] = None
        item["pnlRoePct"] = None
        if row["side"] == "BUY":
            open_lots[key] = {"row": row, "remainingQty": float(row["quantity"])}
        elif row["side"] == "SELL" and key in open_lots:
            lot = open_lots[key]
            buy_row = lot["row"]
            entry = float(buy_row["price"])
            exit_price = float(row["price"])
            quantity = min(float(row["quantity"]), lot["remainingQty"])
            pnl = (exit_price - entry) * quantity
            margin = float(buy_row["quote_amount"]) / CONFIG["microLeverage"] if CONFIG["microLeverage"] else 0
            item["entryPrice"] = entry
            item["pnl"] = rnd(pnl)
            item["pnlPct"] = rnd(((exit_price - entry) / entry) * 100 if entry else 0)
            item["pnlRoePct"] = rnd((pnl / margin) * 100 if margin else 0)
            lot["remainingQty"] -= quantity
            if lot["remainingQty"] <= max(float(buy_row["quantity"]) * 0.000001, 1e-12):
                open_lots.pop(key, None)
        annotated.append(item)
    return list(reversed(annotated))


def rebuild_micro_stats(rows):
    stats = {}
    open_lots = {}
    for row in rows:
        key = (row.get("strategy") or "strategy1", row["inst_id"])
        item = stats.setdefault(key, {"realizedPnl": 0.0, "trades": 0, "closedTrades": 0, "wins": 0})
        item["trades"] += 1
        if row["side"] == "BUY":
            qty = float(row["quantity"])
            open_lots[key] = {"row": row, "remainingQty": qty, "closedPnl": 0.0}
        elif row["side"] == "SELL":
            lot = open_lots.get(key)
            if not lot:
                continue
            buy_row = lot["row"]
            entry = float(buy_row["price"])
            exit_price = float(row["price"])
            quantity = min(float(row["quantity"]), lot["remainingQty"])
            pnl = (exit_price - entry) * quantity
            item["realizedPnl"] += pnl
            lot["closedPnl"] += pnl
            lot["remainingQty"] -= quantity
            if lot["remainingQty"] <= max(float(buy_row["quantity"]) * 0.000001, 1e-12):
                item["closedTrades"] += 1
                item["wins"] += 1 if lot["closedPnl"] > 0 else 0
                open_lots.pop(key, None)
    for item in stats.values():
        item["realizedPnl"] = rnd(item["realizedPnl"])
    return stats


def parse_datetime(value):
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def compact_candle(candle):
    return {
        "time": candle.get("time"),
        "open": rnd(candle.get("open"), 8),
        "high": rnd(candle.get("high"), 8),
        "low": rnd(candle.get("low"), 8),
        "close": rnd(candle.get("close"), 8),
        "volume": rnd(candle.get("volume")),
        "closeTime": candle.get("closeTime"),
    }


def compact_micro_signal(signal):
    keys = [
        "instId", "price", "lastLow", "pct5", "pct15", "pct1h", "pct12h", "volumeRatio",
        "volumeAccel", "compactRangePct", "ma5", "ma20", "ma60", "distanceMa60Pct",
        "ma20Slope", "ma60Slope", "ma60Slope24", "stacked", "breakout", "priorHigh", "quietLift",
        "volumeRising", "entryVolumeOk", "chaseRisk", "trendOk", "notOverextended", "trendScore",
        "exitReason", "exitPrice", "buy", "time", "reason", "strategy",
    ]
    return {key: signal.get(key) for key in keys if key in signal}


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def dedupe_candles(candles):
    by_time = {candle["closeTime"]: candle for candle in candles}
    return [by_time[key] for key in sorted(by_time)]


def candle_from_db(row):
    ts_ms = int(row["ts"].timestamp() * 1000)
    return {
        "time": ts_ms,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
        "closeTime": ts_ms,
    }


def annotate_trade_pnl(rows):
    annotated = []
    open_lots = {}
    for row in reversed(rows):
        key = (row["symbol"], row["strategy"])
        item = dict(row)
        item["pnl"] = None
        item["pnlPct"] = None
        if row["side"] == "BUY":
            open_lots[key] = row
        elif row["side"] == "SELL" and key in open_lots:
            buy_row = open_lots.pop(key)
            entry = float(buy_row["price"])
            exit_price = float(row["price"])
            quantity = float(row["quantity"])
            pnl = (exit_price - entry) * quantity
            item["entryPrice"] = entry
            item["pnl"] = rnd(pnl)
            item["pnlPct"] = rnd(((exit_price - entry) / entry) * 100 if entry else 0)
        annotated.append(item)
    return list(reversed(annotated))


def to_okx_inst_id(symbol):
    if "-" in symbol:
        return symbol
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}-USDT"
    if symbol.endswith("USDC"):
        return f"{symbol[:-4]}-USDC"
    return symbol


def new_account():
    return {
        "cash": CONFIG["startingCash"], "assetQty": 0.0, "avgEntry": 0.0,
        "peakEquity": CONFIG["startingCash"], "maxDrawdownPct": 0.0,
        "realizedPnl": 0.0, "trades": 0, "closedTrades": 0, "wins": 0,
        "lastSignal": "HOLD", "lastReason": "not_started", "lastAction": "none",
        "entryDay": None, "entryCountToday": 0, "lastExitTime": 0, "lastCandleCloseTime": 0,
    }


def refresh_daily_limit(account, timestamp_ms):
    day = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()
    if account.get("entryDay") != day:
        account["entryDay"] = day
        account["entryCountToday"] = 0


def can_enter(account, timestamp_ms):
    refresh_daily_limit(account, timestamp_ms)
    cooldown_ms = CONFIG["cooldownMinutes"] * 60 * 1000
    return account["entryCountToday"] < CONFIG["maxEntriesPerDay"] and (not account["lastExitTime"] or timestamp_ms - account["lastExitTime"] >= cooldown_ms)


def snapshot_row(strategy, account, price):
    equity = account["cash"] + account["assetQty"] * price
    position_value = account["assetQty"] * price
    entry_cost = account["assetQty"] * account["avgEntry"]
    unreal = position_value - entry_cost if account["assetQty"] > 0 else 0.0
    return {
        "id": strategy["id"], "name": strategy["name"], "description": strategy["description"],
        "cash": rnd(account["cash"]), "assetQty": rnd(account["assetQty"], 8),
        "avgEntry": rnd(account["avgEntry"]), "positionValue": rnd(position_value),
        "unrealizedPnl": rnd(unreal), "unrealizedPnlPct": rnd((unreal / entry_cost) * 100 if entry_cost else 0),
        "equity": rnd(equity), "returnPct": rnd(((equity - CONFIG["startingCash"]) / CONFIG["startingCash"]) * 100),
        "realizedPnl": rnd(account["realizedPnl"]), "maxDrawdownPct": rnd(account["maxDrawdownPct"]),
        "trades": account["trades"], "wins": account["wins"], "entriesToday": account["entryCountToday"],
        "winRate": rnd((account["wins"] / account["closedTrades"]) * 100 if account["closedTrades"] else 0),
        "inPosition": account["assetQty"] > 0, "lastSignal": account["lastSignal"],
        "lastReason": account["lastReason"], "lastAction": account["lastAction"],
    }


def empty_snapshot(symbol, running, error, last_run_at):
    return {"config": {**CONFIG, "symbol": symbol}, "running": running, "lastError": error, "lastRunAt": last_run_at, "updatedAt": None, "lastPrice": 0, "strategies": [snapshot_row(s, new_account(), 0) for s in STRATEGIES], "candles": []}


def backtest_symbol(symbol, candles, higher):
    return []


def with_risk_exit(decision, account, price):
    if account["assetQty"] <= 0:
        return decision
    if price <= account["avgEntry"] * (1 - CONFIG["stopLossPct"] / 100):
        return {"signal": "SELL", "reason": "stop_loss"}
    if price >= account["avgEntry"] * (1 + CONFIG["takeProfitPct"] / 100):
        return {"signal": "SELL", "reason": "take_profit"}
    return decision


def decide(strategy_id, candles, higher, account):
    return hold("standard_strategy_retired")


def buy(reason): return {"signal": "BUY", "reason": reason}
def sell(reason): return {"signal": "SELL", "reason": reason}
def hold(reason): return {"signal": "HOLD", "reason": reason}
def rnd(value, digits=4): return round(value, digits) if math.isfinite(value) else 0


def sma(values, period):
    return None if len(values) < period else sum(values[-period:]) / period


def stddev(values, period):
    avg = sma(values, period)
    if avg is None: return None
    return math.sqrt(sum((v - avg) ** 2 for v in values[-period:]) / period)


def rsi(values, period):
    if len(values) <= period: return None
    gains = losses = 0.0
    recent = values[-period - 1:]
    for prev, cur in zip(recent[:-1], recent[1:]):
        diff = cur - prev
        gains += max(diff, 0)
        losses += abs(min(diff, 0))
    if losses == 0: return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - 100 / (1 + rs)


def ema_series(values, period):
    if len(values) < period: return []
    mult = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out = [prev]
    for value in values[period:]:
        prev = (value - prev) * mult + prev
        out.append(prev)
    return out


def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal: return None
    fast_s, slow_s = ema_series(values, fast), ema_series(values, slow)
    offset = len(fast_s) - len(slow_s)
    line = [fast_s[i + offset] - slow_s[i] for i in range(len(slow_s))]
    sig = ema_series(line, signal)
    if len(sig) < 2: return None
    return {"histogram": line[-1] - sig[-1], "previousHistogram": line[-2] - sig[-2]}


def atr(candles, period):
    if len(candles) <= period: return None
    ranges = []
    for prev, cur in zip(candles[-period - 1:-1], candles[-period:]):
        ranges.append(max(cur["high"] - cur["low"], abs(cur["high"] - prev["close"]), abs(cur["low"] - prev["close"])))
    return sum(ranges) / period


def vwap(candles, period):
    if len(candles) < period: return None
    recent = candles[-period:]
    vol = sum(c["volume"] for c in recent)
    if vol == 0: return None
    return sum(((c["high"] + c["low"] + c["close"]) / 3) * c["volume"] for c in recent) / vol


OKX_LIVE_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OKX Live Performance</title>
<style>body{margin:0;background:#f6f7f4;color:#19211f;font-family:Inter,Segoe UI,Arial,sans-serif}.top{display:flex;justify-content:space-between;gap:16px;padding:22px 28px;background:#fffefa;border-bottom:1px solid #dce3df;position:sticky;top:0;z-index:2}.controls{display:flex;gap:8px;flex-wrap:wrap}a.btn,button{border:1px solid #dce3df;border-radius:8px;background:#fff;padding:0 12px;height:40px;font-weight:800;cursor:pointer;color:#19211f;text-decoration:none;display:inline-flex;align-items:center}main{max-width:1280px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.metric,.panel{background:#fff;border:1px solid #dce3df;border-radius:8px;box-shadow:0 12px 32px rgba(31,45,42,.08)}.metric{padding:16px}.metric span,.label{display:block;color:#65706e;font-size:12px;text-transform:uppercase}.metric strong{display:block;margin-top:10px;font-size:24px}.panel{padding:18px;margin:16px 0 22px;overflow-x:auto}.good{color:#16835f}.bad{color:#c53b3b}.muted{color:#65706e}.pill{display:inline-flex;border:1px solid #dce3df;border-radius:999px;padding:4px 9px;background:#fbfcfb;font-size:12px;font-weight:800}table{width:100%;min-width:980px;border-collapse:collapse;font-size:13px}th{text-align:left;color:#65706e;background:#f8faf8;padding:9px;border-bottom:1px solid #dce3df}td{padding:9px;border-bottom:1px solid #eef2ef;vertical-align:top}tr:hover td{background:#fbfcfb}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.grid{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}</style></head>
<body><header class="top"><div><h1>OKX 真實交易績效</h1><p id="status">Loading...</p></div><div class="controls"><button id="refresh">Refresh</button><a class="btn" href="/micro">Micro</a><a class="btn" href="/crypto">Strategy Lab</a></div></header><main><section class="grid"><div class="metric"><span>帳戶 Equity</span><strong id="equity">--</strong></div><div class="metric"><span>可用 USDT</span><strong id="available">--</strong></div><div class="metric"><span>Realized P/L</span><strong id="pnl">--</strong></div><div class="metric"><span>勝率</span><strong id="winRate">--</strong></div></section><section class="grid"><div class="metric"><span>Closed Trades</span><strong id="closed">--</strong></div><div class="metric"><span>Open Positions</span><strong id="open">--</strong></div><div class="metric"><span>Protected BUYs</span><strong id="protected">--</strong></div><div class="metric"><span>交易模式</span><strong id="mode">--</strong></div></section><section class="panel"><h2>使用策略績效</h2><p>百分比以每筆實際 pilot margin 當分母計算 ROE；USD 為 OKX 成交後記錄的 realized P/L。</p><div id="strategies"></div></section><section class="panel"><h2>目前未平倉</h2><div id="positions"></div></section><section class="panel"><h2>OKX 歷史倉位</h2><p id="historyStatus">直接查 OKX private positions-history；可補到手動或 runner log 沒記完整的歷史倉位。</p><div id="positionHistory"></div></section><section class="panel"><h2>過去真實交易損益</h2><div id="trades"></div></section><section class="panel"><h2>最近事件</h2><div id="events"></div></section></main>
<script>
const $=s=>document.querySelector(s);$("#refresh").onclick=()=>load();setInterval(load,15000);load();
async function load(){try{const d=await (await fetch('/api/crypto/okx-live/performance')).json();render(d);}catch(e){$("#status").textContent='Load failed: '+e;}}
function render(d){const s=d.summary||{},a=d.account||{};$("#status").textContent=`Updated ${d.updatedAt?new Date(d.updatedAt).toLocaleString():'--'} · logs ${d.logGlob||''}${a.ok?'':' · account error: '+(a.error||'')}`;$("#equity").textContent=a.equity==null?'--':money(a.equity)+' '+(a.currency||'USDT');$("#available").textContent=a.available==null?'--':money(a.available)+' USDT';$("#pnl").textContent=`${money(s.pnlUsd)} / ${pct(s.pnlPct)}`;$("#pnl").className=tone(s.pnlUsd);$("#winRate").textContent=pct(s.winRate);$("#closed").textContent=s.closedTrades||0;$("#open").textContent=s.openPositions||0;$("#protected").textContent=`${s.hardStopProtectedBuys||0} / ${s.buyEvents||0}`;$("#mode").textContent=a.simulated?'Simulated':'Real OKX';renderStrategies(d.byStrategy||[]);renderPositions(d.openPositions||[]);renderPositionHistory(d.positionsHistory||{});renderTrades(d.closedTrades||[]);renderEvents(d.events||[]);}
function renderStrategies(rows){if(!rows.length){$("#strategies").innerHTML='<p>No closed strategy performance yet.</p>';return}$("#strategies").innerHTML=`<table><thead><tr><th>Strategy</th><th>Closed</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>P/L USD</th><th>P/L %</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(r.strategy)}</strong></td><td>${r.closedTrades}</td><td class="good">${r.wins}</td><td class="bad">${r.losses}</td><td>${pct(r.winRate)}</td><td class="${tone(r.pnlUsd)}">${money(r.pnlUsd)}</td><td class="${tone(r.pnlPct)}">${pct(r.pnlPct)}</td></tr>`).join('')}</tbody></table>`}
function renderPositions(rows){if(!rows.length){$("#positions").innerHTML='<p>No open live OKX positions.</p>';return}$("#positions").innerHTML=`<table><thead><tr><th>Strategy</th><th>Coin</th><th>Entry Time</th><th>Entry</th><th>Margin</th><th>Notional</th><th>Size</th><th>OKX Hard Stop</th><th>Reason</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.strategy)}</td><td><strong>${r.instId}</strong></td><td>${dt(r.entryTime)}</td><td>${money(r.entryPrice)}</td><td>${money(r.margin)}</td><td>${money(r.notional)}</td><td>${qty(r.sz)}</td><td>${r.hardStopAlgoId?'<span class="pill good">ON</span> '+money(r.hardStopPrice):'<span class="pill bad">missing</span>'}</td><td>${esc(r.entryReason||'')}</td></tr>`).join('')}</tbody></table>`}
function renderPositionHistory(payload){const rows=payload.rows||[];$("#historyStatus").textContent=payload.ok?`OKX positions-history · ${rows.length} / raw ${payload.rawCount||0} · limit ${payload.limit||''}${payload.simulated?' · Simulated':' · Real OKX'}`:`OKX positions-history failed: ${payload.error||'unknown error'}`;if(!rows.length){$("#positionHistory").innerHTML='<p>No OKX historical positions returned yet.</p>';return}$("#positionHistory").innerHTML=`<table><thead><tr><th>Close Time</th><th>Coin</th><th>Side</th><th>Open</th><th>Close</th><th>Margin</th><th>Notional</th><th>P/L USD</th><th>P/L %</th><th>Fees</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${dt(r.closeTime)}<br><span class="label">open ${dt(r.openTime)}</span></td><td><strong>${r.instId}</strong><br><span class="label">${esc(r.mgnMode||'')} ${esc(r.posSide||'')}</span></td><td>${esc(r.direction||'')}</td><td>${money(r.openAvgPx)}</td><td>${money(r.closeAvgPx)}</td><td>${money(r.margin)}</td><td>${money(r.notional)}</td><td class="${tone(r.pnlUsd)}">${money(r.pnlUsd)}</td><td class="${tone(r.pnlPct)}">${pct(r.pnlPct)}</td><td>${money(r.fee)}<br><span class="label">funding ${money(r.fundingFee)}</span></td></tr>`).join('')}</tbody></table>`}
function renderTrades(rows){if(!rows.length){$("#trades").innerHTML='<p>No closed live trades yet.</p>';return}$("#trades").innerHTML=`<table><thead><tr><th>Exit Time</th><th>Coin</th><th>Strategy</th><th>Entry</th><th>Exit</th><th>Margin</th><th>P/L USD</th><th>P/L %</th><th>Exit Reason</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${dt(r.exitTime)}</td><td><strong>${r.instId}</strong><br><span class="label">entry ${dt(r.entryTime)}</span></td><td>${esc(r.strategy)}</td><td>${money(r.entryPrice)}</td><td>${money(r.exitPrice)}</td><td>${money(r.margin)}</td><td class="${tone(r.pnlUsd)}">${money(r.pnlUsd)}</td><td class="${tone(r.pnlPct)}">${pct(r.pnlPct)}</td><td>${esc(r.exitReason||'')}</td></tr>`).join('')}</tbody></table>`}
function renderEvents(rows){if(!rows.length){$("#events").innerHTML='<p>No live events yet.</p>';return}$("#events").innerHTML=`<table><thead><tr><th>Time</th><th>Event</th><th>Coin</th><th>Strategy</th><th>Price</th><th>P/L</th><th>Reason / Protection</th></tr></thead><tbody>${rows.slice(0,80).map(r=>`<tr><td>${dt(r.time)}</td><td class="${r.event==='BUY'?'good':'bad'}">${r.event}</td><td>${r.instId}</td><td>${esc(r.strategy)}</td><td>${money(r.price)}</td><td class="${tone(r.pnlUsd||0)}">${r.pnlUsd==null?'--':money(r.pnlUsd)+' / '+pct(r.pnlPct)}</td><td>${esc(r.reason||'')}${r.hardStopAlgoId?'<br><span class="pill">hard stop '+r.hardStopAlgoId+'</span>':''}</td></tr>`).join('')}</tbody></table>`}
function money(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:6})}function qty(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:8})}function pct(v){v=Number(v||0);return `${v>=0?'+':''}${v.toFixed(2)}%`}function tone(v){return Number(v)>=0?'good':'bad'}function dt(v){return v?new Date(v).toLocaleString():'--'}function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
</script></body></html>"""

CRYPTO_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Crypto Strategy Lab</title>
<style>body{margin:0;background:#f5f7f4;color:#18201f;font-family:Inter,Segoe UI,Arial,sans-serif}.top{display:flex;justify-content:space-between;gap:16px;padding:22px 28px;background:#fffefa;border-bottom:1px solid #dce3df;position:sticky;top:0}.controls{display:flex;gap:8px}button{border:1px solid #dce3df;border-radius:8px;background:#fff;padding:0 12px;height:40px;font-weight:700;cursor:pointer}main{max-width:1280px;margin:auto;padding:24px}.tabs{display:flex;gap:10px;margin-bottom:16px}.tabs button{min-width:120px}.active{border-color:#2867b2;box-shadow:inset 0 0 0 1px #2867b2}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.metric,.panel,.card{background:#fff;border:1px solid #dce3df;border-radius:8px;box-shadow:0 12px 32px rgba(31,45,42,.08)}.metric{padding:16px}.metric span,.label{display:block;color:#65706e;font-size:12px;text-transform:uppercase}.metric strong{display:block;margin-top:10px;font-size:24px}.panel{padding:18px;margin:16px 0 22px;overflow-x:auto}canvas{width:100%;height:280px;border:1px solid #dce3df;border-radius:8px;background:#fbfcfb}.cards{display:grid;grid-template-columns:repeat(5,minmax(180px,1fr));gap:12px}.card{padding:14px;cursor:pointer}.card.pos{border-color:rgba(22,131,95,.55);background:#fbfffc}.card.selected,.pick.selected td{border-color:#2867b2;background:#f3f8ff}.pick{cursor:pointer}.position{border:1px solid #dce3df;border-radius:8px;padding:10px;margin:10px 0;background:#f8faf8}.position.on{background:#effaf4}.stat{display:flex;justify-content:space-between;gap:10px;border-top:1px solid #dce3df;padding-top:8px;margin-top:8px;font-size:13px}.detailgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}.good{color:#16835f}.bad{color:#c53b3b}table{width:100%;min-width:860px;border-collapse:collapse;font-size:13px}th{text-align:left;color:#65706e;background:#f8faf8;padding:9px;border-bottom:1px solid #dce3df}td{padding:9px;border-bottom:1px solid #eef2ef;vertical-align:top}tr:hover td{background:#fbfcfb}@media(max-width:900px){.grid,.cards,.detailgrid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.grid,.cards,.detailgrid{grid-template-columns:1fr}.top{align-items:flex-start}}</style></head>
<body><header class="top"><div><h1>Crypto Strategy Lab</h1><p id="sub">Loading...</p></div><div class="controls"><button id="run">Run</button><button id="toggle">Start</button><button id="microScan">Micro Scan</button><button id="backfill">Backfill 90d</button><button id="backtest">Backtest</button></div></header><main><nav id="tabs" class="tabs"></nav><section class="grid"><div class="metric"><span>Last Price</span><strong id="price">--</strong></div><div class="metric"><span>Leader</span><strong id="leader">--</strong></div><div class="metric"><span>Best Return</span><strong id="ret">--</strong></div><div class="metric"><span>Mode</span><strong>Paper</strong></div></section><section class="panel"><h2>5m Candles</h2><p id="last">Waiting</p><canvas id="chart"></canvas></section><section><h2>Strategy Ranking</h2><div id="cards" class="cards"></div></section><section class="panel"><h2>Small Cap Breakout Radar</h2><p id="microStatus">Waiting for scan.</p><div id="microPositions"></div><div id="microCandidates"></div><div id="microTrades"></div></section><section class="panel"><h2>Selected Strategy</h2><div id="detail"><p>Click a strategy card or table row to inspect it.</p></div></section><section class="panel"><h2>Backtest Performance</h2><p id="backfillStatus">Historical data status: idle.</p><div id="backtestRows"></div></section><section class="panel"><h2>Strategy Performance</h2><p>All 15 paper-trading combinations are ranked by current return, including realized and unrealized P/L.</p><div id="performance"></div></section><section class="panel"><h2>Trade History</h2><p>Past entries/exits are stored in lighto-tracker-db. Open positions and unrealized P/L are shown above.</p><div id="trades"></div></section></main>
<script>
let state={data:null,symbol:"",selected:null}; const $=s=>document.querySelector(s);
$("#run").onclick=()=>post("/api/crypto/run-once"); $("#toggle").onclick=()=>post(state.data?.running?"/api/crypto/stop":"/api/crypto/start");
$("#microScan").onclick=()=>runMicroScan();
$("#backfill").onclick=async()=>{let s=await (await fetch("/api/crypto/backfill?days=90",{method:"POST"})).json();renderBackfill(s);}
$("#backtest").onclick=()=>loadBacktest();
setInterval(load,10000); load();
async function load(){state.data=await (await fetch("/api/crypto/status")).json(); render(); if(state.data.backfill)renderBackfill(state.data.backfill); loadMicro();}
async function post(url){state.data=await (await fetch(url,{method:"POST"})).json(); render();}
function markets(){return state.data?.markets||[]} function market(){let ms=markets(); if(!state.symbol&&ms[0])state.symbol=ms[0].config.symbol; return ms.find(m=>m.config.symbol===state.symbol)||ms[0];}
async function loadTrades(){let m=market(); if(!m)return; let rows=await (await fetch(`/api/crypto/trades?symbol=${m.config.symbol}`)).json(); renderTrades(rows);}
async function loadPerformance(){let rows=await (await fetch("/api/crypto/performance")).json(); renderPerformance(rows);}
function renderTrades(rows){if(!rows.length){$("#trades").innerHTML='<p>No trades yet for this market.</p>';return} $("#trades").innerHTML=`<table><thead><tr><th>Time</th><th>Side</th><th>Strategy</th><th>Price</th><th>Qty</th><th>Amount</th><th>P/L</th><th>Reason</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${new Date(r.ts).toLocaleString()}</td><td class="${r.side==='BUY'?'good':'bad'}">${r.side}</td><td>${r.strategy}</td><td>${money(r.price)}</td><td>${qty(r.quantity)}</td><td>${money(r.quote_amount)}</td><td class="${tone(r.pnl||0)}">${r.pnl==null?'--':money(r.pnl)+' / '+pct(r.pnlPct)}</td><td>${r.reason}</td></tr>`).join('')}</tbody></table>`}
function render(){let m=market(); if(!m)return; let leader=m.strategies[0]; $("#sub").textContent=`${m.config.symbol} · ${m.config.dataSource||'OKX'} · 5m trigger / 15m structure`; $("#price").textContent=money(m.lastPrice); $("#leader").textContent=leader?.name||"--"; $("#ret").textContent=pct(leader?.returnPct||0); $("#ret").className=tone(leader?.returnPct||0); $("#toggle").textContent=state.data.running?"Stop":"Start"; $("#last").textContent=m.updatedAt?`Last update: ${new Date(m.updatedAt).toLocaleString()}`:"Waiting for first update"; tabs(); cards(m.strategies,m.lastPrice); chart(m.candles||[]); loadTrades(); loadPerformance(); if(state.selected)loadDetail();}
function tabs(){ $("#tabs").innerHTML=markets().map(m=>`<button class="${m.config.symbol===state.symbol?'active':''}" data-s="${m.config.symbol}">${m.config.symbol.replace('USDT','')}</button>`).join(""); document.querySelectorAll("#tabs button").forEach(b=>b.onclick=()=>{state.symbol=b.dataset.s;state.selected=null;$("#detail").innerHTML='<p>Click a strategy card or table row to inspect it.</p>';render();});}
function cards(strats, price){let m=market(); $("#cards").innerHTML=strats.map((s,i)=>{let pv=s.positionValue??s.assetQty*price; let cost=s.assetQty*s.avgEntry; let pnl=cost?((pv-cost)/cost*100):0; let sel=state.selected&&state.selected.symbol===m.config.symbol&&state.selected.strategy===s.id; return `<article class="card ${s.inPosition?'pos':''} ${sel?'selected':''}" data-symbol="${m.config.symbol}" data-strategy="${s.id}"><h3>${s.name}</h3><span class="label">${s.id}</span><p>${s.description}</p><div class="position ${s.inPosition?'on':''}"><span class="label">Position</span><strong>${s.inPosition?'Long '+money(pv):'Flat'}</strong>${s.inPosition?`<div>Qty ${qty(s.assetQty)}</div><div>Entry ${money(s.avgEntry)}</div><div class="${tone(pnl)}">P/L ${pct(pnl)}</div>`:''}</div>${stat('Equity',money(s.equity))}${stat('Return',`<span class="${tone(s.returnPct)}">${pct(s.returnPct)}</span>`)}${stat('Trades',s.trades)}${stat('Signal',s.lastSignal)}${stat('Reason',s.lastReason)}</article>`}).join(""); document.querySelectorAll(".card[data-strategy]").forEach(el=>el.onclick=()=>selectStrategy(el.dataset.symbol,el.dataset.strategy));}
function renderPerformance(rows){if(!rows.length){$("#performance").innerHTML='<p>No strategy state yet.</p>';return} $("#performance").innerHTML=`<table><thead><tr><th>Rank</th><th>Market</th><th>Strategy</th><th>Equity</th><th>Return</th><th>Realized</th><th>Unrealized</th><th>Trades</th><th>Win Rate</th><th>Max DD</th><th>Position</th></tr></thead><tbody>${rows.map((r,i)=>{let sel=state.selected&&state.selected.symbol===r.symbol&&state.selected.strategy===r.id; return `<tr class="pick ${sel?'selected':''}" data-symbol="${r.symbol}" data-strategy="${r.id}"><td>${i+1}</td><td>${r.symbol.replace('USDT','')}</td><td>${r.name}<br><span class="label">${r.id}</span></td><td>${money(r.equity)}</td><td class="${tone(r.returnPct)}">${pct(r.returnPct)}</td><td class="${tone(r.realizedPnl)}">${money(r.realizedPnl)}</td><td class="${tone(r.unrealizedPnl)}">${money(r.unrealizedPnl)} / ${pct(r.unrealizedPnlPct)}</td><td>${r.trades} / ${r.closedTrades}</td><td>${pct(r.winRate)}</td><td class="bad">${pct(-Math.abs(r.maxDrawdownPct||0))}</td><td>${r.inPosition?'Long '+money(r.positionValue):'Flat'}</td></tr>`}).join('')}</tbody></table>`; document.querySelectorAll(".pick[data-strategy]").forEach(el=>el.onclick=()=>selectStrategy(el.dataset.symbol,el.dataset.strategy));}
async function selectStrategy(symbol,strategy){state.selected={symbol,strategy};state.symbol=symbol;render();await loadDetail();}
async function loadDetail(){let s=state.selected;if(!s)return;let data=await (await fetch(`/api/crypto/strategy?symbol=${s.symbol}&strategy=${s.strategy}`)).json();renderDetail(data);}
function renderDetail(data){let p=data.performance;if(!p){$("#detail").innerHTML='<p>No detail found.</p>';return} $("#detail").innerHTML=`<h3>${p.symbol.replace('USDT','')} · ${p.name}</h3><div class="detailgrid"><div class="metric"><span>Equity</span><strong>${money(p.equity)}</strong></div><div class="metric"><span>Return</span><strong class="${tone(p.returnPct)}">${pct(p.returnPct)}</strong></div><div class="metric"><span>Realized</span><strong class="${tone(p.realizedPnl)}">${money(p.realizedPnl)}</strong></div><div class="metric"><span>Unrealized</span><strong class="${tone(p.unrealizedPnl)}">${money(p.unrealizedPnl)}</strong></div></div><div class="detailgrid"><div>${stat('Position',p.inPosition?'Long '+money(p.positionValue):'Flat')}${stat('Qty',qty(p.assetQty))}${stat('Entry',money(p.avgEntry))}</div><div>${stat('Trades',p.trades+' / '+p.closedTrades)}${stat('Win Rate',pct(p.winRate))}${stat('Max DD',pct(-Math.abs(p.maxDrawdownPct||0)))}</div><div>${stat('Signal',p.lastSignal)}${stat('Action',p.lastAction)}${stat('Reason',p.lastReason)}</div><div>${stat('Updated',p.updatedAt?new Date(p.updatedAt).toLocaleString():'--')}${stat('Price Time',p.priceTime?new Date(p.priceTime).toLocaleString():'--')}</div></div><h3>Strategy Trades</h3>${miniTrades(data.trades)}<h3>Recent Signals</h3>${miniSignals(data.signals)}`;}
function miniTrades(rows){if(!rows.length)return '<p>No trades for this strategy yet.</p>';return `<table><thead><tr><th>Time</th><th>Side</th><th>Price</th><th>Qty</th><th>Amount</th><th>P/L</th><th>Reason</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${new Date(r.ts).toLocaleString()}</td><td class="${r.side==='BUY'?'good':'bad'}">${r.side}</td><td>${money(r.price)}</td><td>${qty(r.quantity)}</td><td>${money(r.quote_amount)}</td><td class="${tone(r.pnl||0)}">${r.pnl==null?'--':money(r.pnl)+' / '+pct(r.pnlPct)}</td><td>${r.reason}</td></tr>`).join('')}</tbody></table>`}
function miniSignals(rows){if(!rows.length)return '<p>No signals yet.</p>';return `<table><thead><tr><th>Time</th><th>Signal</th><th>Action</th><th>Price</th><th>Equity</th><th>Return</th><th>Reason</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${new Date(r.ts).toLocaleString()}</td><td>${r.signal}</td><td>${r.action}</td><td>${money(r.price)}</td><td>${money(r.equity)}</td><td class="${tone(r.return_pct)}">${pct(r.return_pct)}</td><td>${r.reason}</td></tr>`).join('')}</tbody></table>`}
async function loadBackfill(){let s=await (await fetch("/api/crypto/backfill")).json();renderBackfill(s);}
function renderBackfill(s){let parts=Object.entries(s.symbols||{}).map(([sym,vals])=>`${sym}: 5m ${vals["5m"]||0}, 15m ${vals["15m"]||0}`).join(" | ");$("#backfillStatus").textContent=`Historical data status: ${s.message||"idle"}${s.running?" (running)":""}${parts?" · "+parts:""}`;}
async function loadBacktest(){await loadBackfill();$("#backtestRows").innerHTML="<p>Running backtest...</p>";let data=await (await fetch("/api/crypto/backtest?days=90")).json();renderBacktest(data.rows||[]);}
function renderBacktest(rows){if(!rows.length){$("#backtestRows").innerHTML="<p>No backtest rows yet. Run Backfill 90d first.</p>";return}$("#backtestRows").innerHTML=`<table><thead><tr><th>Rank</th><th>Market</th><th>Strategy</th><th>Return</th><th>Equity</th><th>Realized</th><th>Unrealized</th><th>Trades</th><th>Win Rate</th><th>Max DD</th><th>Candles</th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td>${i+1}</td><td>${r.symbol.replace("USDT","")}</td><td>${r.name}<br><span class="label">${r.id}</span></td><td class="${tone(r.returnPct)}">${pct(r.returnPct)}</td><td>${money(r.equity)}</td><td class="${tone(r.realizedPnl)}">${money(r.realizedPnl)}</td><td class="${tone(r.unrealizedPnl)}">${money(r.unrealizedPnl)}</td><td>${r.trades} / ${r.closedTrades}</td><td>${pct(r.winRate)}</td><td class="bad">${pct(-Math.abs(r.maxDrawdownPct||0))}</td><td>${r.candles||0} / ${r.higherCandles||0}</td></tr>`).join("")}</tbody></table>`}
async function runMicroScan(){const data=await (await fetch("/api/crypto/micro/run-once",{method:"POST"})).json();renderMicro(data);await loadMicroTrades();}
async function loadMicro(){const data=await (await fetch("/api/crypto/micro")).json();renderMicro(data);await loadMicroTrades();}
function renderMicro(data){$("#microStatus").textContent=`Last scan: ${data.lastRunAt?new Date(data.lastRunAt).toLocaleString():"waiting"} - ${data.running?"running":"stopped"}${data.lastError?" - "+data.lastError:""}`;renderMicroPositions(data.positions||[]);renderMicroCandidates(data.ranking1h||data.candidates||[]);}
function renderMicroPositions(rows){if(!rows.length){$("#microPositions").innerHTML="<h3>Open Micro Positions</h3><p>No open breakout positions.</p>";return}$("#microPositions").innerHTML=`<h3>Open Micro Positions</h3><table><thead><tr><th>Strategy</th><th>Coin</th><th>Entry</th><th>Price</th><th>MA60 Stop</th><th>Distance</th><th>Unrealized</th><th>Trades</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.strategy||'strategy1'}</td><td>${r.instId}</td><td>${money(r.avgEntry)}</td><td>${money(r.price)}</td><td>${money(r.ma60)}</td><td class="${tone(r.distanceToMa60Pct)}">${pct(r.distanceToMa60Pct)}</td><td class="${tone(r.unrealizedPnl)}">${money(r.unrealizedPnl)} / ${pct(r.unrealizedPnlPct)}</td><td>${r.trades} / ${r.closedTrades}</td></tr>`).join("")}</tbody></table>`}
function renderMicroCandidates(rows){if(!rows.length){$("#microCandidates").innerHTML="<h3>1h Ranking Watchlist</h3><p>No candidates yet.</p>";return}$("#microCandidates").innerHTML=`<h3>1h Ranking Watchlist</h3><table><thead><tr><th>Coin</th><th>Buy</th><th>Price</th><th>1h</th><th>15m</th><th>12h</th><th>Vol x</th><th>24h Vol</th><th>MA60</th></tr></thead><tbody>${rows.slice(0,30).map(r=>`<tr><td>${r.instId}</td><td class="${r.buy?'good':'bad'}">${r.buy?'YES':'watch'}</td><td>${money(r.price)}</td><td class="${tone(r.pct1h)}">${pct(r.pct1h)}</td><td class="${tone(r.pct15)}">${pct(r.pct15)}</td><td class="${tone(r.pct12h)}">${pct(r.pct12h)}</td><td>${Number(r.volumeRatio||0).toFixed(2)}</td><td>${money(r.quoteVolume24h)}</td><td>${money(r.ma60)}</td></tr>`).join("")}</tbody></table>`}
async function loadMicroTrades(){const rows=await (await fetch("/api/crypto/micro/trades")).json();renderMicroTrades(rows);}
function renderMicroTrades(rows){if(!rows.length){$("#microTrades").innerHTML="<h3>Micro Trades</h3><p>No micro trades yet.</p>";return}$("#microTrades").innerHTML=`<h3>Micro Trades</h3><table><thead><tr><th>Time</th><th>Strategy</th><th>Coin</th><th>Side</th><th>Price</th><th>MA60</th><th>Notional</th><th>P/L</th><th>Reason</th></tr></thead><tbody>${rows.slice(0,40).map(r=>`<tr><td>${new Date(r.ts).toLocaleString()}</td><td>${r.strategy||'strategy1'}</td><td>${r.inst_id}</td><td class="${r.side==='BUY'?'good':'bad'}">${r.side}</td><td>${money(r.price)}</td><td>${money(r.ma60)}</td><td>${money(r.quote_amount)}</td><td class="${tone(r.pnl||0)}">${r.pnl==null?'--':money(r.pnl)+' / '+pct(r.pnlRoePct??r.pnlPct)}</td><td>${r.reason}</td></tr>`).join("")}</tbody></table>`}
function stat(k,v){return `<div class="stat"><span>${k}</span><strong>${v}</strong></div>`} function money(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:2})} function qty(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:8})} function pct(v){v=Number(v||0);return `${v>=0?'+':''}${v.toFixed(2)}%`} function tone(v){return Number(v)>=0?'good':'bad'}
function chart(c){const canvas=$("#chart"),r=devicePixelRatio||1,rect=canvas.getBoundingClientRect();canvas.width=Math.max(640,rect.width*r);canvas.height=280*r;const x=canvas.getContext('2d');x.scale(r,r);x.clearRect(0,0,rect.width,280);if(!c.length){x.fillText('Waiting for candles',18,32);return}let hi=Math.max(...c.map(k=>k.high)),lo=Math.min(...c.map(k=>k.low)),span=Math.max(1,hi-lo),w=(rect.width-64)/c.length;function y(v){return 18+((hi-v)/span)*(238)};c.forEach((k,i)=>{let cx=16+i*w+w/2,up=k.close>=k.open;x.strokeStyle=x.fillStyle=up?'#16835f':'#c53b3b';x.beginPath();x.moveTo(cx,y(k.high));x.lineTo(cx,y(k.low));x.stroke();x.fillRect(cx-w*.25,Math.min(y(k.open),y(k.close)),Math.max(2,w*.5),Math.max(2,Math.abs(y(k.close)-y(k.open))))});}
</script></body></html>"""


MICRO_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Small Cap Radar</title>
<style>body{margin:0;background:#f6f7f4;color:#19211f;font-family:Inter,Segoe UI,Arial,sans-serif}.top{display:flex;justify-content:space-between;gap:16px;padding:22px 28px;background:#fffefa;border-bottom:1px solid #dce3df;position:sticky;top:0;z-index:2}.controls{display:flex;gap:8px;flex-wrap:wrap}button,a.btn{border:1px solid #dce3df;border-radius:8px;background:#fff;padding:0 12px;height:40px;font-weight:700;cursor:pointer;color:#19211f;text-decoration:none;display:inline-flex;align-items:center}main{max-width:1280px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.metric,.panel{background:#fff;border:1px solid #dce3df;border-radius:8px;box-shadow:0 12px 32px rgba(31,45,42,.08)}.metric{padding:16px}.metric span,.label{display:block;color:#65706e;font-size:12px;text-transform:uppercase}.metric strong{display:block;margin-top:10px;font-size:24px}.panel{padding:18px;margin:16px 0 22px;overflow-x:auto}.archiveChart{width:100%;height:320px;border:1px solid #dce3df;border-radius:8px;background:#fbfcfb;margin:12px 0 16px}.archiveRow{cursor:pointer}.archiveRow.selected td{background:#eef6ff}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.tab{border:1px solid #dce3df;border-radius:999px;background:#fff;padding:9px 14px;font-weight:800;cursor:pointer}.tab.active{background:#19211f;color:#fff}.pane{display:none}.pane.active{display:block}.good{color:#16835f}.bad{color:#c53b3b}.strategyPerf{border:1px solid #dce3df;border-radius:10px;margin:12px 0;background:#fff;overflow:hidden}.strategyPerf summary{list-style:none;cursor:pointer;padding:14px 16px;background:#fbfcfb;display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}.strategyPerf summary::-webkit-details-marker{display:none}.strategyPerf summary:before{content:'▸';font-weight:900;color:#65706e}.strategyPerf[open] summary:before{content:'▾'}.strategyPerfTitle{font-size:18px;font-weight:900;color:#19211f}.strategyPerfMeta{display:flex;gap:12px;flex-wrap:wrap;font-size:13px}.strategyPerfBody{padding:0 16px 16px}.strategyPerfBody table{margin-top:8px}table{width:100%;min-width:980px;border-collapse:collapse;font-size:13px}th{text-align:left;color:#65706e;background:#f8faf8;padding:9px;border-bottom:1px solid #dce3df}td{padding:9px;border-bottom:1px solid #eef2ef;vertical-align:top}tr:hover td{background:#fbfcfb}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.grid{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}</style></head>
<body><header class="top"><div><h1>Small Cap Perp Radar</h1><p id="status">Loading...</p></div><div class="controls"><button id="scan">Scan Now</button><a class="btn" href="/crypto">Strategy Lab</a></div></header><main><section class="grid"><div class="metric"><span>Market</span><strong id="marketType">--</strong></div><div class="metric"><span>1h Ranking</span><strong id="watchCount">--</strong></div><div class="metric"><span>Positions</span><strong id="posCount">--</strong></div><div class="metric"><span>Last Scan</span><strong id="lastScan">--</strong></div></section><nav class="tabs"><button class="tab active" data-tab="radar">Radar</button><button class="tab" data-tab="trades">進出場紀錄</button><button class="tab" data-tab="perf12h">12小時策略績效</button></nav><div id="tab-radar" class="pane active"><section class="panel"><h2>Active Strategies</h2><p>目前 API config 正在啟用的 micro 策略；即使還沒有進出場紀錄也會列在這裡。</p><div id="activeStrategies"></div></section><section class="panel"><h2>1h Gain Ranking</h2><p>Uses OKX USDT perpetuals, computes 1h gain from 5m candles, and checks MA60 trend state for short-wave setups.</p><div id="candidates"></div></section><section class="panel"><h2>Surge Archive</h2><p id="archiveStatus">Sorted by 1h gain. Waiting for hourly archive.</p><canvas id="archiveChart" class="archiveChart"></canvas><div id="archive"></div></section><section class="panel"><h2>Open Positions</h2><p>Paper positions use 10 USDT margin at 5x leverage, enter on 5m MA trend plus 1h breakout, then exit on 1% stop, two closes below MA60, or 2% trailing giveback.</p><div id="positions"></div></section></div><div id="tab-trades" class="pane"><section class="panel"><h2>進出場與績效紀錄</h2><p>只顯示：策略名稱、inst_id、進場時間、出場時間、績效。</p><div id="trades"></div></section></div><div id="tab-perf12h" class="pane"><section class="panel"><h2>不同策略最近 12 小時績效</h2><p id="perf12hStatus">Loading...</p><div id="perf12h"></div></section></div></main>
<script>
const $=s=>document.querySelector(s);
let archiveRows=[], selectedArchiveId=null;
$("#scan").onclick=()=>scan();
document.querySelectorAll(".tab").forEach(btn=>btn.onclick=()=>showTab(btn.dataset.tab));
function showTab(name){document.querySelectorAll(".tab").forEach(b=>b.classList.toggle("active",b.dataset.tab===name));document.querySelectorAll(".pane").forEach(p=>p.classList.toggle("active",p.id===`tab-${name}`));}
setInterval(load,10000); load();
async function load(){const data=await (await fetch("/api/crypto/micro")).json();render(data);await loadTradeRecords();await loadPerformance12h();await loadArchive();}
async function scan(){$("#status").textContent="Scanning...";const data=await (await fetch("/api/crypto/micro/run-once",{method:"POST"})).json();render(data);await loadTradeRecords();await loadPerformance12h();await loadArchive();}
function render(data){let ranking=data.ranking1h||data.candidates||[];$("#marketType").textContent=`${data.config?.microInstType||"SWAP"} ${data.config?.microInterval||"5m"}`;$("#watchCount").textContent=ranking.length;$("#posCount").textContent=(data.positions||[]).length;$("#lastScan").textContent=data.lastRunAt?new Date(data.lastRunAt).toLocaleTimeString():"--";$("#status").textContent=`${data.running?"Running":"Stopped"} - ${data.lastRunAt?new Date(data.lastRunAt).toLocaleString():"Waiting"}${data.lastError?" - "+data.lastError:""}`;renderActiveStrategies(data.config?.microActiveStrategies||[]);renderCandidates(ranking);renderPositions(data.positions||[]);}
function renderActiveStrategies(rows){if(!rows.length){$("#activeStrategies").innerHTML="<p>No active strategies configured.</p>";return}$("#activeStrategies").innerHTML=`<table><thead><tr><th>#</th><th>Strategy</th><th>Status</th></tr></thead><tbody>${rows.map((s,i)=>`<tr><td>${i+1}</td><td><strong>${s}</strong></td><td class="good">active</td></tr>`).join("")}</tbody></table>`}
function renderCandidates(rows){if(!rows.length){$("#candidates").innerHTML="<p>No ranking data yet.</p>";return}$("#candidates").innerHTML=`<table><thead><tr><th>Rank</th><th>Coin</th><th>Status</th><th>Price</th><th>1h</th><th>15m</th><th>12h</th><th>Vol x</th><th>Accel</th><th>Range</th><th>MA60</th><th>Score</th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td>${i+1}</td><td><strong>${r.instId}</strong></td><td class="${r.buy?'good':'bad'}">${r.buy?'BUY SIGNAL':(r.quietLift?'early':'watch')}</td><td>${money(r.price)}</td><td class="${tone(r.pct1h)}">${pct(r.pct1h)}</td><td class="${tone(r.pct15)}">${pct(r.pct15)}</td><td class="${tone(r.pct12h)}">${pct(r.pct12h)}</td><td>${Number(r.volumeRatio||0).toFixed(2)}</td><td>${Number(r.volumeAccel||0).toFixed(2)}</td><td>${pct(r.compactRangePct)}</td><td>${money(r.ma60)}<br><span class="label">${pct(r.ma60Slope)}</span></td><td>${Number(r.trendScore||0).toFixed(2)}</td></tr>`).join("")}</tbody></table>`}
function renderPositions(rows){if(!rows.length){$("#positions").innerHTML="<p>No open paper positions.</p>";return}$("#positions").innerHTML=`<table><thead><tr><th>Strategy</th><th>Coin</th><th>Entry</th><th>Price</th><th>MA60 Stop</th><th>To MA60</th><th>Peak</th><th>Margin</th><th>Notional</th><th>Unrealized</th><th>Trades</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.strategy||'strategy1'}</td><td><strong>${r.instId}</strong></td><td>${money(r.avgEntry)}</td><td>${money(r.price)}</td><td>${money(r.ma60)}<br><span class="label">${r.belowMa60Count||0}/2</span></td><td class="${tone(r.distanceToMa60Pct)}">${pct(r.distanceToMa60Pct)}</td><td>${money(r.peakPrice)}<br><span class="label">${pct(r.givebackPct)}</span></td><td>${money(r.margin)}<br><span class="label">${Number(r.leverage||0).toFixed(1)}x</span></td><td>${money(r.notional||r.positionValue)}</td><td class="${tone(r.unrealizedPnl)}">${money(r.unrealizedPnl)} / ${pct(r.unrealizedRoePct)}</td><td>${r.trades} / ${r.closedTrades}</td></tr>`).join("")}</tbody></table>`}
async function loadTradeRecords(){const rows=await (await fetch("/api/crypto/micro/trade-records")).json();renderTradeRecords(rows);}
function renderTradeRecords(rows){if(!rows.length){$("#trades").innerHTML="<p>No entries or exits yet.</p>";return}$("#trades").innerHTML=`<table><thead><tr><th>Strategy</th><th>inst_id</th><th>Entry Time</th><th>Exit Time</th><th>Performance</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.strategy||'strategy1'}</td><td><strong>${r.inst_id}</strong></td><td>${new Date(r.entry_time).toLocaleString()}</td><td>${r.exit_time?new Date(r.exit_time).toLocaleString():'open'}</td><td class="${tone(r.pnl_roe_pct??r.pnl_pct??0)}">${r.status==='open'?'open':money(r.pnl)+' / '+pct(r.pnl_roe_pct??r.pnl_pct)}</td></tr>`).join("")}</tbody></table>`}
async function loadPerformance12h(){const data=await (await fetch("/api/crypto/micro/performance12h")).json();renderPerformance12h(data);}
function renderPerformance12h(data){const current=data.current;const groups=ensureCurrentPerformanceGroups((data.byStrategy||groupPerformance12hByStrategy(data.history||[])).filter(g=>(g.windows||[]).length),current);$("#perf12hStatus").textContent=current?`報告時段：${current.snapshotSlotTaipei||''} 台北 · ${current.windowStartTaipei||new Date(current.windowStart).toLocaleString()} - ${current.windowEndTaipei||new Date(current.windowEnd).toLocaleString()} · 與 Google Sheet strategy_performance_12h 同一視窗`:'No 12h records yet';if(!groups.length){$("#perf12h").innerHTML="<p>No strategy performance records yet.</p>";return}$("#perf12h").innerHTML=groups.map((g,i)=>`<details class="strategyPerf" ${i===0?'open':''}><summary><span class="strategyPerfTitle">${g.strategy}</span><span class="strategyPerfMeta"><span>累積 <strong class="${tone(g.cumulativeReturnPct)}">${pct(g.cumulativeReturnPct)}</strong></span><span>年化 <strong class="${tone(g.annualizedReturnPct)}">${pct(g.annualizedReturnPct)}</strong></span><span>Closed ${g.closedTrades||0}</span><span>P/L <strong class="${tone(g.realizedPnl)}">${money(g.realizedPnl)}</strong></span><span>Days ${Number(g.elapsedDays||0).toFixed(2)}</span></span></summary><div class="strategyPerfBody"><table><thead><tr><th>Sheet 報告時段</th><th>Entries</th><th>Closed</th><th>Open</th><th>Win Rate</th><th>Realized P/L</th><th>Avg ROE</th></tr></thead><tbody>${(g.windows||[]).map(r=>`<tr><td>${r.isCurrent?'最新報告':'歷史報告'} ${r.snapshotSlotTaipei||''}<br><span class="label">${r.windowStartTaipei||new Date(r.windowStart).toLocaleString()} - ${r.windowEndTaipei||new Date(r.windowEnd).toLocaleString()}</span></td><td>${r.entries}</td><td>${r.closedTrades}</td><td>${r.openTrades}</td><td>${pct(r.winRate)}</td><td class="${tone(r.realizedPnl)}">${money(r.realizedPnl)}</td><td class="${tone(r.avgPnlRoePct)}">${pct(r.avgPnlRoePct)}</td></tr>`).join("")}</tbody></table></div></details>`).join("")}
function ensureCurrentPerformanceGroups(groups,current){const out=[...(groups||[])],seen=new Set(out.map(g=>g.strategy));if(current&&(current.rows||[]).length){(current.rows||[]).forEach(r=>{const s=r.strategy||'strategy1';if(!seen.has(s)){out.push(addStrategyReturns({strategy:s,windows:[{...r,windowStart:current.windowStart,windowEnd:current.windowEnd,windowStartTaipei:current.windowStartTaipei,windowEndTaipei:current.windowEndTaipei,snapshotSlotTaipei:current.snapshotSlotTaipei,isCurrent:true}]}));seen.add(s);}})}return out.sort((a,b)=>a.strategy.localeCompare(b.strategy));}
function perfWindowHasData(r){return Number(r.entries||0)>0||Number(r.closedTrades||0)>0||Number(r.openTrades||0)>0||Math.abs(Number(r.realizedPnl||0))>0}
function groupPerformance12hByStrategy(windows){const map={};(windows||[]).forEach(w=>(w.rows||[]).filter(perfWindowHasData).forEach(r=>{const s=r.strategy||'strategy1';if(!map[s])map[s]={strategy:s,windows:[]};map[s].windows.push({...r,windowStart:w.windowStart,windowEnd:w.windowEnd,windowStartTaipei:w.windowStartTaipei,windowEndTaipei:w.windowEndTaipei,snapshotSlotTaipei:w.snapshotSlotTaipei,isCurrent:w.isCurrent});}));return Object.values(map).sort((a,b)=>a.strategy.localeCompare(b.strategy)).map(addStrategyReturns);}
function addStrategyReturns(g){const margin=10,totalClosed=(g.windows||[]).reduce((s,r)=>s+Number(r.closedTrades||0),0),realized=(g.windows||[]).reduce((s,r)=>s+Number(r.realizedPnl||0),0),starts=(g.windows||[]).map(r=>new Date(r.windowStart).getTime()),ends=(g.windows||[]).map(r=>new Date(r.windowEnd).getTime()),days=Math.max((Math.max(...ends)-Math.min(...starts))/86400000,0.5),cum=totalClosed?realized/(totalClosed*margin)*100:0,ann=totalClosed&&cum>-100?(Math.pow(1+cum/100,365/days)-1)*100:(cum<=-100?-100:0);return {...g,closedTrades:totalClosed,realizedPnl:realized,cumulativeReturnPct:cum,annualizedReturnPct:ann,elapsedDays:days};}
async function loadArchive(){const rows=await (await fetch("/api/crypto/micro/surge-archive?limit=60")).json();renderArchive(rows);}
function renderArchive(rows){archiveRows=rows;if(!rows.length){$("#archive").innerHTML="<p>No archived surge snapshots yet.</p>";drawArchiveChart([],null);return}if(!selectedArchiveId||!rows.find(r=>r.id===selectedArchiveId))selectedArchiveId=rows[0].id;let picked=rows.find(r=>r.id===selectedArchiveId)||rows[0];$("#archiveStatus").textContent=`${picked.inst_id} - ${new Date(picked.scan_hour).toLocaleString()} - sorted by 1h gain - ${(picked.candles||[]).length} bars`;drawArchiveChart(picked.candles||[],picked);$("#archive").innerHTML=`<table><thead><tr><th>Hour</th><th>Rank</th><th>Coin</th><th>Price</th><th>1h</th><th>15m</th><th>12h</th><th>Vol x</th><th>MA60 Dist</th><th>K Bars</th></tr></thead><tbody>${rows.map(r=>`<tr class="archiveRow ${r.id===selectedArchiveId?'selected':''}" data-id="${r.id}"><td>${new Date(r.scan_hour).toLocaleString()}</td><td>${r.rank}</td><td>${r.inst_id}</td><td>${money(r.price)}</td><td class="${tone(r.pct1h)}">${pct(r.pct1h)}</td><td class="${tone(r.pct15)}">${pct(r.pct15)}</td><td class="${tone(r.pct12h)}">${pct(r.pct12h)}</td><td>${Number(r.volume_ratio||0).toFixed(2)}</td><td class="${tone(r.distance_ma60_pct)}">${pct(r.distance_ma60_pct)}</td><td>${(r.candles||[]).length}</td></tr>`).join("")}</tbody></table>`;document.querySelectorAll(".archiveRow").forEach(row=>row.onclick=()=>{selectedArchiveId=Number(row.dataset.id);renderArchive(archiveRows);});}
function drawArchiveChart(candles,row){const canvas=$("#archiveChart"),rect=canvas.getBoundingClientRect(),ratio=devicePixelRatio||1,w=Math.max(640,rect.width),h=320;canvas.width=w*ratio;canvas.height=h*ratio;const ctx=canvas.getContext("2d");ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);ctx.fillStyle="#fbfcfb";ctx.fillRect(0,0,w,h);ctx.strokeStyle="#dce3df";ctx.lineWidth=1;for(let i=0;i<5;i++){let y=28+i*(h-58)/4;ctx.beginPath();ctx.moveTo(48,y);ctx.lineTo(w-16,y);ctx.stroke();}if(!candles.length){ctx.fillStyle="#65706e";ctx.fillText("Click a surge archive row to inspect its 4h candles.",18,30);return}let hi=Math.max(...candles.map(k=>Number(k.high))),lo=Math.min(...candles.map(k=>Number(k.low))),span=Math.max(hi-lo,hi*0.0001),left=52,right=18,top=26,bottom=42,plotW=w-left-right,plotH=h-top-bottom,barW=plotW/candles.length;function y(v){return top+((hi-v)/span)*plotH}ctx.fillStyle="#19211f";ctx.font="12px Inter, Segoe UI, Arial";ctx.fillText(`${row.inst_id}  ${new Date(row.scan_hour).toLocaleString()}  12h ${pct(row.pct12h)}  1h ${pct(row.pct1h)}`,16,18);ctx.fillStyle="#65706e";ctx.fillText(money(hi),8,y(hi)+4);ctx.fillText(money(lo),8,y(lo)+4);candles.forEach((k,i)=>{let x=left+i*barW+barW/2,open=Number(k.open),close=Number(k.close),high=Number(k.high),low=Number(k.low),up=close>=open;ctx.strokeStyle=ctx.fillStyle=up?"#16835f":"#c53b3b";ctx.beginPath();ctx.moveTo(x,y(high));ctx.lineTo(x,y(low));ctx.stroke();ctx.fillRect(x-Math.max(2,barW*.28),Math.min(y(open),y(close)),Math.max(2,barW*.56),Math.max(2,Math.abs(y(close)-y(open))));});ctx.fillStyle="#65706e";ctx.fillText(new Date(candles[0].time).toLocaleTimeString(),left,h-16);ctx.fillText(new Date(candles[candles.length-1].time).toLocaleTimeString(),Math.max(left,w-100),h-16);}
function money(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:6})}
function pct(v){v=Number(v||0);return `${v>=0?'+':''}${v.toFixed(2)}%`}
function tone(v){return Number(v)>=0?'good':'bad'}
</script></body></html>"""
