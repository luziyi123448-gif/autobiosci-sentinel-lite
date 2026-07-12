from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from autobiosci_sentinel.accessions import extract_accessions
from autobiosci_sentinel.config import load_topics
from autobiosci_sentinel.database import (
    accession_metadata,
    accession_papers,
    claim_next_run,
    count_papers,
    finish_run,
    has_active_runs,
    has_recent_succeeded_run,
    queue_run,
    recent_jobs,
    recent_runs,
    refresh_accession_metadata,
    top_papers,
    upsert_papers,
)
from autobiosci_sentinel.logging_utils import setup_logging
from autobiosci_sentinel.pubmed import fetch_pubmed_xml, parse_pubmed_xml, search_pubmed, search_pubmed_all_pmids
from autobiosci_sentinel.report import (
    read_spotcheck_summary,
    read_validation_metrics,
    write_review_claim_audit,
    write_review_citation_verification,
    write_review_package,
    write_review_search_coverage_inventory,
    write_review_update_diff,
    write_pipeline_outputs,
    write_report,
    write_spotcheck_summary,
    write_submission_draft,
    write_validation_metrics,
    write_validation_template,
)
from autobiosci_sentinel.scoring import score_paper

LOGGER = logging.getLogger(__name__)
LAST_SEARCH_RUN_METADATA: dict | None = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autobiosci-sentinel")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the PubMed radar pipeline")
    add_run_arguments(run_parser)
    run_parser.add_argument("--dry-run", action="store_true")

    queue_parser = subparsers.add_parser("queue", help="Queue a PubMed radar run")
    add_run_arguments(queue_parser)

    seed_windows_parser = subparsers.add_parser("seed-windows", help="Queue dated runs for each date window")
    add_seed_windows_arguments(seed_windows_parser)

    run_next_parser = subparsers.add_parser("run-next", help="Run the next queued radar job")
    run_next_parser.add_argument("--db", default="data/papers.sqlite")
    run_next_parser.add_argument("--log-level", default="INFO")

    worker_parser = subparsers.add_parser("worker", help="Run queued radar jobs")
    add_run_arguments(worker_parser)
    worker_parser.add_argument("--max-jobs", type=positive_int, default=3)
    worker_parser.add_argument("--auto", action="store_true", help="Queue one run before processing jobs")
    worker_parser.add_argument("--dedupe-window-seconds", type=non_negative_int, default=0)

    auto_parser = subparsers.add_parser(
        "auto",
        help="Queue one run and process bounded queued jobs",
        description="Queue one run and process bounded queued jobs",
    )
    add_run_arguments(auto_parser)
    auto_parser.add_argument("--max-jobs", type=positive_int, default=3)
    auto_parser.add_argument("--dedupe-window-seconds", type=non_negative_int, default=0)

    status_parser = subparsers.add_parser("status", help="Show recent jobs")
    status_parser.add_argument("--db", default="data/papers.sqlite")
    status_parser.add_argument("--limit", type=int, default=10)
    status_parser.add_argument("--log-level", default="INFO")

    accessions_parser = subparsers.add_parser("accessions", help="Refresh and list accession metadata")
    accessions_parser.add_argument("--db", default="data/papers.sqlite")
    accessions_parser.add_argument("--log-level", default="INFO")

    manuscript_parser = subparsers.add_parser("manuscript", help="Write a legacy redirect to the current review package")
    manuscript_parser.add_argument("--config", default="configs/topics.yaml")
    manuscript_parser.add_argument("--db", default="data/papers.sqlite")
    manuscript_parser.add_argument("--output", default="reports/manuscript_draft.md")
    manuscript_parser.add_argument("--validation-metrics", default="reports/validation_metrics.json")
    manuscript_parser.add_argument("--ai-spotcheck-summary", default="reports/ai_consensus_spotcheck_summary.json")
    manuscript_parser.add_argument("--spotcheck-summary", default="reports/human_spotcheck_summary.json")
    manuscript_parser.add_argument("--log-level", default="INFO")

    review_parser = subparsers.add_parser("review", help="Write a recurring review draft package")
    review_parser.add_argument("--config", default="configs/topics.yaml")
    review_parser.add_argument("--db", default="data/papers.sqlite")
    review_parser.add_argument("--output-dir", default="reports")
    review_parser.add_argument("--validation", default="reports/validation_template.csv")
    review_parser.add_argument("--validation-metrics", default="reports/validation_metrics.json")
    review_parser.add_argument("--ai-spotcheck-summary", default="reports/ai_consensus_spotcheck_summary.json")
    review_parser.add_argument("--spotcheck-summary", default="reports/human_spotcheck_summary.json")
    review_parser.add_argument("--log-level", default="INFO")

    review_init_parser = subparsers.add_parser("review-init", help="Alias for review package initialization")
    review_init_parser.add_argument("--config", default="configs/topics.yaml")
    review_init_parser.add_argument("--db", default="data/papers.sqlite")
    review_init_parser.add_argument("--output-dir", default="reports")
    review_init_parser.add_argument("--validation", default="reports/validation_template.csv")
    review_init_parser.add_argument("--validation-metrics", default="reports/validation_metrics.json")
    review_init_parser.add_argument("--ai-spotcheck-summary", default="reports/ai_consensus_spotcheck_summary.json")
    review_init_parser.add_argument("--spotcheck-summary", default="reports/human_spotcheck_summary.json")
    review_init_parser.add_argument("--log-level", default="INFO")

    search_coverage_parser = subparsers.add_parser(
        "review-search-coverage",
        help="Write a PubMed ESearch PMID coverage inventory for the frozen review snapshot",
    )
    search_coverage_parser.add_argument("--config", default="configs/topics.yaml")
    search_coverage_parser.add_argument("--db", default="data/papers.sqlite")
    search_coverage_parser.add_argument("--output", default="reports/review_search_coverage.md")
    search_coverage_parser.add_argument("--json", default="reports/review_search_coverage.json")
    search_coverage_parser.add_argument("--csv", default="reports/review_search_coverage.csv")
    search_coverage_parser.add_argument("--batch-size", type=positive_int, default=200)
    search_coverage_parser.add_argument("--max-records", type=positive_int, default=None)
    search_coverage_parser.add_argument("--start-date", default=None)
    search_coverage_parser.add_argument("--end-date", default=None)
    search_coverage_parser.add_argument("--log-level", default="INFO")

    claim_audit_parser = subparsers.add_parser("review-claim-audit", help="Audit review draft claims against evidence")
    claim_audit_parser.add_argument("--draft", default="reports/review_draft.md")
    claim_audit_parser.add_argument("--evidence", default="reports/review_evidence_table.csv")
    claim_audit_parser.add_argument("--citations", default="reports/review_citation_audit.csv")
    claim_audit_parser.add_argument("--terms", default="reports/review_forbidden_terms.yaml")
    claim_audit_parser.add_argument("--output", default="reports/review_claim_audit.md")
    claim_audit_parser.add_argument("--json", default="reports/review_claim_audit.json")
    claim_audit_parser.add_argument("--log-level", default="INFO")

    citation_verify_parser = subparsers.add_parser("review-citation-verify", help="Verify review citation DOI metadata")
    citation_verify_parser.add_argument("--input", default="reports/review_citation_audit.csv")
    citation_verify_parser.add_argument("--output", default="reports/review_citation_verification.md")
    citation_verify_parser.add_argument("--json", default="reports/review_citation_verification.json")
    citation_verify_parser.add_argument("--csv", default="reports/review_citation_verification.csv")
    citation_verify_parser.add_argument("--timeout", type=float, default=10.0)
    citation_verify_parser.add_argument("--log-level", default="INFO")

    update_diff_parser = subparsers.add_parser("review-update-diff", help="Compare two frozen review snapshots")
    update_diff_parser.add_argument("--old", default="reports")
    update_diff_parser.add_argument("--new", default="reports")
    update_diff_parser.add_argument("--output", default="reports/review_update_diff.md")
    update_diff_parser.add_argument("--json", default="reports/review_update_diff.json")
    update_diff_parser.add_argument("--queue", default="reports/human_update_queue.csv")
    update_diff_parser.add_argument("--log-level", default="INFO")

    validation_parser = subparsers.add_parser("validation-template", help="Write a validation-label CSV template")
    validation_parser.add_argument("--db", default="data/papers.sqlite")
    validation_parser.add_argument("--output", default="reports/validation_template.csv")
    validation_parser.add_argument("--snapshot-id", default="current")
    validation_parser.add_argument("--log-level", default="INFO")

    metrics_parser = subparsers.add_parser("validation-metrics", help="Write validation-label metrics")
    metrics_parser.add_argument("--input", default="reports/validation_template.csv")
    metrics_parser.add_argument("--output", default="reports/validation_metrics.md")
    metrics_parser.add_argument("--log-level", default="INFO")

    spotcheck_parser = subparsers.add_parser("spotcheck-summary", help="Compare human spot-check labels")
    spotcheck_parser.add_argument("--input", default="reports/human_spotcheck_template.csv")
    spotcheck_parser.add_argument("--validation", default="reports/validation_template.csv")
    spotcheck_parser.add_argument("--output", default="reports/human_spotcheck_summary.md")
    spotcheck_parser.add_argument("--title", default="Human Spot-check Summary")
    spotcheck_parser.add_argument("--log-level", default="INFO")

    args = parser.parse_args(argv)
    setup_logging(args.log_level)
    if args.command == "run":
        return run(args)
    if args.command == "queue":
        return queue(args)
    if args.command == "seed-windows":
        return seed_windows(args)
    if args.command == "run-next":
        return run_next(args)
    if args.command == "worker":
        return worker(args)
    if args.command == "auto":
        args.auto = True
        return worker(args)
    if args.command == "status":
        return status(args)
    if args.command == "accessions":
        return accessions(args)
    if args.command == "manuscript":
        return manuscript(args)
    if args.command in {"review", "review-init"}:
        return review(args)
    if args.command == "review-search-coverage":
        return review_search_coverage(args)
    if args.command == "review-claim-audit":
        return review_claim_audit(args)
    if args.command == "review-citation-verify":
        return review_citation_verify(args)
    if args.command == "review-update-diff":
        return review_update_diff(args)
    if args.command == "validation-template":
        return validation_template(args)
    if args.command == "validation-metrics":
        return validation_metrics_command(args)
    if args.command == "spotcheck-summary":
        return spotcheck_summary(args)
    return 2


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default="configs/topics.yaml")
    parser.add_argument("--db", default="data/papers.sqlite")
    parser.add_argument("--report", default="reports/daily_report.md")
    parser.add_argument("--retmax", type=int, default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--log-level", default="INFO")


def add_seed_windows_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default="configs/topics.yaml")
    parser.add_argument("--db", default="data/papers.sqlite")
    parser.add_argument("--report", default="reports/daily_report.md")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--window-days", type=int, required=True)
    parser.add_argument("--retmax", type=int, default=None)
    parser.add_argument("--log-level", default="INFO")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def run(args: argparse.Namespace) -> int:
    topics_count, papers = collect_papers(args.config, args.retmax, args.start_date, args.end_date)
    if args.dry_run:
        print(f"Dry run complete: fetched {len(papers)} papers from {topics_count} topics.")
        return 0

    result = write_outputs(args.db, args.report, topics_count, papers)
    print(
        f"Report written to {args.report}; fetched={result['fetched']} "
        f"new={result['new']} total={result['total']}"
    )
    return 0


