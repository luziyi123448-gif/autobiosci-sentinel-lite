import sqlite3

from autobiosci_sentinel.database import (
    accession_metadata,
    claim_next_run,
    count_papers,
    finish_run,
    has_active_runs,
    init_db,
    queue_run,
    recent_runs,
    refresh_accession_metadata,
    top_papers,
    upsert_papers,
)


def test_jobs_table_mirrors_runs_without_replacing_runs(tmp_path):
    db = tmp_path / "papers.sqlite"
    init_db(db)

    with sqlite3.connect(db) as conn:
        run_columns = [
            (row[1], row[2], row[3], row[4], row[5])
            for row in conn.execute("PRAGMA table_info(runs)")
        ]
        job_columns = [
            (row[1], row[2], row[3], row[4], row[5])
            for row in conn.execute("PRAGMA table_info(jobs)")
        ]

    assert job_columns == run_columns

    queue_run(db, "configs/topics.yaml", "reports/daily_report.md")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert conn.execute("SELECT id, status, config_path FROM jobs").fetchall() == [
            (1, "queued", "configs/topics.yaml")
        ]


def test_jobs_mirror_handles_legacy_runs_column_order(tmp_path):
    db = tmp_path / "papers.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'failed')),
                config_path TEXT NOT NULL,
                report_path TEXT NOT NULL,
                retmax INTEGER,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                fetched_count INTEGER NOT NULL DEFAULT 0,
                new_count INTEGER NOT NULL DEFAULT 0,
                total_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            )
            """
        )

    run_id = queue_run(
        db,
        "configs/topics.yaml",
        "reports/daily_report.md",
        start_date="2026/01/01",
        end_date="2026/01/31",
    )

    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT start_date, end_date FROM jobs WHERE id = ?",
            (run_id,),
        ).fetchone() == ("2026/01/01", "2026/01/31")


def test_sqlite_deduplicates_by_pmid(tmp_path):
    db = tmp_path / "papers.sqlite"
    paper = {
        "pmid": "1",
        "title": "Original",
        "abstract": "Abstract",
        "journal": "Journal",
        "pub_date": "2026-07-01",
        "authors": "Author",
        "doi": "10/test",
        "topic": "topic",
        "score": 1,
        "score_reasons": ["old"],
        "accessions": ["GSE0"],
        "fetched_at": "2026-07-04T00:00:00Z",
    }

    assert upsert_papers(db, [paper]) == 1
    updated = {
        **paper,
        "title": "Updated",
        "topic": "updated-topic",
        "score": 5,
        "score_reasons": ["new"],
        "accessions": ["GSE1"],
    }
    assert upsert_papers(db, [updated]) == 0

    assert count_papers(db) == 1
    saved = top_papers(db, limit=1)[0]
    assert saved["title"] == "Updated"
    assert saved["score"] == 5
    assert saved["score_reasons"] == ["new"]
    assert saved["accessions"] == ["GSE1"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT topic, pmid FROM paper_topics ORDER BY topic").fetchall() == [
            ("topic", "1"),
            ("updated-topic", "1"),
        ]
        assert conn.execute("SELECT accession, pmid FROM accession_index").fetchall() == [("GSE1", "1")]
    metadata = accession_metadata(db)
    assert len(metadata) == 1
    assert metadata[0]["accession"] == "GSE1"
    assert metadata[0]["source"] == "GEO"
    assert refresh_accession_metadata(db) == 1


def test_init_db_backfills_indexes_from_existing_papers(tmp_path):
    db = tmp_path / "papers.sqlite"
    init_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO papers (pmid, title, topic, accessions)
            VALUES ('1', 'Paper', 'topic', '["gse123"]')
            """
        )

    assert refresh_accession_metadata(db) == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT pmid, topic FROM paper_topics").fetchall() == [("1", "topic")]
        assert conn.execute("SELECT accession, pmid FROM accession_index").fetchall() == [("GSE123", "1")]
    assert accession_metadata(db)[0]["accession"] == "GSE123"


def test_run_queue_lifecycle(tmp_path):
    db = tmp_path / "papers.sqlite"

    assert has_active_runs(db) is False
    run_id = queue_run(db, "configs/topics.yaml", "reports/daily_report.md", retmax=5)
    assert has_active_runs(db) is True
    queued = recent_runs(db, limit=1)[0]
    assert queued["id"] == run_id
    assert queued["status"] == "queued"
    assert queued["retmax"] == 5
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, status, retmax FROM jobs").fetchall() == [(run_id, "queued", 5)]

    claimed = claim_next_run(db)
    assert claimed is not None
    assert claimed["id"] == run_id
    assert claimed["status"] == "running"
    assert claim_next_run(db) is None
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, status FROM jobs").fetchall() == [(run_id, "running")]

    finish_run(db, run_id, "succeeded", fetched_count=2, new_count=1, total_count=3)
    assert has_active_runs(db) is False
    finished = recent_runs(db, limit=1)[0]
    assert finished["status"] == "succeeded"
    assert finished["fetched_count"] == 2
    assert finished["new_count"] == 1
    assert finished["total_count"] == 3
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT status, fetched_count, new_count, total_count FROM jobs WHERE id = ?",
            (run_id,),
        ).fetchone() == ("succeeded", 2, 1, 3)
