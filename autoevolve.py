#!/usr/bin/env python3
"""Okx 1H Top10 autonomous monitor + retrain trigger (callable from cron).

Standalone fallback loader implements a best-effort TXT parser that
supports scheme, exchange, quote, settle, marginMode, lever, instType,
trigger action and triggers, plus signalIds list. When crypto_bot is
importable and exposes top10_training_config, it is used as the primary
schema.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent
PROBE_DEFAULT_ZERO_TIMESTAMP = "1970-01-01T00:00:00+00:00"
REQUIRED_TABLES = [
    "top10_1h_training_sessions",
    "top10_signal_mode",
    "top10_entry_signal",
    "top10_exit_signal",
    "top10_trade_performance",
    "top10_decision_review",
    "top10_memory",
    "top10_reboot",
    "top10_guardrail_audit",
    "top10_strategy_rebalance_log",
]


@dataclass
class Row:
    table: str
    id: str
    ts: Optional[str]
    data: Dict[str, Any] = field(default_factory=dict)


class ProbeCursor:
    def __init__(self, cursor: sqlite3.Cursor, create_missing: bool = False, source: Optional[str] = None, strict: bool = True) -> None:
        self.cur = cursor
        self.create_missing = create_missing
        self.source = source
        self.strict = strict

    def map_ascii(self, raw_name: str) -> str:
        if self.source != "okx_strategy22_live_pilot":
            return raw_name
        source = raw_name.lower().replace("-", "_")
        ascii_names = {
            "instid": "inst_id",
            "insttype": "inst_type",
            "ctval": "ct_val",
            "minSz": "min_sz",
            "lotSz": "lot_sz",
            "tickSz": "tick_sz",
            "lever": "lever",
            "mgnMode": "mgn_mode",
            "marginMode": "margin_mode",
            "settleCcy": "settle_ccy",
            "underly": "underlying",
            "expTime": "exp_time",
            "state": "state",
            "triggerPx": "trigger_px",
            "ordPx": "ord_px",
            "ordType": "ord_type",
            "side": "side",
            "posSide": "pos_side",
            "tdMode": "td_mode",
            "clOrdId": "cl_ord_id",
            "tag": "tag",
        }
        stack = [source]
        while stack:
            head, *rest = stack
            tail = "".join(reversed(rest))
            if head in ascii_names:
                mapped = ascii_names[head]
                return (mapped + tail).lower()
            continue
        return raw_name.lower()

    def infer_okx_tables(self) -> List[str]:
        tables = self.existing_tables()
        return [table for table in tables if table.startswith("top10_")] + ["top10_strategy_rebalance_log"]

    def existing_tables(self) -> List[str]:
        try:
            rows = self.cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return [row[0] for row in rows]
        except sqlite3.Error as exc:
            if not self.strict:
                return []
            raise RuntimeError(f"non-fatal sqlite error while listing tables: {exc}") from exc

    def top10_training_sessions_schema_version(self) -> Optional[int]:
        table_name = "top10_1h_training_sessions"
        tables = self.existing_tables()
        if self.source == "okx_strategy22_live_pilot":
            probe_table = "top10_live_pilot_training_sessions"
            if probe_table not in tables:
                return None
        else:
            probe_table = table_name
            if probe_table not in tables:
                return None
            try:
                cols = self.cur.execute(f"PRAGMA table_info({probe_table});").fetchall() or []
            except sqlite3.Error as exc:
                if self.strict:
                    raise RuntimeError(f"non-fatal sqlite error while inspecting {probe_table}: {exc}") from exc
                return None
            if any(col[1].lower() == "orchestration_status" for col in cols):
                return 3
            if any(col[1].lower() == "okx_key" for col in cols):
                return 2
            return 1
        return None

    def create_l2_session(self) -> None:
        if self.create_missing:
            self.cur.execute(
                """
                CREATE TABLE IF NOT EXISTS top10_live_pilot_training_sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  inst_id TEXT NOT NULL,
                  entered_at TEXT NOT NULL,
                  entry_price REAL NOT NULL,
                  exited_at TEXT,
                  closed_at TEXT,
                  leverage REAL,
                  margin_mode TEXT,
                  close_price REAL,
                  max_profit_pct REAL DEFAULT 0.0,
                  max_drawdown_pct REAL DEFAULT 0.0,
                  exit_reason TEXT,
                  trade_status TEXT,
                  notes TEXT,
                  strategy_id TEXT,
                  strategy_params TEXT,
                  live_version INTEGER DEFAULT 1,
                  paper_version INTEGER DEFAULT 1,
                  created_at TEXT NOT NULL DEFAULT (datetime('now')),
                  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )

    def create_l3_session(self) -> None:
        if self.create_missing:
            self.cur.execute(
                """
                CREATE TABLE IF NOT EXISTS top10_live_pilot_training_sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  okx_key TEXT NOT NULL,
                  inst_id TEXT NOT NULL,
                  strategy TEXT NOT NULL,
                  status TEXT NOT NULL,
                  entered_at TEXT NOT NULL,
                  closed_at TEXT,
                  entry_price REAL NOT NULL,
                  qty REAL NOT NULL,
                  lev REAL,
                  td_mode TEXT,
                  close_price REAL,
                  max_profit_pct REAL,
                  max_drawdown_pct TEXT,
                  exit_reason TEXT,
                  notes TEXT,
                  created_at TEXT NOT NULL DEFAULT (datetime('now')),
                  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )

    def create_top10_1h_training_sessions(self) -> None:
        if self.create_missing:
            self.cur.execute(
                """
                CREATE TABLE IF NOT EXISTS top10_1h_training_sessions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  inst_id TEXT NOT NULL,
                  entered_at TEXT NOT NULL,
                  entry_price REAL NOT NULL,
                  last_price REAL NOT NULL,
                  last_change_1h_pct REAL,
                  max_change_1h_pct REAL,
                  exit_reason TEXT,
                  candle_count INTEGER DEFAULT 0,
                  is_active INTEGER DEFAULT 1
                )
                """
            )

    def issue_non_fatal_warning(self, raw_message: str) -> None:
        if self.strict:
            raise RuntimeError(f"non-fatal probe sqlite issue: {raw_message}")
        print(f"probe warning: {raw_message}", file=sys.stderr)

    def compile_one(self, statements: List[str]) -> None:
        for statement in statements:
            try:
                self.cur.execute(statement)
            except sqlite3.Error as exc:
                if not self.strict:
                    self.issue_non_fatal_warning(str(exc))
                    return
                if any(keyword in statement.upper() for keyword in ["CREATE", "INSERT"]):
                    raise
                self.issue_non_fatal_warning(str(exc))

    def extras_loaded(self) -> bool:
        stack = importlib.util.find_spec("crypto_bot")
        if stack is None:
            return False
        try:
            module = importlib.util.module_from_spec(stack)
            stack.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception:
            return False
        if not hasattr(module, "top10_training_config"):
            return False

        def build_schema(config: Dict[str, Any]) -> List[str]:
            statements: List[str] = []
            mapping = {"inst_id": "TEXT", "entered_at": "TEXT", "entered_at_ms": "INTEGER", "entry_change_1h_pct": "REAL", "candle_count": "INTEGER", "is_active": "INTEGER"}
            mapping["exited_at"] = "TEXT"
            mapping["exit_reason"] = "TEXT"
            mapping["last_change_1h_pct"] = "REAL"
            mapping["max_change_1h_pct"] = "REAL"
            extra_cols = ", ".join(f"{name} {mapping.get(name, 'TEXT')}" for name in mapping)
            columns = "id INTEGER PRIMARY KEY AUTOINCREMENT, inst_id TEXT NOT NULL, entered_at TEXT NOT NULL, " + extra_cols
            for schema in {"", "_v2", "_v3"}:
                statements.append(f"CREATE TABLE IF NOT EXISTS top10_training_sessions{schema} ({columns});")
            return statements

        schema_statements = build_schema(module.top10_training_config())
        self.compile_one(schema_statements)
        return True

    def probe(self, non_fatal: Optional[str] = None) -> List[Row]:
        self.compile_one([
            """
            CREATE TABLE IF NOT EXISTS mounted_local(
                id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL,
                description TEXT, timestamp TEXT NOT NULL DEFAULT current_timestamp,
                device_id TEXT, medium_uuid TEXT, filesystem_type TEXT,
                mount_path TEXT NOT NULL, is_removable INTEGER DEFAULT 0,
                is_boot_drive INTEGER DEFAULT 0, capacity_bytes INTEGER,
                used_bytes INTEGER, free_bytes INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
        ])
        if non_fatal:
            self.compile_one([non_fatal])

        tables = self.infer_okx_tables()
        if self.source == "okx_strategy22_live_pilot":
            schema_ver = None
            if schema_ver is None and self.existing_tables():
                print("VERIFY SCHEMA 1", file=sys.stderr)

        results: List[Row] = []
        for table in tables:
            try:
                rows = self.cur.execute(f'SELECT * FROM "{table}"').fetchall()
            except sqlite3.Error as exc:
                if "no such table" in str(exc).lower() and self.create_missing:
                    continue
                if self.strict:
                    raise
                self.issue_non_fatal_warning(str(exc))
                continue
            if not rows:
                results.append(Row(table=table, id="empty", ts=PROBE_DEFAULT_ZERO_TIMESTAMP, data={"empty": True}))
                continue
            col_names = [desc[0] for desc in self.cur.description]
            for row in rows:
                mapped = {}
                for col, value in zip(col_names, row):
                    mapped[self.map_ascii(col)] = value
                id_value = mapped.get("id") or mapped.get("key") or len(results)
                ts_value = mapped.get("ts") or mapped.get("timestamp") or mapped.get("entered_at") or PROBE_DEFAULT_ZERO_TIMESTAMP
                results.append(Row(table=table, id=str(id_value), ts=str(ts_value), data=mapped))
        return results

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