def queue(args: argparse.Namespace) -> int:
    run_id = queue_run(args.db, args.config, args.report, args.retmax, args.start_date, args.end_date)
    print(f"Queued run {run_id} in {args.db}")
    return 0


def seed_windows(args: argparse.Namespace) -> int:
    windows = date_windows(args.start_date, args.end_date, args.window_days)
    queued = 0
    for start_date, end_date in windows:
        queue_run(args.db, args.config, args.report, args.retmax, start_date, end_date)
        queued += 1
    print(f"Queued {queued} run(s) in {args.db}")
    return 0


def date_windows(start_date: str, end_date: str, window_days: int) -> list[tuple[str, str]]:
    if window_days < 1:
        raise ValueError("--window-days must be at least 1")
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if end < start:
        raise ValueError("--end-date must be on or after --start-date")
    sep = "/" if "/" in start_date else "-"
    windows: list[tuple[str, str]] = []
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=window_days - 1), end)
        windows.append((_format_date(current, sep), _format_date(window_end, sep)))
        current = window_end + timedelta(days=1)
    return windows


def _parse_date(value: str) -> date:
    return date.fromisoformat(value.replace("/", "-"))


def _format_date(value: date, sep: str) -> str:
    return value.isoformat().replace("-", sep)


def run_next(args: argparse.Namespace) -> int:
    result = process_next_run(args.db)
    if result is None:
        print("No queued runs.")
        return 0
    if result["status"] == "failed":
        print(f"Queued run {result['id']} failed: {result['error']}")
        return 1
    print(
        f"Queued run {result['id']} succeeded; fetched={result['fetched']} "
        f"new={result['new']} total={result['total']}"
    )
    return 0


