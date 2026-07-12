import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from autobiosci_sentinel import cli
from autobiosci_sentinel.config import Topic
from autobiosci_sentinel.database import queue_run, upsert_papers
from autobiosci_sentinel.pubmed import PubMedSearchResult
from autobiosci_sentinel.report import VALIDATION_COLUMNS

SPOTCHECK_COLUMNS = [
    "pmid",
    "reviewer_relevant",
    "reviewer_topic_match",
    "reviewer_transcriptomics",
    "reviewer_rnaseq_or_scrnaseq",
    "reviewer_biomarker_focus",
    "reviewer_accession_present",
    "reviewer_accessions",
    "reviewer_accession_match_status",
    "reviewer_accession_eval_label",
    "reviewer_error_category",
]


def _write_validation_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=VALIDATION_COLUMNS)
        writer.writeheader()
        for row in rows:
            complete_row = {column: "" for column in VALIDATION_COLUMNS}
            complete_row["snapshot_id"] = "s"
            complete_row["tool_accession_candidate_present"] = "no"
            complete_row.update(row)
            writer.writerow(complete_row)


def _write_spotcheck_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SPOTCHECK_COLUMNS)
        writer.writeheader()
        for row in rows:
            complete_row = {column: "" for column in SPOTCHECK_COLUMNS}
            complete_row.update(row)
            writer.writerow(complete_row)


def _mark_run_succeeded(db, run_id, finished_at):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE runs SET status = 'succeeded', started_at = ?, finished_at = ?, error = '' WHERE id = ?",
            (finished_at, finished_at, run_id),
        )
        conn.execute(
            "UPDATE jobs SET status = 'succeeded', started_at = ?, finished_at = ?, error = '' WHERE id = ?",
            (finished_at, finished_at, run_id),
        )


