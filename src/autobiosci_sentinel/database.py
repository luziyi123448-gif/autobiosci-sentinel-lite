from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from autobiosci_sentinel.accessions import describe_accessions


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    pmid TEXT PRIMARY KEY,
    title TEXT,
    abstract TEXT,
    journal TEXT,
    pub_date TEXT,
    authors TEXT,
    doi TEXT,
    topic TEXT,
    score INTEGER,
    score_reasons TEXT,
    accessions TEXT,
    fetched_at TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT
)
"""

RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed')),
    config_path TEXT NOT NULL,
    report_path TEXT NOT NULL,
    retmax INTEGER,
    start_date TEXT,
    end_date TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    new_count INTEGER NOT NULL DEFAULT 0,
    total_count INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT ''
)
"""

JOBS_SCHEMA = RUNS_SCHEMA.replace("runs", "jobs", 1)

RUN_COLUMNS = (
    "id, status, config_path, report_path, retmax, start_date, end_date, created_at, "
    "started_at, finished_at, fetched_count, new_count, total_count, error"
)

PAPER_TOPICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_topics (
    pmid TEXT NOT NULL,
    topic TEXT NOT NULL,
    PRIMARY KEY (pmid, topic),
    FOREIGN KEY (pmid) REFERENCES papers(pmid)
)
"""

ACCESSION_INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS accession_index (
    accession TEXT NOT NULL,
    pmid TEXT NOT NULL,
    PRIMARY KEY (accession, pmid),
    FOREIGN KEY (pmid) REFERENCES papers(pmid)
)
"""

ACCESSION_METADATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS accession_metadata (
    accession TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    checked_at TEXT NOT NULL
)
"""


def init_db(path: str | Path) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(SCHEMA)
        conn.execute(RUNS_SCHEMA)
        conn.execute(JOBS_SCHEMA)
        _ensure_run_columns(conn, "runs")
        _ensure_run_columns(conn, "jobs")
        conn.execute(PAPER_TOPICS_SCHEMA)
        conn.execute(ACCESSION_INDEX_SCHEMA)
        conn.execute(ACCESSION_METADATA_SCHEMA)
        _backfill_secondary_indexes(conn)


def _ensure_run_columns(conn: sqlite3.Connection, table: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if "start_date" not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN start_date TEXT")
    if "end_date" not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN end_date TEXT")


def _backfill_secondary_indexes(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT pmid, topic, accessions FROM papers").fetchall()
    for pmid, topic, accessions_text in rows:
        if topic:
            conn.execute("INSERT OR IGNORE INTO paper_topics (pmid, topic) VALUES (?, ?)", (pmid, topic))
        accessions = _load_accessions(accessions_text)
        conn.executemany(
            "INSERT OR IGNORE INTO accession_index (accession, pmid) VALUES (?, ?)",
            [(accession, pmid) for accession in accessions],
        )


def _load_accessions(value: str | None) -> list[str]:
    try:
        items = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    return sorted({str(item).upper() for item in items if item})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _mirror_run_to_job(conn: sqlite3.Connection, run_id: int) -> None:
    if conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
        return
    conn.execute("DELETE FROM jobs WHERE id = ?", (run_id,))
    conn.execute(f"INSERT INTO jobs ({RUN_COLUMNS}) SELECT {RUN_COLUMNS} FROM runs WHERE id = ?", (run_id,))


def upsert_papers(path: str | Path, papers: list[dict[str, Any]]) -> int:
    init_db(path)
    now = utc_now()
    inserted = 0
    with sqlite3.connect(path) as conn:
        all_accessions: set[str] = set()
        for paper in papers:
            accessions = sorted({str(accession).upper() for accession in paper.get("accessions") or [] if accession})
            all_accessions.update(accessions)
            topic = paper.get("topic", "")
            exists = conn.execute("SELECT 1 FROM papers WHERE pmid = ?", (paper["pmid"],)).fetchone()
            if exists is None:
                inserted += 1
            conn.execute(
                """
                INSERT INTO papers (
                    pmid, title, abstract, journal, pub_date, authors, doi, topic,
                    score, score_reasons, accessions, fetched_at, first_seen_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pmid) DO UPDATE SET
                    title = excluded.title,
                    abstract = excluded.abstract,
                    journal = excluded.journal,
                    pub_date = excluded.pub_date,
                    authors = excluded.authors,
                    doi = excluded.doi,
                    topic = excluded.topic,
                    score = excluded.score,
                    score_reasons = excluded.score_reasons,
                    accessions = excluded.accessions,
                    fetched_at = excluded.fetched_at,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    paper["pmid"],
                    paper.get("title", ""),
                    paper.get("abstract", ""),
                    paper.get("journal", ""),
                    paper.get("pub_date", ""),
                    paper.get("authors", ""),
                    paper.get("doi", ""),
                    topic,
                    int(paper.get("score", 0)),
                    json.dumps(paper.get("score_reasons", []), ensure_ascii=False),
                    json.dumps(accessions, ensure_ascii=False),
                    paper.get("fetched_at", now),
                    now,
                    now,
                ),
            )
            pmid = paper["pmid"]
            conn.execute("DELETE FROM accession_index WHERE pmid = ?", (pmid,))
            if topic:
                conn.execute("INSERT OR IGNORE INTO paper_topics (pmid, topic) VALUES (?, ?)", (pmid, topic))
            conn.executemany(
                "INSERT OR IGNORE INTO accession_index (accession, pmid) VALUES (?, ?)",
                [(accession, pmid) for accession in accessions if accession],
            )
        _upsert_accession_metadata(conn, all_accessions, now)
    return inserted