def _print_worker_result(worker_result: str, processed: int) -> None:
    print(json.dumps({"processed": processed, "worker_result": worker_result}, sort_keys=True))


def worker(args: argparse.Namespace) -> int:
    overlap_no_op = False
    recent_duplicate_no_op = False
    if args.auto:
        active_runs_present = has_active_runs(args.db)
        overlap_no_op = active_runs_present
        if not active_runs_present:
            recent_duplicate_no_op = has_recent_succeeded_run(
                args.db,
                args.config,
                args.report,
                retmax=args.retmax,
                start_date=args.start_date,
                end_date=args.end_date,
                window_seconds=args.dedupe_window_seconds,
            )
            if not recent_duplicate_no_op:
                run_id = queue_run(args.db, args.config, args.report, args.retmax, args.start_date, args.end_date)
                print(f"Queued run {run_id} in {args.db}")
    processed = 0
    while args.max_jobs is None or processed < args.max_jobs:
        result = process_next_run(args.db)
        if result is None:
            break
        processed += 1
        if result["status"] == "failed":
            print(f"Queued run {result['id']} failed: {result['error']}")
            _print_worker_result("failed", processed)
            return 1
    print(f"Worker processed {processed} queued run(s).")
    worker_result = "success"
    if processed == 0:
        if overlap_no_op:
            worker_result = "overlap_no_op"
        elif recent_duplicate_no_op:
            worker_result = "recent_duplicate_no_op"
        else:
            worker_result = "empty_queue_no_op"
    _print_worker_result(worker_result, processed)
    return 0


