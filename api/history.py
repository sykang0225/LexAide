"""
api/history.py — 심의 이력·승인 로그 (SQLite, 표준 sqlite3)

준법관리자의 승인/수정요청/반려 결정을 저장·조회한다.
의존성 추가 없이 stdlib sqlite3만 사용.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

_DB = Path(__file__).parent.parent / "data" / "review_history.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB))
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    c = _conn()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mode       TEXT,
                verdict    TEXT,
                risk_score REAL,
                decision   TEXT,
                reviewer   TEXT,
                reason     TEXT,
                snippet    TEXT
            )"""
        )
        # 규칙 피드백(낮춤/올림/추가) 변경 이력 — "누가·언제·무엇을·왜·이전값→이후값"
        c.execute(
            """CREATE TABLE IF NOT EXISTS rule_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                actor     TEXT,
                action    TEXT,
                tree_file TEXT,
                rule_id   TEXT,
                node_id   TEXT,
                field     TEXT,
                before    TEXT,
                after     TEXT,
                reason    TEXT,
                backup    TEXT
            )"""
        )
        c.commit()
    finally:
        c.close()


def add_review(rec: dict) -> int:
    """결정 1건 저장 → row id 반환."""
    with _lock:
        c = _conn()
        try:
            cur = c.execute(
                "INSERT INTO reviews "
                "(created_at, mode, verdict, risk_score, decision, reviewer, reason, snippet) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    rec.get("mode", ""),
                    rec.get("verdict", ""),
                    rec.get("risk_score"),
                    rec.get("decision", ""),
                    (rec.get("reviewer") or "준법관리자"),
                    rec.get("reason", ""),
                    rec.get("snippet", ""),
                ),
            )
            c.commit()
            return int(cur.lastrowid)
        finally:
            c.close()


def list_reviews(limit: int = 50) -> list[dict]:
    """최근순 이력 조회."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def add_rule_change(rec: dict) -> int:
    """규칙 피드백 변경 1건 기록 → row id."""
    with _lock:
        c = _conn()
        try:
            cur = c.execute(
                "INSERT INTO rule_changes "
                "(created_at, actor, action, tree_file, rule_id, node_id, field, before, after, reason, backup) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    (rec.get("actor") or "준법관리자"),
                    rec.get("action", ""),
                    rec.get("tree_file", ""),
                    rec.get("rule_id", ""),
                    rec.get("node_id", ""),
                    rec.get("field", ""),
                    "" if rec.get("before") is None else str(rec.get("before")),
                    "" if rec.get("after") is None else str(rec.get("after")),
                    rec.get("reason", ""),
                    rec.get("backup", ""),
                ),
            )
            c.commit()
            return int(cur.lastrowid)
        finally:
            c.close()


def list_rule_changes(limit: int = 50) -> list[dict]:
    """최근순 규칙 변경 이력 조회."""
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM rule_changes ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


# 모듈 로드 시 테이블 보장
init_db()