def refresh_accession_metadata(path: str | Path) -> int:
    init_db(path)
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT DISTINCT accession FROM accession_index ORDER BY accession").fetchall()
        accessions = [row[0] for row in rows]
        _upsert_accession_metadata(conn, accessions, utc_now())
    return len(accessions)


def accession_metadata(path: str | Path) -> list[dict[str, Any]]:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                metadata.accession,
                metadata.source,
                metadata.url,
                metadata.checked_at,
                COUNT(accession_index.pmid) AS paper_count
            FROM accession_metadata AS metadata
            JOIN accession_index ON accession_index.accession = metadata.accession
            GROUP BY metadata.accession
            ORDER BY metadata.accession
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _upsert_accession_metadata(conn: sqlite3.Connection, accessions: set[str] | list[str], checked_at: str) -> None:
    conn.executemany(
        """
        INSERT INTO accession_metadata (accession, source, url, checked_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(accession) DO UPDATE SET
            source = excluded.source,
            url = excluded.url,
            checked_at = excluded.checked_at
        """,
        [
            (item["accession"], item["source"], item["url"], checked_at)
            for item in describe_accessions(list(accessions))
        ],
    )


def queue_run(
    path: str | Path,
    config_path: str,
    report_path: str,
    retmax: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    init_db(path)
    now = utc_now()
    with sqlite3.connect(path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (status, config_path, report_path, retmax, start_date, end_date, created_at)
            VALUES ('queued', ?, ?, ?, ?, ?, ?)
            """,
            (config_path, report_path, retmax, start_date, end_date, now),
        )
        _mirror_run_to_job(conn, int(cursor.lastrowid))
    return int(cursor.lastrowid)


def has_active_runs(path: str | Path) -> bool:
    init_db(path)
    with sqlite3.connect(path) as conn:
        return (
            conn.execute("SELECT 1 FROM runs WHERE status IN ('queued', 'running') LIMIT 1").fetchone()
            is not None
        )


def has_recent_succeeded_run(
    path: str | Path,
    config_path: str,
    report_path: str,
    retmax: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    window_seconds: int = 0,
    now: datetime | None = None,
) -> bool:
    if window_seconds <= 0:
        return False
    init_db(path)
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = (reference - timedelta(seconds=window_seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")
    with sqlite3.connect(path) as conn:
        return (
            conn.execute(
                """
                SELECT 1
                FROM runs
                WHERE status = 'succeeded'
                  AND config_path = ?
                  AND report_path = ?
                  AND (retmax = ? OR (retmax IS NULL AND ? IS NULL))
                  AND (start_date = ? OR (start_date IS NULL AND ? IS NULL))
                  AND (end_date = ? OR (end_date IS NULL AND ? IS NULL))
                  AND finished_at >= ?
                ORDER BY finished_at DESC
                LIMIT 1
                """,
                (config_path, report_path, retmax, retmax, start_date, start_date, end_date, end_date, cutoff),
            ).fetchone()
            is not None
        )


def claim_next_run(path: str | Path) -> dict[str, Any] | None:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM runs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            conn.commit()
            return None
        now = utc_now()
        conn.execute(
            "UPDATE runs SET status = 'running', started_at = ?, error = '' WHERE id = ?",
            (now, row["id"]),
        )
        _mirror_run_to_job(conn, int(row["id"]))
        conn.commit()
        updated = conn.execute("SELECT * FROM runs WHERE id = ?", (row["id"],)).fetchone()
    return dict(updated)


def finish_run(
    path: str | Path,
    run_id: int,
    status: str,
    fetched_count: int = 0,
    new_count: int = 0,
    total_count: int = 0,
    error: str = "",
) -> None:
    if status not in {"succeeded", "failed"}:
        raise ValueError("status must be 'succeeded' or 'failed'")
    init_db(path)
    now = utc_now()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            UPDATE runs
            SET status = ?, finished_at = ?, fetched_count = ?, new_count = ?, total_count = ?, error = ?
            WHERE id = ?
            """,
            (status, now, fetched_count, new_count, total_count, error, run_id),
        )
        _mirror_run_to_job(conn, run_id)


def recent_runs(path: str | Path, limit: int = 10) -> list[dict[str, Any]]:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def recent_jobs(path: str | Path, limit: int = 10) -> list[dict[str, Any]]:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def count_papers(path: str | Path) -> int:
    init_db(path)
    with sqlite3.connect(path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0])


def top_papers(path: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    return _query(
        path,
        """
        SELECT * FROM papers
        ORDER BY score DESC, pub_date DESC, pmid DESC
        LIMIT ?
        """,
        (limit,),
    )


def accession_papers(path: str | Path) -> list[dict[str, Any]]:
    return _query(
        path,
        """
        SELECT * FROM papers
        WHERE accessions IS NOT NULL AND accessions != '[]' AND accessions != ''
        ORDER BY score DESC, pub_date DESC
        """,
        (),
    )


def _query(path: str | Path, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    papers = [dict(row) for row in rows]
    for paper in papers:
        paper["score_reasons"] = json.loads(paper.get("score_reasons") or "[]")
        paper["accessions"] = json.loads(paper.get("accessions") or "[]")
    _attach_accession_metadata(path, papers)
    return papers


def _attach_accession_metadata(path: str | Path, papers: list[dict[str, Any]]) -> None:
    accessions = sorted({accession for paper in papers for accession in paper["accessions"]})
    for paper in papers:
        paper["accession_metadata"] = {}
    if not accessions:
        return
    placeholders = ",".join("?" for _ in accessions)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT accession, source, url, checked_at FROM accession_metadata WHERE accession IN ({placeholders})",
            accessions,
        ).fetchall()
    metadata = {row["accession"]: dict(row) for row in rows}
    for paper in papers:
        paper["accession_metadata"] = {
            accession: metadata[accession]
            for accession in paper["accessions"]
            if accession in metadata
        }