def status(args: argparse.Namespace) -> int:
    jobs = recent_jobs(args.db, args.limit)
    if not jobs:
        print("No jobs recorded.")
        return 0
    for run_row in jobs:
        print(
            f"{run_row['id']} {run_row['status']} created={run_row['created_at']} "
            f"started={run_row['started_at'] or '-'} finished={run_row['finished_at'] or '-'} "
            f"fetched={run_row['fetched_count']} new={run_row['new_count']} "
            f"total={run_row['total_count']} error={run_row['error'] or '-'}"
        )
    return 0


def accessions(args: argparse.Namespace) -> int:
    refreshed = refresh_accession_metadata(args.db)
    rows = accession_metadata(args.db)
    if not rows:
        print("No accession candidates recorded.")
        return 0
    print(f"Refreshed {refreshed} accession metadata record(s).")
    for row in rows:
        print(f"{row['accession']}\t{row['source']}\t{row['paper_count']}\t{row['url'] or '-'}")
    return 0


def manuscript(args: argparse.Namespace) -> int:
    topics_count = len(load_topics(args.config, None))
    write_submission_draft(
        args.output,
        topics_count=topics_count,
        total_count=count_papers(args.db),
        top_papers=top_papers(args.db),
        accession_papers=accession_papers(args.db),
        validation=read_validation_metrics(args.validation_metrics),
        spotcheck=read_spotcheck_summary(args.spotcheck_summary),
        ai_spotcheck=read_spotcheck_summary(args.ai_spotcheck_summary),
    )
    print(f"Legacy manuscript redirect written to {args.output}")
    return 0