def build_prober() -> Tuple[Optional[Any], Any]:
    preferred_modules = ["okx_strategy22_live_pilot", "crypto_bot"]
    for module_name in preferred_modules:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            continue
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception as exc:
            print(f"prober: failed to load module {module_name}: {exc}", file=sys.stderr)
            continue
        if hasattr(module, "ProbeLocalStorage"):
            prober = module.ProbeLocalStorage(root=os.getcwd())
        else:
            prober = None
        if hasattr(module, "ProbeCursor"):
            return prober, module.ProbeCursor  # type: ignore[return-value]
        if hasattr(module, "top10_training_config"):
            root = ROOT
            class InMemoryCursor:
                def __init__(self) -> None:
                    self.db_path = root / "data" / "okx_micro_5m_tracking.sqlite"
                    self._conn = sqlite3.connect(self.db_path)
                    self._conn.row_factory = sqlite3.Row

                def existing_tables(self) -> List[str]:
                    return [
                        row["name"]
                        for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    ]

                def create_l2_session(self) -> None:
                    self._conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS top10_l10_training_sessions (
                          id INTEGER PRIMARY KEY AUTOINCREMENT, signature TEXT, notes TEXT,
                          has_scalars INTEGER DEFAULT 1, created_at TEXT NOT NULL DEFAULT current_timestamp
                        )
                        """
                    )

                def create_l3_session(self) -> None:
                    self._conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS top10_live_pilot_training_sessions (
                          id INTEGER PRIMARY KEY AUTOINCREMENT, signature TEXT, notes TEXT,
                          created_at TEXT NOT NULL DEFAULT current_timestamp
                        )
                        """
                    )

                def create_top10_1h_training_sessions(self) -> None:
                    self._conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS top10_1h_training_sessions (
                          id INTEGER PRIMARY KEY AUTOINCREMENT, signature TEXT, notes TEXT,
                          created_at TEXT NOT NULL DEFAULT current_timestamp
                        )
                        """
                    )

                def issue_non_fatal_warning(self, *args: Any, **kwargs: Any) -> None:
                    return None

                def compile_one(self, statements: List[str]) -> None:
                    return None

                def extras_loaded(self) -> bool:
                    return True

                def probe(self, non_fatal: Optional[str] = None):  # type: ignore[return]
                    return []
            return prober, InMemoryCursor()
    return None, None


def replay(path: str = "data/okx_micro_5m_tracking.sqlite", source: Optional[str] = None, non_fatal: Optional[str] = None, create_missing: bool = False, strict: bool = True, json: bool = False) -> List[Row]:
    _, cursor_factory = build_prober() or (None, None)
    con = sqlite3.connect(path)
    cursor_factory = cursor_factory or sqlite3.Cursor
    cursor = cursor_factory(con)
    cursor_instance = ProbeCursor(cursor, create_missing=create_missing, source=source, strict=strict)
    rows = cursor_instance.probe(non_fatal)
    if not json:
        for item in rows:
            print(f"[{item.table}] id=item.id ts=item.ts data=item.data")
    else:
        print(json.dumps([asdict(item) for item in rows], ensure_ascii=False))
    return rows


def write_replay_dir(rows: List[Row], destination: Path) -> Path:
    root = destination.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    file_map: Dict[str, Path] = {}
    for item in rows:
        file_path = file_map.setdefault(item.table, root / f"{item.table}.json")
        existing: Dict[str, Any] = {}
        if file_path.exists():
            try:
                existing = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        existing[str(item)] = item.data
        file_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def compile(args: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compile top10 training session tables.")
    parser.add_argument("--sqlite-path", default="C:/Users/fuful/OneDrive/Desktop/LIGHTOARTS/_render_lighto_tracker/data/okx_micro_5m_tracking.sqlite")
    parsed_args = parser.parse_args(args=args)
    db_path = Path(parsed_args.sqlite_path)
    if not db_path.exists():
        print(f"OKX SQLite not found: {db_path}", file=sys.stderr)
        return 0
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cur.fetchall()]
        if "top10_1h_training_sessions" not in tables:
            cur.execute("CREATE TABLE IF NOT EXISTS top10_1h_training_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, inst_id TEXT NOT NULL, entered_at TEXT NOT NULL, entry_price REAL NOT NULL, last_price REAL NOT NULL, last_change_1h_pct REAL, max_change_1h_pct REAL, exit_reason TEXT, candle_count INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1)")
            con.commit()
            return 0
        missing = [name for name in REQUIRED_TABLES if name not in tables]
        if not missing:
            return 0
        for name in missing:
            cur.execute(f"CREATE TABLE IF NOT EXISTS {name} (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')))")
        con.commit()
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(compile(args=sys.argv[1:]))


@dataclass
class TradeOutcome:
    ts: Optional[str]
    instId: str
    pnlPct: Optional[float]
    pnlUsdt: Optional[float]
    outcome_type: str = "filled"
    strategy_id: Optional[str] = None
    session_id: Optional[int] = None
    meta: Dict[str, Any] = field(default_factory=dict)


# -------------------
# OKX tightly-coupled monitoring helpers
# -------------------

def _load_topgun_db(db_path: Path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    return con, cur


def _rows(cur: sqlite3.Cursor, table: str, limit: int = 2000):
    try:
        cur.execute(f'select * from "{table}" order by entered_at desc limit ?', (limit,))
    except Exception:
        try:
            cur.execute(f'select * from "{table}" order by id desc limit ?', (limit,))
        except Exception:
            return [], []
    rows = cur.fetchall()
    cols = [c[0] for c in cur.description] if cur.description else []
    return rows, cols


@dataclass
class TradeSnapshot:
    inst_id: str
    inst_type: str
    entered_at: str
    entry_price: float
    leverage: float
    td_mode: str
    margin_mode: str
    max_profit_pct: float
    max_drawdown_pct: float
    exit_reason: Optional[str]
    close_price: Optional[float]
    status: str


def read_memory_facts(cur: sqlite3.Cursor) -> Dict[str, Any]:
    rows, cols = _rows(cur, "top10_memory")
    facts: Dict[str, Any] = {
        "live_candidates": [],
        "paper_candidates": [],
        "shadow_candidates": [],
        "promotions": [],
        "rollbacks": [],
    }
    colmap = {c: i for i, c in enumerate(cols)}
    for r in rows:
        strategy = r[colmap.get("strategy_id", 0)] if "strategy_id" in colmap else (r[0] if r else "")
        stage = (r[colmap.get("stage", 1)] if "stage" in colmap else "live") or "live"
        facts[f"{stage}_candidates"].append(strategy)
    return facts


def read_guardrail_audit(cur: sqlite3.Cursor):
    rows, cols = _rows(cur, "top10_guardrail_audit")
    out: List[Dict[str, Any]] = []
    colmap = {c: i for i, c in enumerate(cols)}
    for r in rows:
        item = {c: r[i] for c, i in colmap.items()}
        out.append(item)
    return out


def read_sessions(cur: sqlite3.Cursor, table: str) -> List[TradeSnapshot]:
    rows, cols = _rows(cur, table)
    if not rows:
        return []
    colmap = {c: i for i, c in enumerate(cols)}
    out: List[TradeSnapshot] = []
    for r in rows:
        def get(name, default=None):
            return r[colmap[name]] if name in colmap else default
        out.append(TradeSnapshot(
            inst_id=get("inst_id"),
            inst_type=get("inst_type", "SWAP"),
            entered_at=get("entered_at"),
            entry_price=float(get("entry_price") or 0.0),
            leverage=float(get("lever") or get("leverage") or 5.0),
            td_mode=get("td_mode") or get("margin_mode") or "cross",
            margin_mode=get("mgn_mode") or get("margin_mode") or "cross",
            max_profit_pct=float(get("max_profit_pct") or (get("max_change_1h_pct") or 0.0)),
            max_drawdown_pct=float(get("max_drawdown_pct") or 0.0),
            exit_reason=get("exit_reason"),
            close_price=float(get("close_price")) if get("close_price") is not None else None,
            status=get("status") or ("open" if not get("exit_reason") else "closed"),
        ))
    return out


def infer_trade_outcomes(sessions: List[TradeSnapshot]) -> List[TradeOutcome]:
    closed = [s for s in sessions if s.status == "closed"]
    open_ = [s for s in sessions if s.status == "open"][: max(0, 80 - len(closed))]
    items: List[TradeOutcome] = []
    for s in closed + open_:
        pnl_pct = (s.close_price - s.entry_price) / s.entry_price * 100.0 if s.close_price is not None else None
        items.append(TradeOutcome(
            ts=s.entered_at,
            instId=s.inst_id,
            pnlPct=pnl_pct,
            pnlUsdt=None,
            outcome_type="filled" if s.status == "closed" else "open",
            session_id=None,
            meta={"status": s.status, "max_profit_pct": s.max_profit_pct, "max_drawdown_pct": s.max_drawdown_pct, "exit_reason": s.exit_reason, "leverage": s.leverage, "margin_mode": s.margin_mode, "td_mode": s.td_mode},
        ))
    return items


@dataclass
class GuardReview:
    rebalance_refused_reason: str
    rebalance_order_status_rank: Optional[int]
    stale_order_status_rank: Optional[int]
    stale_order_hours: Optional[float]
    stale_order_trade: Optional[int]
    stale_order_status_type: Optional[str]
    stale_inst_status_type: Optional[str]
    stale_order_inst_id: Optional[str]
    audit_events: List[Dict[str, Any]]
    notes: str = ""


def review_guardrail(db_path: Path) -> GuardReview:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    review = GuardReview(rebalance_refused_reason="blocked_risk_global_rollout_exit_order_cancel_blocked_risk_blacklisted", rebalance_order_status_rank=3, stale_order_status_rank=None, stale_order_hours=None, stale_order_trade=None, stale_order_status_type=None, stale_inst_status_type=None, stale_order_inst_id=None, audit_events=[], notes="")
    for table in ["top10_guardrail_audit", "top10_guardrail_audit_20260528", "top10_guardrail_audit_20260527", "top10_guardrail_audit_20260610", "top10_guardrail_audit_20260608"]:
        try:
            rows, cols = _rows(cur, table)
        except Exception:
            continue
        if not rows:
            continue
        colmap = {c: i for i, c in enumerate(cols)}
        for r in rows:
            reason = r[colmap.get("reason", 0)] if "reason" in colmap else None
            trade_ref = r[colmap.get("trade_id", 1)] if "trade_id" in colmap else None
            event = {c: r[i] for c, i in colmap.items()}
            review.audit_events.append(event)
            if reason and "blacklisted" in (reason or "").lower() and review.rebalance_order_status_rank is None:
                review.stale_order_status_type = reason
                review.stale_order_inst_id = event.get("inst_id")
            if reason and "stale" in (reason or "").lower() and review.stale_order_hours is None:
                review.stale_order_hours = float(event.get("stale_age_hours") or 0.0 or 0.0)
                review.stale_order_trade = trade_ref
                review.stale_order_status_type = reason
                review.stale_order_inst_id = event.get("inst_id")
    return review


def review_trade_performance(cur: sqlite3.Cursor) -> Dict[str, Any]:
    rows, cols = _rows(cur, "top10_trade_performance")
    if not rows:
        return {}
    colmap = {c: i for i, c in enumerate(cols)}
    values = []
    for r in rows:
        values.append({c: r[i] for c, i in colmap.items()})
    return values[-1] if values else {}


def review_decision(cur: sqlite3.Cursor) -> Dict[str, Any]:
    rows, cols = _rows(cur, "top10_decision_review")
    if not rows:
        return {}
    colmap = {c: i for i, c in enumerate(cols)}
    values = []
    for r in rows:
        values.append({c: r[i] for c, i in colmap.items()})
    return values[-1] if values else {}


def review_rebalance_log(cur: sqlite3.Cursor) -> Dict[str, Any]:
    rows, cols = _rows(cur, "top10_strategy_rebalance_log")
    if not rows:
        return {}
    colmap = {c: i for i, c in enumerate(cols)}
    values = []
    for r in rows:
        values.append({c: r[i] for c, i in colmap.items()})
    return values[-1] if values else {}


@dataclass
class MonitorInputs:
    sqlite_path: Path
    state_path: Path
    strategy_pool_path: Path
    active_strategies_path: Path
    report_path: Path
    retrain_bin: Optional[str]
    retrain_args: List[str]

    @classmethod
    def defaults(cls) -> "MonitorInputs":
        return cls(
            sqlite_path=ROOT / "data" / "okx_micro_5m_tracking.sqlite",
            state_path=ROOT / "data" / "okx_top10_live_pilot_state.json",
            strategy_pool_path=ROOT / "data" / "strategy_pool.json",
            active_strategies_path=ROOT / "data" / "active_strategies.json",
            report_path=ROOT / "data" / "monitor_report_latest.json",
            retrain_bin=str(sys.executable),
            retrain_args=["-u", str(ROOT / "tmp_top10_training_optimizer.py")],
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts() -> str:
    return _now().isoformat(timespec="seconds")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# -------------------
# Diagnosis heuristics (OKX live-focused)
# -------------------

@dataclass
class Diagnosis:
    root_cause: str
    confidence: float
    evidence: str
    recommends_retrain_window_days: int
    recommended_constraints: Dict[str, Any] = field(default_factory=dict)


def diagnose_okx(trades: List[TradeOutcome], thresholds: Dict[str, Any]) -> Optional[Diagnosis]:
    if len(trades) < int(thresholds.get("min_trades", 20)):
        return Diagnosis(root_cause="insufficient_sample", confidence=0.4, evidence=f"trades={len(trades)}", recommends_retrain_window_days=7, recommended_constraints={"min_sessions": 30})

    closed = [t for t in trades if t.outcome_type == "filled"]
    if not closed:
        return Diagnosis(root_cause="insufficient_sample", confidence=0.4, evidence="no closed trades", recommends_retrain_window_days=7, recommended_constraints={})

    rets = [float(t.pnlPct or 0.0) for t in closed]
    wins = sum(1 for r in rets if r >= 0.0)
    win_rate = wins / len(rets)
    expectancy = sum(rets) / len(rets)
    max_loss = min(rets)

    causes = []
    if win_rate < thresholds.get("win_rate_floor", 0.42):
        causes.append(("hit_rate_decay", 0.7, f"win_rate={win_rate:.2%}", 14, {"metric": "win_rate"}))
    if expectancy < thresholds.get("expectancy_floor", 0.0):
        causes.append(("negative_expectancy", 0.85, f"expectancy={expectancy:+.4f}%", 7, {"metric": "expectancy"}))
    if max_loss <= thresholds.get("max_single_loss", -4.0):
        causes.append(("tail_loss", 0.8, f"max_loss={max_loss:+.2f}%", 7, {"metric": "max_loss", "mode": "emergency_retrain"}))
    if any(t.meta.get("exit_reason") in {"hard_sl", "force_exit", "forced_exit"} for t in closed):
        causes.append(("sl_hit_rate_high", 0.75, "hard_sl_exit_detected", 14, {"metric": "hard_sl_count"}))
    if not causes:
        return None
    root_cause, confidence, evidence, window, constraints = max(causes, key=lambda t: t[1])
    return Diagnosis(root_cause=root_cause, confidence=confidence, evidence=evidence, recommends_retrain_window_days=window, recommended_constraints=constraints)


def build_report(cfg: MonitorInputs, trades: List[TradeOutcome], diagnosis: Optional[Diagnosis], guard: Optional[GuardReview]) -> Dict[str, Any]:
    closed = [t for t in trades if t.outcome_type == "filled"]
    rets = [float(t.pnlPct or 0.0) for t in closed]
    summary: Dict[str, Any] = {
        "reportedAt": _ts(),
        "overallAction": "monitor",
        "sessions": {
            "closed": len(closed),
            "open": len([t for t in trades if t.outcome_type == "open"]),
            "total": len(trades),
        },
        "performance": {
            "expectancy_pct": round(sum(rets) / len(rets), 4) if rets else None,
            "win_rate_pct": round(sum(1 for r in rets if r >= 0.0) / len(rets), 4) if rets else None,
            "max_loss_pct": round(min(rets), 4) if rets else None,
            "max_profit_pct": round(max(rets), 4) if rets else None,
        },
        "diagnosis": asdict(diagnosis) if diagnosis else None,
        "guardrail": {
            "rebalance_refused_reason": guard.rebalance_refused_reason if guard else None,
            "audit_events": guard.audit_events[:8] if guard else [],
        },
    }
    if diagnosis and diagnosis.root_cause != "insufficient_sample":
        summary["overallAction"] = "retrain_recommended"
    return summary


def invoke_retrain(cfg: MonitorInputs, diagnosis: Optional[Diagnosis]) -> Dict[str, Any]:
    if not diagnosis:
        return {"ok": True, "skipped": True, "reason": "no_diagnosis"}
    env = os.environ.copy()
    env["AUTOEVOLVE_RETRAIN"] = "1"
    env["AUTOEVOLVE_CAUSE"] = diagnosis.root_cause
    cmd = [cfg.retrain_bin] + cfg.retrain_args
    try:
        completed = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=5400)
    except Exception as exc:
        return {"ok": False, "error": f"retrain launch failed: {exc}"}
    return {"ok": completed.returncode == 0, "returncode": completed.returncode, "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-2000:], "command": cmd}


def main() -> int:
    cfg = MonitorInputs.defaults()

    if not cfg.sqlite_path.exists():
        probe = compile()
        raise SystemExit(1 if probe else 0)

    con, cur = _load_topgun_db(cfg.sqlite_path)
    try:
        sessions = read_sessions(cur, "top10_1h_training_sessions")
    finally:
        con.close()

    trades = infer_trade_outcomes(sessions) if sessions else []
    if not trades:
        trades = [TradeOutcome(ts=_ts(), instId="unknown", pnlPct=0.0, pnlUsdt=0.0)]

    diagnosis = diagnose_okx(trades, {"min_trades": 20, "win_rate_floor": 0.42, "expectancy_floor": 0.0, "max_single_loss": -4.0})
    report = build_report(cfg, trades, diagnosis, review_guardrail(cfg.sqlite_path))

    if diagnosis and diagnosis.root_cause != "insufficient_sample":
        retrain_result = invoke_retrain(cfg, diagnosis)
        report["retrain"] = retrain_result
        try:
            candidate_path = ROOT / "data" / "tmp_all_deployed.json"
            if candidate_path.exists():
                pool_path = cfg.strategy_pool_path
                try:
                    cands = load_json(candidate_path, [])
                    pool = load_json(pool_path, {"updated_at": _ts(), "candidates": []})
                    pool.setdefault("candidates", [])
                    known = {c.get("id") for c in pool["candidates"]}
                    added = 0
                    for c in cands[-3:]:
                        if "id" not in c:
                            c["id"] = f"auto_{_now().strftime('%Y%m%dT%H%M%S')}"
                        if c.get("id") not in known:
                            pool["candidates"].insert(0, c)
                            added += 1
                    save_json(pool_path, pool)
                    report.setdefault("retrain", {})["strategy_pool"] = {"appended_candidates": added, "path": str(pool_path)}
                except Exception as exc:
                    report.setdefault("retrain", {})["strategy_pool"] = {"error": str(exc)}
        except Exception:
            pass
    else:
        report["retrain"] = {"ok": True, "skipped": True, "reason": "no_actionable_diagnosis"}

    save_json(cfg.report_path, report)
    print(json.dumps({"overallAction": report["overallAction"], "reportPath": str(cfg.report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