def test_run_pipeline_passes_date_range_to_collect_papers(monkeypatch):
    captured = {}

    def fake_collect_papers(config_path, retmax=None, start_date=None, end_date=None):
        captured.update(
            {
                "config_path": config_path,
                "retmax": retmax,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return 1, []

    monkeypatch.setattr(cli, "collect_papers", fake_collect_papers)
    monkeypatch.setattr(cli, "write_outputs", lambda db_path, report_path, topics_count, papers: {"fetched": 0})

    result = cli.run_pipeline(
        "config.yaml",
        "papers.sqlite",
        "report.md",
        retmax=5,
        start_date="2026/01/01",
        end_date="2026/07/01",
    )

    assert result == {"fetched": 0}
    assert captured == {
        "config_path": "config.yaml",
        "retmax": 5,
        "start_date": "2026/01/01",
        "end_date": "2026/07/01",
    }


def test_collect_papers_passes_date_range_to_search_pubmed(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        cli,
        "load_topics",
        lambda config_path, retmax: [
            Topic(name="topic", query="query", core_keywords=[], retmax=7, days_back=14)
        ],
    )

    def fake_search_pubmed(query, retmax, days_back=None, start_date=None, end_date=None):
        captured.update(
            {
                "query": query,
                "retmax": retmax,
                "days_back": days_back,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return ["12345"]

    monkeypatch.setattr(cli, "search_pubmed", fake_search_pubmed)
    monkeypatch.setattr(cli, "fetch_pubmed_xml", lambda pmids: "")
    monkeypatch.setattr(cli, "parse_pubmed_xml", lambda xml_text, topic: [])

    topics_count, papers = cli.collect_papers(
        "config.yaml",
        start_date="2026/01/01",
        end_date="2026/07/01",
    )

    assert topics_count == 1
    assert papers == []
    assert captured == {
        "query": "query",
        "retmax": 7,
        "days_back": 14,
        "start_date": "2026/01/01",
        "end_date": "2026/07/01",
    }


def test_process_next_run_passes_queued_date_range_to_run_pipeline(tmp_path, monkeypatch):
    db = tmp_path / "papers.sqlite"
    run_id = queue_run(
        db,
        "config.yaml",
        "report.md",
        retmax=5,
        start_date="2026/01/01",
        end_date="2026/07/01",
    )
    captured = {}

    def fake_run_pipeline(config_path, db_path, report_path, retmax=None, start_date=None, end_date=None):
        captured.update(
            {
                "config_path": config_path,
                "db_path": db_path,
                "report_path": report_path,
                "retmax": retmax,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return {"fetched": 2, "new": 1, "total": 3}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    result = cli.process_next_run(str(db))

    assert result == {"id": run_id, "status": "succeeded", "fetched": 2, "new": 1, "total": 3}
    assert captured == {
        "config_path": "config.yaml",
        "db_path": str(db),
        "report_path": "report.md",
        "retmax": 5,
        "start_date": "2026/01/01",
        "end_date": "2026/07/01",
    }


def test_worker_respects_max_jobs(tmp_path, monkeypatch):
    db = tmp_path / "papers.sqlite"
    first_id = queue_run(db, "config1.yaml", "report1.md")
    second_id = queue_run(db, "config2.yaml", "report2.md")
    processed = []

    def fake_run_pipeline(config_path, db_path, report_path, retmax=None, start_date=None, end_date=None):
        processed.append(config_path)
        return {"fetched": 0, "new": 0, "total": 0}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    result = cli.main(["worker", "--db", str(db), "--max-jobs", "1"])

    assert result == 0
    assert processed == ["config1.yaml"]
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT id, status FROM runs ORDER BY id").fetchall()
    assert rows == [(first_id, "succeeded"), (second_id, "queued")]


def test_worker_auto_queues_one_run_before_processing(tmp_path, monkeypatch):
    db = tmp_path / "papers.sqlite"
    captured = {}

    def fake_run_pipeline(config_path, db_path, report_path, retmax=None, start_date=None, end_date=None):
        captured.update(
            {
                "config_path": config_path,
                "db_path": db_path,
                "report_path": report_path,
                "retmax": retmax,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return {"fetched": 0, "new": 0, "total": 0}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    result = cli.main(
        [
            "worker",
            "--auto",
            "--config",
            "config.yaml",
            "--db",
            str(db),
            "--report",
            "report.md",
            "--retmax",
            "5",
            "--start-date",
            "2026/01/01",
            "--end-date",
            "2026/07/01",
            "--max-jobs",
            "1",
        ]
    )

    assert result == 0
    assert captured == {
        "config_path": "config.yaml",
        "db_path": str(db),
        "report_path": "report.md",
        "retmax": 5,
        "start_date": "2026/01/01",
        "end_date": "2026/07/01",
    }
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT status, retmax, start_date, end_date FROM runs").fetchall()
    assert rows == [("succeeded", 5, "2026/01/01", "2026/07/01")]


def test_worker_auto_skips_recent_duplicate_within_window(tmp_path, monkeypatch, capsys):
    db = tmp_path / "papers.sqlite"
    prior_run_id = queue_run(db, "config.yaml", "report.md", retmax=5, start_date="2026/01/01", end_date="2026/07/01")
    recent_finished_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    _mark_run_succeeded(db, prior_run_id, recent_finished_at)

    def fail_run_pipeline(*args, **kwargs):
        raise AssertionError("recent duplicate auto run should not be processed")

    monkeypatch.setattr(cli, "run_pipeline", fail_run_pipeline)

    result = cli.main(
        [
            "worker",
            "--auto",
            "--config",
            "config.yaml",
            "--db",
            str(db),
            "--report",
            "report.md",
            "--retmax",
            "5",
            "--start-date",
            "2026/01/01",
            "--end-date",
            "2026/07/01",
            "--dedupe-window-seconds",
            "10",
            "--max-jobs",
            "1",
        ]
    )

    assert result == 0
    output_lines = capsys.readouterr().out.strip().splitlines()
    assert json.loads(output_lines[-1]) == {"processed": 0, "worker_result": "recent_duplicate_no_op"}
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_worker_auto_queues_when_recent_success_is_outside_window(tmp_path, monkeypatch):
    db = tmp_path / "papers.sqlite"
    prior_run_id = queue_run(db, "config.yaml", "report.md", retmax=5, start_date="2026/01/01", end_date="2026/07/01")
    old_finished_at = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    _mark_run_succeeded(db, prior_run_id, old_finished_at)
    processed = []

    def fake_run_pipeline(config_path, db_path, report_path, retmax=None, start_date=None, end_date=None):
        processed.append((config_path, db_path, report_path, retmax, start_date, end_date))
        return {"fetched": 0, "new": 0, "total": 0}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    result = cli.main(
        [
            "worker",
            "--auto",
            "--config",
            "config.yaml",
            "--db",
            str(db),
            "--report",
            "report.md",
            "--retmax",
            "5",
            "--start-date",
            "2026/01/01",
            "--end-date",
            "2026/07/01",
            "--dedupe-window-seconds",
            "10",
            "--max-jobs",
            "1",
        ]
    )

    assert result == 0
    assert processed == [
        ("config.yaml", str(db), "report.md", 5, "2026/01/01", "2026/07/01"),
    ]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2


def test_worker_auto_default_dedupe_window_still_queues_recent_match(tmp_path, monkeypatch):
    db = tmp_path / "papers.sqlite"
    prior_run_id = queue_run(db, "config.yaml", "report.md", retmax=5, start_date="2026/01/01", end_date="2026/07/01")
    recent_finished_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    _mark_run_succeeded(db, prior_run_id, recent_finished_at)
    processed = []

    def fake_run_pipeline(config_path, db_path, report_path, retmax=None, start_date=None, end_date=None):
        processed.append((config_path, db_path, report_path, retmax, start_date, end_date))
        return {"fetched": 0, "new": 0, "total": 0}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    result = cli.main(
        [
            "worker",
            "--auto",
            "--config",
            "config.yaml",
            "--db",
            str(db),
            "--report",
            "report.md",
            "--retmax",
            "5",
            "--start-date",
            "2026/01/01",
            "--end-date",
            "2026/07/01",
            "--max-jobs",
            "1",
        ]
    )

    assert result == 0
    assert processed == [
        ("config.yaml", str(db), "report.md", 5, "2026/01/01", "2026/07/01"),
    ]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2


def test_auto_help_describes_bounded_worker(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["auto", "--help"])

    assert excinfo.value.code == 0
    assert "Queue one run and process bounded queued jobs" in capsys.readouterr().out


def test_status_reads_jobs_table(tmp_path, capsys):
    db = tmp_path / "papers.sqlite"
    run_id = queue_run(db, "config.yaml", "report.md")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE runs SET error = 'from-runs' WHERE id = ?", (run_id,))
        conn.execute(
            "UPDATE jobs SET status = 'failed', fetched_count = 9, error = 'from-jobs' WHERE id = ?",
            (run_id,),
        )

    result = cli.main(["status", "--db", str(db)])

    assert result == 0
    output = capsys.readouterr().out
    assert f"{run_id} failed" in output
    assert "fetched=9" in output
    assert "from-jobs" in output
    assert "from-runs" not in output


def test_auto_command_does_not_queue_when_runs_are_queued(tmp_path, monkeypatch):
    db = tmp_path / "papers.sqlite"
    queue_run(db, "queued1.yaml", "queued1.md")
    queue_run(db, "queued2.yaml", "queued2.md")
    queue_run(db, "queued3.yaml", "queued3.md")
    processed = []

    def fake_run_pipeline(config_path, db_path, report_path, retmax=None, start_date=None, end_date=None):
        processed.append((config_path, db_path, report_path, retmax, start_date, end_date))
        return {"fetched": 0, "new": 0, "total": 0}

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    result = cli.main(
        [
            "auto",
            "--config",
            "config.yaml",
            "--db",
            str(db),
            "--report",
            "report.md",
            "--retmax",
            "5",
            "--start-date",
            "2026/01/01",
            "--end-date",
            "2026/07/01",
        ]
    )

    assert result == 0
    assert processed == [
        ("queued1.yaml", str(db), "queued1.md", None, None, None),
        ("queued2.yaml", str(db), "queued2.md", None, None, None),
        ("queued3.yaml", str(db), "queued3.md", None, None, None),
    ]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT config_path, status FROM runs ORDER BY id").fetchall() == [
            ("queued1.yaml", "succeeded"),
            ("queued2.yaml", "succeeded"),
            ("queued3.yaml", "succeeded"),
        ]


def test_worker_auto_does_not_queue_when_run_is_running(tmp_path, monkeypatch, capsys):
    db = tmp_path / "papers.sqlite"
    run_id = queue_run(db, "running.yaml", "running.md")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run_id,))

    def fail_run_pipeline(*args, **kwargs):
        raise AssertionError("running work should not be processed")

    monkeypatch.setattr(cli, "run_pipeline", fail_run_pipeline)

    result = cli.main(
        [
            "worker",
            "--auto",
            "--config",
            "config.yaml",
            "--db",
            str(db),
            "--report",
            "report.md",
            "--max-jobs",
            "1",
        ]
    )

    assert result == 0
    output_lines = capsys.readouterr().out.strip().splitlines()
    assert json.loads(output_lines[-1]) == {"processed": 0, "worker_result": "overlap_no_op"}
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT config_path, status FROM runs ORDER BY id").fetchall() == [
            ("running.yaml", "running"),
        ]


def test_seed_windows_queues_one_run_per_window(tmp_path):
    config = tmp_path / "topics.yaml"
    config.write_text(
        """
topics:
  - name: topic_a
    query: query a
    core_keywords: []
  - name: topic_b
    query: query b
    core_keywords: []
""".lstrip(),
        encoding="utf-8",
    )
    db = tmp_path / "papers.sqlite"

    result = cli.main(
        [
            "seed-windows",
            "--config",
            str(config),
            "--db",
            str(db),
            "--report",
            "report.md",
            "--start-date",
            "2026/01/01",
            "--end-date",
            "2026/01/05",
            "--window-days",
            "3",
            "--retmax",
            "5",
        ]
    )

    assert result == 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT start_date, end_date, retmax FROM runs ORDER BY id"
        ).fetchall()
    assert rows == [
        ("2026/01/01", "2026/01/03", 5),
        ("2026/01/04", "2026/01/05", 5),
    ]


def test_accessions_command_lists_metadata(tmp_path, capsys):
    db = tmp_path / "papers.sqlite"
    upsert_papers(
        db,
        [
            {
                "pmid": "1",
                "title": "Paper",
                "accessions": ["GSE123"],
            }
        ],
    )

    result = cli.main(["accessions", "--db", str(db)])

    assert result == 0
    output = capsys.readouterr().out
    assert "GSE123\tGEO\t1\thttps://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123" in output


def test_write_outputs_creates_fixed_pipeline_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "papers.sqlite"

    cli.write_outputs(
        str(db),
        "reports/daily_report.md",
        1,
        [
            {
                "pmid": "1",
                "title": "Paper",
                "abstract": "Abstract with GSE123",
                "journal": "Journal",
                "pub_date": "2026-07-01",
                "topic": "topic",
                "score": 10,
                "score_reasons": ["public dataset accession candidate"],
                "accessions": ["GSE123"],
            }
        ],
    )

    for relative_path in [
        "reports/run_summary.md",
        "reports/backfill_status.md",
        "reports/accession_candidates.md",
        "outputs/accessions.txt",
    ]:
        text = (tmp_path / relative_path).read_text(encoding="utf-8")
        assert "GSE123" in text

    assert (tmp_path / "reports/daily_report.md").exists()
    assert (tmp_path / "reports/daily_report.top_papers.json").exists()
    assert (tmp_path / "reports/daily_report.accession_candidates.json").exists()


def test_run_pipeline_writes_search_run_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "papers.sqlite"
    report = tmp_path / "reports" / "daily_report.md"
    monkeypatch.setattr(
        cli,
        "load_topics",
        lambda config_path, retmax: [
            Topic(name="topic", query='"cancer" AND "RNA-seq"', core_keywords=["cancer"], retmax=7, days_back=14)
        ],
    )
    monkeypatch.setattr(cli, "search_pubmed", lambda *args, **kwargs: PubMedSearchResult(["12345"], raw_count=42))
    monkeypatch.setattr(cli, "fetch_pubmed_xml", lambda pmids: "")
    monkeypatch.setattr(
        cli,
        "parse_pubmed_xml",
        lambda xml_text, topic: [
            {
                "pmid": "12345",
                "title": "Cancer RNA-seq study",
                "abstract": "RNA-seq biomarker evidence",
                "journal": "Journal",
                "pub_date": "2026-07-01",
                "doi": "10.1/example",
                "topic": topic,
                "authors": "A. Author",
            }
        ],
    )

    result = cli.run_pipeline("config.yaml", str(db), str(report), start_date="2026/01/01", end_date="2026/07/01")

    metadata = json.loads((tmp_path / "reports" / "search_run_metadata.json").read_text(encoding="utf-8"))
    assert result["fetched"] == 1
    assert metadata["schema_version"] == "search_run_metadata.v1"
    assert metadata["total_retrieved_pmids"] == 1
    assert metadata["total_parsed_records"] == 1
    assert metadata["topics"][0]["topic_id"] == "topic"
    assert metadata["topics"][0]["query"] == '"cancer" AND "RNA-seq"'
    assert metadata["topics"][0]["raw_pubmed_hit_count"] == 42
    assert metadata["topics"][0]["retrieved_pmids_count"] == 1
    assert metadata["topics"][0]["start_date"] == "2026/01/01"
    assert metadata["topics"][0]["end_date"] == "2026/07/01"


def test_manuscript_command_writes_submission_draft(tmp_path):
    config = tmp_path / "topics.yaml"
    config.write_text(
        """
topics:
  - name: topic
    query: query
    core_keywords:
      - biomarker
""".lstrip(),
        encoding="utf-8",
    )
    db = tmp_path / "papers.sqlite"
    output = tmp_path / "reports" / "manuscript_draft.md"
    ai_summary = tmp_path / "reports" / "ai_consensus_spotcheck_summary.json"
    ai_summary.parent.mkdir(parents=True, exist_ok=True)
    ai_summary.write_text(
        '[{"completed_records":14,"total_records":14,"disagreed_records":1,"field_disagreements":1}]\n',
        encoding="utf-8",
    )
    upsert_papers(
        db,
        [
            {
                "pmid": "1",
                "title": "Paper",
                "abstract": "Abstract with GSE123",
                "journal": "Journal",
                "pub_date": "2026-07-04",
                "topic": "topic",
                "score": 5,
                "score_reasons": ["public dataset accession candidate"],
                "accessions": ["GSE123"],
            }
        ],
    )

    result = cli.main(
        [
            "manuscript",
            "--config",
            str(config),
            "--db",
            str(db),
            "--output",
            str(output),
            "--ai-spotcheck-summary",
            str(ai_summary),
        ]
    )

    assert result == 0
    text = output.read_text(encoding="utf-8")
    assert "Legacy Manuscript Draft Redirect" in text
    assert "reports/review_draft.md" in text
    assert "reports/submission_manifest.md" in text
    assert "GSE123" not in text
    assert "AI-assisted consensus spot-check completed" not in text
    assert "manual eligibility screening has been completed" not in text


def test_review_command_writes_review_package(tmp_path):
    config = tmp_path / "topics.yaml"
    config.write_text(
        """
topics:
  - name: topic
    query: query
    core_keywords:
      - biomarker
""".lstrip(),
        encoding="utf-8",
    )
    db = tmp_path / "papers.sqlite"
    output_dir = tmp_path / "reports"
    upsert_papers(
        db,
        [
            {
                "pmid": "1",
                "doi": "10.1/example",
                "title": "Paper",
                "abstract": "Abstract with GSE123",
                "journal": "Journal",
                "pub_date": "2026-07-04",
                "authors": "A. Author",
                "topic": "topic",
                "score": 5,
                "score_reasons": ["public dataset accession candidate"],
                "accessions": ["GSE123"],
            }
        ],
    )

    result = cli.main(["review", "--config", str(config), "--db", str(db), "--output-dir", str(output_dir)])

    assert result == 0
    assert (output_dir / "review_protocol.md").exists()
    assert (output_dir / "review_search_strategy.md").exists()
    assert (output_dir / "review_search_strategy.json").exists()
    assert (output_dir / "review_evidence_table.csv").exists()
    assert "@article{pmid1_2026_paper" in (output_dir / "review_references.bib").read_text(encoding="utf-8")
    assert "Metadata-level scoping review draft" in (output_dir / "review_draft.md").read_text(encoding="utf-8")
    assert "review_manifest.md" in (output_dir / "review_manifest.md").read_text(encoding="utf-8")
    assert (output_dir / "review_citation_audit.csv").exists()
    assert (output_dir / "review_fulltext_queue.csv").exists()
    assert (output_dir / "review_fulltext_instructions.md").exists()
    assert (output_dir / "review_quality_assessment_guidance.md").exists()
    assert (output_dir / "review_human_checkpoints.md").exists()
    assert (output_dir / "review_submission_audit.md").exists()
    assert (output_dir / "review_claim_audit.md").exists()
    assert (output_dir / "review_prisma_flow.md").exists()
    assert (output_dir / "review_prisma_flow.json").exists()
    assert (output_dir / "review_display_items.md").exists()
    assert (output_dir / "review_display_items.json").exists()
    assert (output_dir / "review_figure1_flow.mmd").exists()
    assert (output_dir / "review_figure2_theme_distribution.csv").exists()
    assert (output_dir / "review_figure2_theme_distribution.md").exists()
    assert (output_dir / "submission_manifest.md").exists()
    assert (output_dir / "review_submission_declarations.md").exists()
    assert (output_dir / "review_submission_templates.md").exists()
    assert (output_dir / "review_submission_checklist.md").exists()
    assert (output_dir / "review_prisma_checklist.md").exists()


def test_review_init_alias_writes_review_package(tmp_path):
    config = tmp_path / "topics.yaml"
    config.write_text(
        """
topics:
  - name: topic
    query: query
    core_keywords: []
""".lstrip(),
        encoding="utf-8",
    )
    db = tmp_path / "papers.sqlite"
    output_dir = tmp_path / "reports"
    upsert_papers(db, [{"pmid": "1", "title": "Paper", "score": 1, "accessions": []}])

    result = cli.main(["review-init", "--config", str(config), "--db", str(db), "--output-dir", str(output_dir)])

    assert result == 0
    assert (output_dir / "review_manifest.json").exists()


def test_review_search_coverage_command_writes_inventory(tmp_path, monkeypatch):
    config = tmp_path / "topics.yaml"
    config.write_text(
        """
topics:
  - name: topic
    query: query
    core_keywords: []
    retmax: 2
""".lstrip(),
        encoding="utf-8",
    )
    db = tmp_path / "papers.sqlite"
    output = tmp_path / "reports" / "review_search_coverage.md"
    json_output = tmp_path / "reports" / "review_search_coverage.json"
    csv_output = tmp_path / "reports" / "review_search_coverage.csv"
    upsert_papers(db, [{"pmid": "1", "title": "Frozen", "score": 1, "accessions": []}])

    def fake_search_all(query, batch_size=200, days_back=None, start_date=None, end_date=None, max_records=None):
        assert query == "query"
        assert batch_size == 2
        return PubMedSearchResult(["1", "2", "3"], raw_count=3)

    monkeypatch.setattr(cli, "search_pubmed_all_pmids", fake_search_all)

    result = cli.main(
        [
            "review-search-coverage",
            "--config",
            str(config),
            "--db",
            str(db),
            "--output",
            str(output),
            "--json",
            str(json_output),
            "--csv",
            str(csv_output),
            "--batch-size",
            "2",
        ]
    )

    assert result == 0
    summary = json.loads(json_output.read_text(encoding="utf-8"))[0]
    assert summary["unique_esearch_pmid_count"] == 3
    assert summary["frozen_snapshot_count"] == 1
    assert summary["missing_from_frozen_count"] == 2
    assert summary["frozen_not_in_current_query_count"] == 0
    assert "Review Search Coverage Inventory" in output.read_text(encoding="utf-8")
    assert "topic,1,1,yes" in csv_output.read_text(encoding="utf-8")
    assert "topic,2,2,no" in csv_output.read_text(encoding="utf-8")


def test_review_claim_audit_command_writes_report(tmp_path):
    draft = tmp_path / "review_draft.md"
    draft.write_text(
        """
# Metadata-level scoping review draft

This is metadata-level and not a completed systematic review. Human review is pending.
The snapshot contains 1 record and 1/1 citation metadata coverage. Citation audit is pending.
""".lstrip(),
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.csv"
    evidence.write_text(
        "pmid,doi,included_after_metadata_validation\n1,10.1/example,yes\n",
        encoding="utf-8",
    )
    citations = tmp_path / "citations.csv"
    citations.write_text(
        "pmid,citation_key,doi_present\n1,pmid1,yes\n",
        encoding="utf-8",
    )
    output = tmp_path / "claim_audit.md"
    json_output = tmp_path / "claim_audit.json"

    result = cli.main(
        [
            "review-claim-audit",
            "--draft",
            str(draft),
            "--evidence",
            str(evidence),
            "--citations",
            str(citations),
            "--output",
            str(output),
            "--json",
            str(json_output),
        ]
    )

    assert result == 0
    assert "Review Claim Audit" in output.read_text(encoding="utf-8")
    assert json_output.exists()


def test_review_citation_verify_command_reports_summary(tmp_path, monkeypatch):
    captured = {}

    def fake_verify(input_path, output_path, json_path, csv_path, timeout_seconds=10):
        captured.update(
            {
                "input_path": input_path,
                "output_path": output_path,
                "json_path": json_path,
                "csv_path": csv_path,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "total_records": 1,
            "verified_records": 1,
            "failed_records": 0,
            "network_error_records": 0,
        }

    monkeypatch.setattr(cli, "write_review_citation_verification", fake_verify)

    result = cli.main(
        [
            "review-citation-verify",
            "--input",
            "citations.csv",
            "--output",
            "verification.md",
            "--json",
            "verification.json",
            "--csv",
            "verification.csv",
            "--timeout",
            "2",
        ]
    )

    assert result == 0
    assert captured == {
        "input_path": "citations.csv",
        "output_path": "verification.md",
        "json_path": "verification.json",
        "csv_path": "verification.csv",
        "timeout_seconds": 2.0,
    }


def test_review_update_diff_command_reports_summary(monkeypatch):
    captured = {}

    def fake_update_diff(old_path, new_path, output_path, json_path, queue_path):
        captured.update(
            {
                "old_path": old_path,
                "new_path": new_path,
                "output_path": output_path,
                "json_path": json_path,
                "queue_path": queue_path,
            }
        )
        return {
            "added_records": 1,
            "metadata_changed_records": 2,
            "removed_records": 0,
            "needs_human_review_count": 3,
        }

    monkeypatch.setattr(cli, "write_review_update_diff", fake_update_diff)

    result = cli.main(
        [
            "review-update-diff",
            "--old",
            "old",
            "--new",
            "new",
            "--output",
            "diff.md",
            "--json",
            "diff.json",
            "--queue",
            "queue.csv",
        ]
    )

    assert result == 0
    assert captured == {
        "old_path": "old",
        "new_path": "new",
        "output_path": "diff.md",
        "json_path": "diff.json",
        "queue_path": "queue.csv",
    }


def test_validation_template_command_writes_all_ranked_records(tmp_path):
    db = tmp_path / "papers.sqlite"
    output = tmp_path / "reports" / "validation_template.csv"
    upsert_papers(
        db,
        [
            {"pmid": "1", "title": "Low", "score": 1, "accessions": []},
            {"pmid": "2", "title": "High", "score": 9, "accessions": ["GSE123"]},
        ],
    )

    result = cli.main(
        [
            "validation-template",
            "--db",
            str(db),
            "--output",
            str(output),
            "--snapshot-id",
            "snapshot-1",
        ]
    )

    assert result == 0
    text = output.read_text(encoding="utf-8")
    assert "snapshot_id,pmid,doi,title" in text
    assert "snapshot-1,2,,High" in text
    assert "snapshot-1,1,,Low" in text


def test_validation_metrics_command_writes_report(tmp_path):
    input_csv = tmp_path / "validation.csv"
    _write_validation_csv(
        input_csv,
        [
            {
                "pmid": "1",
                "rank_position": "1",
                "manual_relevant": "yes",
                "tool_accession_candidate_present": "yes",
                "manual_accession_present": "yes",
                "accession_eval_label": "TP",
            },
            {
                "pmid": "2",
                "rank_position": "2",
                "manual_relevant": "no",
                "manual_accession_present": "no",
                "accession_eval_label": "TN",
            },
        ],
    )
    output = tmp_path / "reports" / "validation_metrics.md"

    result = cli.main(["validation-metrics", "--input", str(input_csv), "--output", str(output)])

    assert result == 0
    text = output.read_text(encoding="utf-8")
    assert "Precision@10, judged rows only: 0.500 (1/2)" in text
    assert "AI-assisted validation-label coverage is complete" in text
    assert (tmp_path / "reports" / "validation_metrics.json").exists()


def test_spotcheck_summary_command_writes_report(tmp_path):
    validation_csv = tmp_path / "validation.csv"
    _write_validation_csv(
        validation_csv,
        [
            {
                "pmid": "1",
                "manual_relevant": "yes",
                "manual_topic_match": "yes",
                "manual_transcriptomics": "yes",
                "manual_rnaseq_or_scrnaseq": "scrnaseq",
                "manual_biomarker_focus": "no",
                "manual_accession_present": "no",
                "accession_match_status": "not_applicable",
                "accession_eval_label": "TN",
            }
        ],
    )
    spotcheck_csv = tmp_path / "spotcheck.csv"
    _write_spotcheck_csv(
        spotcheck_csv,
        [
            {
                "pmid": "1",
                "reviewer_relevant": "yes",
                "reviewer_topic_match": "yes",
                "reviewer_transcriptomics": "yes",
                "reviewer_rnaseq_or_scrnaseq": "scrnaseq",
                "reviewer_biomarker_focus": "no",
                "reviewer_accession_present": "no",
                "reviewer_accession_match_status": "not_applicable",
                "reviewer_accession_eval_label": "TN",
            }
        ],
    )
    output = tmp_path / "reports" / "human_spotcheck_summary.md"

    result = cli.main(
        [
            "spotcheck-summary",
            "--input",
            str(spotcheck_csv),
            "--validation",
            str(validation_csv),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    text = output.read_text(encoding="utf-8")
    assert "Completed reviewer rows: 1/1" in text
    assert "Row agreements: 1" in text
    assert (tmp_path / "reports" / "human_spotcheck_summary.json").exists()