def review(args: argparse.Namespace) -> int:
    topics = load_topics(args.config, None)
    outputs = write_review_package(
        args.output_dir,
        topics=topics,
        total_count=count_papers(args.db),
        papers=top_papers(args.db, limit=1_000_000),
        validation_path=args.validation,
        validation=read_validation_metrics(args.validation_metrics),
        spotcheck=read_spotcheck_summary(args.spotcheck_summary),
        ai_spotcheck=read_spotcheck_summary(args.ai_spotcheck_summary),
        config_path=args.config,
        db_path=args.db,
    )
    print(f"Review package written to {args.output_dir}; files={len(outputs)}")
    return 0


def review_search_coverage(args: argparse.Namespace) -> int:
    topics = load_topics(args.config, None)
    topic_results = []
    for topic in topics:
        pmids = search_pubmed_all_pmids(
            topic.query,
            batch_size=args.batch_size,
            days_back=topic.days_back,
            start_date=args.start_date,
            end_date=args.end_date,
            max_records=args.max_records,
        )
        topic_results.append(
            {
                "topic_id": topic.name,
                "query": topic.query,
                "retmax": topic.retmax,
                "days_back": topic.days_back,
                "raw_pubmed_hit_count": pmids.raw_count,
                "pmids": list(pmids),
            }
        )
    frozen_pmids = [str(paper.get("pmid", "")) for paper in top_papers(args.db, limit=1_000_000)]
    summary = write_review_search_coverage_inventory(
        args.output,
        args.json,
        args.csv,
        topic_results,
        frozen_pmids,
    )
    print(
        f"Review search coverage written to {args.output}; "
        f"unique_esearch_pmids={summary['unique_esearch_pmid_count']} "
        f"missing_from_frozen={summary['missing_from_frozen_count']} "
        f"frozen_not_in_current_query={summary['frozen_not_in_current_query_count']}"
    )
    return 0


def review_claim_audit(args: argparse.Namespace) -> int:
    audit = write_review_claim_audit(
        args.draft,
        args.evidence,
        args.citations,
        args.output,
        args.json,
        args.terms,
    )
    print(
        f"Review claim audit written to {args.output}; "
        f"errors={audit['error_count']} warnings={audit['warning_count']}"
    )
    return 1 if audit["error_count"] else 0


def review_citation_verify(args: argparse.Namespace) -> int:
    summary = write_review_citation_verification(
        args.input,
        args.output,
        args.json,
        args.csv,
        timeout_seconds=args.timeout,
    )
    print(
        f"Review citation verification written to {args.output}; "
        f"verified={summary['verified_records']}/{summary['total_records']} "
        f"failed={summary['failed_records']} network_errors={summary['network_error_records']}"
    )
    return 1 if summary["failed_records"] or summary["network_error_records"] else 0


def review_update_diff(args: argparse.Namespace) -> int:
    summary = write_review_update_diff(args.old, args.new, args.output, args.json, args.queue)
    print(
        f"Review update diff written to {args.output}; "
        f"added={summary['added_records']} changed={summary['metadata_changed_records']} "
        f"removed={summary['removed_records']} needs_human_review={summary['needs_human_review_count']}"
    )
    return 0


def validation_template(args: argparse.Namespace) -> int:
    papers = top_papers(args.db, limit=1_000_000)
    write_validation_template(args.output, papers, args.snapshot_id)
    print(f"Validation template written to {args.output}; records={len(papers)}")
    return 0


def validation_metrics_command(args: argparse.Namespace) -> int:
    metrics = write_validation_metrics(args.input, args.output)
    print(
        f"Validation metrics written to {args.output}; "
        f"annotated={metrics['fully_annotated_records']}/{metrics['total_records']}"
    )
    return 0


def spotcheck_summary(args: argparse.Namespace) -> int:
    summary = write_spotcheck_summary(args.input, args.validation, args.output, title=args.title)
    print(
        f"Spot-check summary written to {args.output}; "
        f"completed={summary['completed_records']}/{summary['total_records']} "
        f"disagreements={summary['disagreed_records']}"
    )
    return 0


def process_next_run(db_path: str) -> dict[str, int | str] | None:
    queued = claim_next_run(db_path)
    if queued is None:
        return None
    run_id = int(queued["id"])
    try:
        result = run_pipeline(
            queued["config_path"],
            db_path,
            queued["report_path"],
            queued["retmax"],
            queued["start_date"],
            queued["end_date"],
        )
    except Exception as exc:
        finish_run(db_path, run_id, "failed", error=str(exc))
        LOGGER.exception("Queued run failed run_id=%s", run_id)
        return {"id": run_id, "status": "failed", "error": str(exc)}
    finish_run(db_path, run_id, "succeeded", result["fetched"], result["new"], result["total"])
    return {"id": run_id, "status": "succeeded", **result}


def run_pipeline(
    config_path: str,
    db_path: str,
    report_path: str,
    retmax: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, int]:
    topics_count, papers = collect_papers(config_path, retmax, start_date, end_date)
    return write_outputs(db_path, report_path, topics_count, papers)


def collect_papers(
    config_path: str,
    retmax: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[int, list[dict]]:
    global LAST_SEARCH_RUN_METADATA
    topics = load_topics(config_path, retmax)
    papers: list[dict] = []
    searched_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    topic_metadata: list[dict] = []

    for topic in topics:
        LOGGER.info("Searching PubMed topic=%s retmax=%s days_back=%s", topic.name, topic.retmax, topic.days_back)
        pmids = search_pubmed(
            topic.query,
            topic.retmax,
            topic.days_back,
            start_date=start_date,
            end_date=end_date,
        )
        LOGGER.info("Fetched %s PMIDs for topic=%s", len(pmids), topic.name)
        xml_text = fetch_pubmed_xml(pmids)
        parsed = parse_pubmed_xml(xml_text, topic.name)
        topic_metadata.append(
            {
                "topic_id": topic.name,
                "query": " ".join(str(topic.query).split()),
                "retmax": topic.retmax,
                "days_back": topic.days_back,
                "start_date": start_date,
                "end_date": end_date,
                "source": "PubMed ESearch",
                "searched_at_utc": searched_at,
                "raw_pubmed_hit_count": getattr(pmids, "raw_count", None),
                "retrieved_pmids_count": len(pmids),
                "parsed_records_count": len(parsed),
            }
        )
        for paper in parsed:
            text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
            found_accessions = extract_accessions(text)
            score, reasons = score_paper(
                paper.get("title", ""),
                paper.get("abstract", ""),
                topic.core_keywords,
                found_accessions,
                paper.get("pub_date"),
                topic.days_back,
            )
            paper["accessions"] = found_accessions
            paper["score"] = score
            paper["score_reasons"] = reasons
        papers.extend(parsed)
    LAST_SEARCH_RUN_METADATA = {
        "schema_version": "search_run_metadata.v1",
        "generated_at_utc": searched_at,
        "source": "PubMed ESearch",
        "topics_count": len(topics),
        "total_retrieved_pmids": sum(item["retrieved_pmids_count"] for item in topic_metadata),
        "total_parsed_records": len(papers),
        "topics": topic_metadata,
    }
    return len(topics), papers


def write_outputs(db_path: str, report_path: str, topics_count: int, papers: list[dict]) -> dict[str, int]:
    global LAST_SEARCH_RUN_METADATA
    new_count = upsert_papers(db_path, papers)
    refresh_accession_metadata(db_path)
    total_count = count_papers(db_path)
    top_rows = top_papers(db_path)
    accession_rows = accession_papers(db_path)
    write_report(
        Path(report_path),
        topics_count=topics_count,
        fetched_count=len(papers),
        new_count=new_count,
        total_count=total_count,
        top_papers=top_rows,
        accession_papers=accession_rows,
    )
    write_pipeline_outputs(
        fetched_count=len(papers),
        new_count=new_count,
        total_count=total_count,
        top_papers=top_rows,
        accession_papers=accession_rows,
        accession_rows=accession_metadata(db_path),
        runs=recent_runs(db_path),
    )
    metadata = LAST_SEARCH_RUN_METADATA
    LAST_SEARCH_RUN_METADATA = None
    if (
        metadata
        and metadata.get("topics_count") == topics_count
        and metadata.get("total_parsed_records") == len(papers)
    ):
        _write_search_run_metadata(Path(report_path).parent / "search_run_metadata.json", metadata)
    return {"fetched": len(papers), "new": new_count, "total": total_count}


def _write_search_run_metadata(path: Path, metadata: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    raise SystemExit(main())
