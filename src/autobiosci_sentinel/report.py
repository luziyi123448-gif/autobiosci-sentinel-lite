from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_report(
    path: str | Path,
    topics_count: int,
    fetched_count: int,
    new_count: int,
    total_count: int,
    top_papers: list[dict[str, Any]],
    accession_papers: list[dict[str, Any]],
    generated_at: str | None = None,
) -> None:
    generated = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    lines = [
        "# AutoBioSci Sentinel Lite - Daily Report",
        "",
        f"- Generated at UTC: {generated}",
        f"- Number of topics: {topics_count}",
        f"- Number of papers fetched this run: {fetched_count}",
        f"- Number of new papers inserted: {new_count}",
        f"- Number of total papers in database: {total_count}",
        "",
        "## Top Papers",
        "",
    ]

    if not top_papers:
        lines.extend(["No papers found.", ""])
    for index, paper in enumerate(top_papers, 1):
        lines.extend(_paper_block(index, paper))

    lines.extend(["## Accession Candidates", ""])
    if not accession_papers:
        lines.extend(["No accession candidates found.", ""])
    for index, paper in enumerate(accession_papers, 1):
        accessions = _format_accessions(paper)
        lines.append(f"{index}. [{paper.get('pmid', '')}] {paper.get('title', '').strip()} - {accessions}")
    lines.append("")

    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    _write_json(report_path.with_suffix(".top_papers.json"), top_papers)
    _write_json(report_path.with_suffix(".accession_candidates.json"), accession_papers)


def write_pipeline_outputs(
    fetched_count: int,
    new_count: int,
    total_count: int,
    top_papers: list[dict[str, Any]],
    accession_papers: list[dict[str, Any]],
    accession_rows: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> None:
    accession_list = ", ".join(row["accession"] for row in accession_rows) or "None"
    _write_text(
        Path("reports/run_summary.md"),
        [
            "# Run Summary",
            "",
            f"- Papers fetched this run: {fetched_count}",
            f"- New papers inserted: {new_count}",
            f"- Total papers in database: {total_count}",
            f"- Accession candidates: {accession_list}",
            "",
            "## Top Papers",
            "",
            *_paper_summary_lines(top_papers),
        ],
    )
    _write_text(
        Path("reports/backfill_status.md"),
        [
            "# Backfill Status",
            "",
            *_run_lines(runs),
            "",
            "## Accession Snapshot",
            "",
            *_accession_row_lines(accession_rows),
        ],
    )
    _write_text(
        Path("reports/accession_candidates.md"),
        [
            "# Accession Candidates",
            "",
            *_paper_summary_lines(accession_papers),
        ],
    )
    _write_text(Path("outputs/accessions.txt"), [row["accession"] for row in accession_rows])


def write_submission_draft(
    path: str | Path,
    topics_count: int,
    total_count: int,
    top_papers: list[dict[str, Any]],
    accession_papers: list[dict[str, Any]],
    validation: dict[str, Any] | None = None,
    spotcheck: dict[str, Any] | None = None,
    ai_spotcheck: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> None:
    generated = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    lines = [
        "# Legacy Manuscript Draft Redirect",
        "",
        f"- Generated at UTC: {generated}",
        f"- Current local database snapshot: {total_count} PubMed record(s) across {topics_count} configured topic(s).",
        "- Status: legacy compatibility output only.",
        "",
        (
            "The `manuscript` command is retained for backwards compatibility with the earlier methods/tool-note "
            "workflow. It no longer writes the active submission-oriented review draft, because the current recurring "
            "review workflow has a larger human-gated package."
        ),
        "",
        "## Current Canonical Review Package",
        "",
        "- Generate the package: `python -m autobiosci_sentinel.cli review --config configs/topics.yaml --db data/papers.sqlite --output-dir reports`",
        "- Draft: `reports/review_draft.md`",
        "- Packet manifest: `reports/submission_manifest.md`",
        "- Human checkpoints: `reports/review_fulltext_queue.csv` and `reports/review_human_checkpoints.md`",
        "- Submission checklist: `reports/review_submission_checklist.md`",
        "",
        "## Boundary",
        "",
        (
            "Do not use this file as the current submission draft. This redirect does not represent completed full-text "
            "eligibility screening, final inclusion decisions, study-quality or risk-of-bias assessment, venue-specific "
            "formatting, author declarations, clinical recommendations, treatment efficacy claims, or biological discovery."
        ),
        "",
    ]
    _write_text(Path(path), lines)


VALIDATION_COLUMNS = [
    "snapshot_id",
    "pmid",
    "doi",
    "title",
    "journal",
    "publication_year",
    "rank_position",
    "tool_score",
    "manual_relevant",
    "manual_topic_match",
    "manual_transcriptomics",
    "manual_rnaseq_or_scrnaseq",
    "manual_biomarker_focus",
    "tool_accession_candidate_present",
    "tool_accession_candidates",
    "manual_accession_present",
    "manual_accessions",
    "accession_match_status",
    "accession_eval_label",
    "error_category",
    "manual_notes",
    "annotator_id",
    "annotation_date",
]

SPOTCHECK_COMPARE_FIELDS = [
    ("manual_relevant", "reviewer_relevant"),
    ("manual_topic_match", "reviewer_topic_match"),
    ("manual_transcriptomics", "reviewer_transcriptomics"),
    ("manual_rnaseq_or_scrnaseq", "reviewer_rnaseq_or_scrnaseq"),
    ("manual_biomarker_focus", "reviewer_biomarker_focus"),
    ("manual_accession_present", "reviewer_accession_present"),
    ("manual_accessions", "reviewer_accessions"),
    ("accession_match_status", "reviewer_accession_match_status"),
    ("accession_eval_label", "reviewer_accession_eval_label"),
    ("error_category", "reviewer_error_category"),
]

SPOTCHECK_REQUIRED_REVIEWER_FIELDS = [
    "reviewer_relevant",
    "reviewer_topic_match",
    "reviewer_transcriptomics",
    "reviewer_rnaseq_or_scrnaseq",
    "reviewer_biomarker_focus",
    "reviewer_accession_present",
    "reviewer_accession_match_status",
    "reviewer_accession_eval_label",
]

DEFAULT_REVIEW_RISK_TERMS = [
    "clinical utility",
    "clinically actionable",
    "mechanism",
    "proves",
    "demonstrates efficacy",
    "systematic review",
    "risk of bias",
    "PRISMA-compliant",
    "treatment recommendation",
    "causal",
]


def write_review_package(
    output_dir: str | Path,
    topics: list[Any],
    total_count: int,
    papers: list[dict[str, Any]],
    validation_path: str | Path = "reports/validation_template.csv",
    validation: dict[str, Any] | None = None,
    spotcheck: dict[str, Any] | None = None,
    ai_spotcheck: dict[str, Any] | None = None,
    generated_at: str | None = None,
    config_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, str]:
    generated = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    validation_rows = _validation_rows_by_pmid(validation_path)
    citation_verification = _citation_verification_by_pmid(out / "review_citation_verification.csv")
    ranked = list(enumerate(papers, 1))
    paths = {
        "protocol": out / "review_protocol.md",
        "records": out / "review_records_frozen.jsonl",
        "evidence": out / "review_evidence_table.csv",
        "references": out / "review_references.bib",
        "search_strategy": out / "review_search_strategy.md",
        "search_strategy_json": out / "review_search_strategy.json",
        "citation_audit": out / "review_citation_audit.csv",
        "fulltext_queue": out / "review_fulltext_queue.csv",
        "fulltext_instructions": out / "review_fulltext_instructions.md",
        "quality_guidance": out / "review_quality_assessment_guidance.md",
        "human_checkpoints": out / "review_human_checkpoints.md",
        "submission_audit": out / "review_submission_audit.md",
        "forbidden_terms": out / "review_forbidden_terms.yaml",
        "claim_audit": out / "review_claim_audit.md",
        "claim_audit_json": out / "review_claim_audit.json",
        "prisma_flow": out / "review_prisma_flow.md",
        "prisma_flow_json": out / "review_prisma_flow.json",
        "display_items": out / "review_display_items.md",
        "display_items_json": out / "review_display_items.json",
        "figure1_flow_source": out / "review_figure1_flow.mmd",
        "figure2_theme_distribution_csv": out / "review_figure2_theme_distribution.csv",
        "figure2_theme_distribution_md": out / "review_figure2_theme_distribution.md",
        "draft": out / "review_draft.md",
        "manifest": out / "review_manifest.md",
        "manifest_json": out / "review_manifest.json",
        "submission_manifest": out / "submission_manifest.md",
        "submission_declarations": out / "review_submission_declarations.md",
        "submission_templates": out / "review_submission_templates.md",
        "submission_checklist": out / "review_submission_checklist.md",
        "prisma_checklist": out / "review_prisma_checklist.md",
    }
    for name, existing_path in {
        "citation_verification": out / "review_citation_verification.md",
        "citation_verification_json": out / "review_citation_verification.json",
        "citation_verification_csv": out / "review_citation_verification.csv",
        "search_coverage_inventory": out / "review_search_coverage.md",
        "search_coverage_inventory_json": out / "review_search_coverage.json",
        "search_coverage_inventory_csv": out / "review_search_coverage.csv",
        "update_diff": out / "review_update_diff.md",
        "update_diff_json": out / "review_update_diff.json",
        "human_update_queue": out / "human_update_queue.csv",
        "search_run_metadata": out / "search_run_metadata.json",
        "ai_consensus_update": out / "review_ai_consensus_update.md",
        "ai_consensus_update_json": out / "review_ai_consensus_update.json",
    }.items():
        if existing_path.exists():
            paths[name] = existing_path

    _write_review_protocol(paths["protocol"], topics, generated)
    _write_review_records_jsonl(paths["records"], ranked, validation_rows)
    _write_review_evidence_table(paths["evidence"], ranked, validation_rows, citation_verification)
    _write_review_references(paths["references"], papers)
    _write_review_citation_audit(paths["citation_audit"], papers)
    _write_review_fulltext_queue(paths["fulltext_queue"], ranked, validation_rows)
    _write_review_search_strategy(
        paths["search_strategy"],
        paths["search_strategy_json"],
        topics,
        total_count,
        validation_rows,
        generated,
        config_path,
        db_path,
    )
    _write_review_fulltext_instructions(paths["fulltext_instructions"])
    _write_quality_assessment_guidance(paths["quality_guidance"])
    _write_review_human_checkpoints(paths["human_checkpoints"])
    _write_prisma_flow(paths["prisma_flow"], paths["prisma_flow_json"], topics, total_count, ranked, validation_rows, generated)
    _write_review_display_items(paths["display_items"], paths["display_items_json"], generated)
    _write_review_display_sources(
        paths["figure1_flow_source"],
        paths["figure2_theme_distribution_csv"],
        paths["figure2_theme_distribution_md"],
        generated,
    )
    _write_review_submission_audit(paths["submission_audit"], papers, validation, spotcheck, ai_spotcheck)
    _write_review_forbidden_terms(paths["forbidden_terms"])
    _write_review_draft(paths["draft"], topics, total_count, ranked, validation_rows, validation, spotcheck, ai_spotcheck, generated)
    write_review_claim_audit(
        paths["draft"],
        paths["evidence"],
        paths["citation_audit"],
        paths["claim_audit"],
        paths["claim_audit_json"],
        paths["forbidden_terms"],
    )
    _write_review_manifest(paths["manifest"], paths, validation, spotcheck, ai_spotcheck, generated)
    _write_json(
        paths["manifest_json"],
        [
            {
                "generated_at": generated,
                "files": {name: str(path) for name, path in paths.items()},
                "citation_verification": _citation_verification_summary(out / "review_citation_verification.json"),
                "periodic_update": _review_update_summary(out / "review_update_diff.json"),
                "fulltext_quality_queue": _fulltext_queue_summary(out / "review_fulltext_queue.csv"),
                "search_strategy": _search_strategy_status(out / "review_search_strategy.json", total_count),
                "search_coverage_inventory": _search_inventory_status(out / "review_search_coverage.json"),
            }
        ],
    )
    _write_submission_declarations(paths["submission_declarations"], generated)
    _write_submission_templates(paths["submission_templates"], generated)
    _write_submission_checklist(paths["submission_checklist"], paths, validation, spotcheck, ai_spotcheck, generated)
    _write_prisma_checklist(paths["prisma_checklist"], validation, spotcheck, ai_spotcheck, generated)
    _write_submission_manifest(paths["submission_manifest"], paths, topics, validation, spotcheck, ai_spotcheck, generated)
    return {name: str(path) for name, path in paths.items()}


def write_review_update_diff(
    old_path: str | Path,
    new_path: str | Path,
    output_path: str | Path,
    json_path: str | Path,
    queue_path: str | Path,
) -> dict[str, Any]:
    self_comparison = Path(old_path).resolve() == Path(new_path).resolve()
    old_records = _read_review_records_jsonl(old_path)
    new_records = _read_review_records_jsonl(new_path)
    old_by_pmid = {str(record.get("pmid", "")): record for record in old_records if record.get("pmid")}
    new_by_pmid = {str(record.get("pmid", "")): record for record in new_records if record.get("pmid")}
    changes: list[dict[str, Any]] = []

    for pmid in sorted(new_by_pmid, key=lambda item: int(item) if item.isdigit() else item):
        new_record = new_by_pmid[pmid]
        old_record = old_by_pmid.get(pmid)
        if old_record is None:
            changes.append(_review_update_change(pmid, "added", None, new_record, ["new PMID"], True))
            continue
        reasons = _record_metadata_changes(old_record, new_record)
        if reasons:
            changes.append(_review_update_change(pmid, "metadata_changed", old_record, new_record, reasons, True))
        else:
            changes.append(_review_update_change(pmid, "unchanged", old_record, new_record, [], False))

    for pmid in sorted(set(old_by_pmid) - set(new_by_pmid), key=lambda item: int(item) if item.isdigit() else item):
        changes.append(_review_update_change(pmid, "removed", old_by_pmid[pmid], None, ["missing from new snapshot"], False))

    summary = {
        "previous_snapshot_id": _snapshot_id_for_path(old_path),
        "current_snapshot_id": _snapshot_id_for_path(new_path),
        "self_comparison": self_comparison,
        "old_records": len(old_by_pmid),
        "new_records": len(new_by_pmid),
        "added_records": sum(1 for item in changes if item["status"] == "added"),
        "removed_records": sum(1 for item in changes if item["status"] == "removed"),
        "unchanged_records": sum(1 for item in changes if item["status"] == "unchanged"),
        "metadata_changed_records": sum(1 for item in changes if item["status"] == "metadata_changed"),
        "labels_carried_forward_count": sum(
            1 for item in changes if item["status"] == "unchanged" and item.get("previous_validation_present") == "yes"
        ),
        "needs_human_review_count": sum(1 for item in changes if item["needs_reannotation"] == "yes"),
        "human_update_queue_count": sum(1 for item in changes if item["needs_reannotation"] == "yes"),
        "update_diff_file": str(output_path),
        "human_update_queue_file": str(queue_path),
        "changes": changes,
    }
    _write_text(Path(output_path), _review_update_diff_lines(summary))
    _write_json(Path(json_path), [summary])
    _write_human_update_queue(queue_path, changes)
    return summary


def write_review_search_coverage_inventory(
    output_path: str | Path,
    json_path: str | Path,
    csv_path: str | Path,
    topic_results: list[dict[str, Any]],
    frozen_pmids: list[str] | set[str],
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    frozen = {str(pmid) for pmid in frozen_pmids if str(pmid).strip()}
    unique_pmids: list[str] = []
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    topics: list[dict[str, Any]] = []
    raw_counts: list[int] = []

    for result in topic_results:
        topic_id = str(result.get("topic_id", "")).strip() or "topic"
        pmids = [str(pmid) for pmid in result.get("pmids", []) if str(pmid).strip()]
        raw_count = _int_or_none(result.get("raw_pubmed_hit_count"))
        if raw_count is not None:
            raw_counts.append(raw_count)
        topics.append(
            {
                "topic_id": topic_id,
                "exact_pubmed_query": " ".join(str(result.get("query", "")).split()),
                "query_sha256": _sha256_text(str(result.get("query", ""))),
                "days_back": _int_or_none(result.get("days_back")),
                "retmax": _int_or_none(result.get("retmax")),
                "raw_pubmed_hit_count": raw_count,
                "esearch_pmids_retrieved": len(pmids),
            }
        )
        for rank, pmid in enumerate(pmids, 1):
            if pmid not in seen:
                seen.add(pmid)
                unique_pmids.append(pmid)
            rows.append(
                {
                    "topic_id": topic_id,
                    "rank": str(rank),
                    "pmid": pmid,
                    "in_frozen_snapshot": "yes" if pmid in frozen else "no",
                }
            )

    esearch_set = set(unique_pmids)
    missing_from_frozen = sorted(esearch_set - frozen, key=_pmid_sort_key)
    frozen_not_in_query = sorted(frozen - esearch_set, key=_pmid_sort_key)
    raw_total = sum(raw_counts) if len(raw_counts) == len(topic_results) else None
    retrieval_complete = raw_total is not None and raw_total == len(unique_pmids)
    status = "pass" if retrieval_complete and not missing_from_frozen and not frozen_not_in_query else "warn"
    label = (
        f"{status.upper()}: inventoried {len(unique_pmids)} unique ESearch PMID(s); "
        f"{len(missing_from_frozen)} missing from frozen snapshot; "
        f"{len(frozen_not_in_query)} frozen snapshot PMID(s) not in current query inventory"
    )
    boundary = (
        "This inventory is PMID-only PubMed ESearch coverage accounting. It does not import metadata, "
        "does not update SQLite, does not validate records, and does not establish a completed systematic review corpus."
    )
    summary = {
        "schema_version": "review_search_coverage.v1",
        "generated_at_utc": generated,
        "source": "PubMed ESearch PMID inventory",
        "topics": topics,
        "raw_pubmed_hit_count_total": raw_total,
        "unique_esearch_pmids": unique_pmids,
        "unique_esearch_pmid_count": len(unique_pmids),
        "frozen_snapshot_count": len(frozen),
        "overlap_count": len(esearch_set & frozen),
        "missing_from_frozen_count": len(missing_from_frozen),
        "missing_from_frozen_pmids": missing_from_frozen,
        "frozen_not_in_current_query_count": len(frozen_not_in_query),
        "frozen_not_in_current_query_pmids": frozen_not_in_query,
        "retrieval_complete": retrieval_complete,
        "coverage_status": status,
        "label": label,
        "boundary_statement": boundary,
    }

    output = Path(output_path)
    json_output = Path(json_path)
    csv_output = Path(csv_path)
    for target in (output, json_output, csv_output):
        target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(json_output, [summary])
    with csv_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["topic_id", "rank", "pmid", "in_frozen_snapshot"])
        writer.writeheader()
        writer.writerows(rows)
    _write_text(
        output,
        [
            "# Review Search Coverage Inventory",
            "",
            f"- Generated at UTC: {generated}",
            f"- Status: {label}",
            f"- Boundary: {boundary}",
            "",
            "## Summary",
            "",
            "| Count | Value |",
            "| --- | ---: |",
            f"| Raw PubMed hit count total | {raw_total if raw_total is not None else 'not available'} |",
            f"| Unique ESearch PMIDs inventoried | {len(unique_pmids)} |",
            f"| Frozen snapshot PMIDs | {len(frozen)} |",
            f"| ESearch PMIDs already in frozen snapshot | {len(esearch_set & frozen)} |",
            f"| ESearch PMIDs missing from frozen snapshot | {len(missing_from_frozen)} |",
            f"| Frozen snapshot PMIDs not in current query inventory | {len(frozen_not_in_query)} |",
            "",
            "## Topic Runs",
            "",
            "| Topic | Raw hits | ESearch PMIDs inventoried | Query SHA-256 |",
            "| --- | ---: | ---: | --- |",
            *[
                f"| {_table_cell(topic['topic_id'])} | {topic['raw_pubmed_hit_count'] if topic['raw_pubmed_hit_count'] is not None else 'not available'} | {topic['esearch_pmids_retrieved']} | `{topic['query_sha256']}` |"
                for topic in topics
            ],
            "",
            "## Files",
            "",
            f"- Full PMID inventory CSV: `{csv_output.as_posix()}`",
            f"- Machine-readable summary JSON: `{json_output.as_posix()}`",
            "",
            "The CSV contains one row per topic PMID and flags whether that PMID is present in the frozen SQLite snapshot.",
        ],
    )
    return summary


def write_validation_template(path: str | Path, papers: list[dict[str, Any]], snapshot_id: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=VALIDATION_COLUMNS)
        writer.writeheader()
        for rank, paper in enumerate(papers, 1):
            accessions = paper.get("accessions") or []
            writer.writerow(
                {
                    "snapshot_id": snapshot_id,
                    "pmid": paper.get("pmid", ""),
                    "doi": paper.get("doi", ""),
                    "title": paper.get("title", ""),
                    "journal": paper.get("journal", ""),
                    "publication_year": _publication_year(paper.get("pub_date", "")),
                    "rank_position": rank,
                    "tool_score": paper.get("score", 0),
                    "manual_relevant": "",
                    "manual_topic_match": "",
                    "manual_transcriptomics": "",
                    "manual_rnaseq_or_scrnaseq": "",
                    "manual_biomarker_focus": "",
                    "tool_accession_candidate_present": "yes" if accessions else "no",
                    "tool_accession_candidates": ";".join(accessions),
                    "manual_accession_present": "",
                    "manual_accessions": "",
                    "accession_match_status": "",
                    "accession_eval_label": "",
                    "error_category": "",
                    "manual_notes": "",
                    "annotator_id": "",
                    "annotation_date": "",
                }
            )


def write_validation_metrics(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    rows = _read_validation_rows(input_path)
    metrics = validation_metrics(rows)
    precision_label, relevance_label, accession_precision_label, accession_recall_label = _validation_metric_labels(metrics)
    lines = [
        "# Validation Label Metrics",
        "",
        f"- Total records: {metrics['total_records']}",
        f"- Fully annotated records: {metrics['fully_annotated_records']}",
        f"- Pending records: {metrics['pending_records']}",
        f"- Unclear relevance records: {metrics['unclear_relevance_records']}",
        f"- Judged top-10 records: {metrics['top10_coverage']['judged']}/10",
        f"- Blank top-10 records: {metrics['top10_coverage']['blank']}",
        "",
        "## Relevance",
        "",
        f"- {precision_label}: {_format_ratio(metrics['precision_at_10'])}",
        f"- {relevance_label}: {_format_ratio(metrics['overall_relevance_precision'])}",
        "",
        "## Accession Extraction",
        "",
        f"- {accession_precision_label}: {_format_ratio(metrics['accession_candidate_precision'])}",
        f"- {accession_recall_label}: {_format_ratio(metrics['accession_recall'])}",
        f"- TP: {metrics['accession_counts']['TP']}",
        f"- FP: {metrics['accession_counts']['FP']}",
        f"- TN: {metrics['accession_counts']['TN']}",
        f"- FN: {metrics['accession_counts']['FN']}",
        f"- Unclear: {metrics['accession_counts']['unclear']}",
        "",
        "Blank validation labels and `unclear` values are excluded from precision and recall denominators and reported as pending or unclear.",
        "Accession metrics are record-level and limited to accessions visible in cached PubMed evidence.",
        "",
        "## Validation Audit",
        "",
        f"- Issues: {metrics['audit']['issue_count']}",
        *_audit_issue_lines(metrics["audit"]["issues"]),
        "",
        "## Status",
        "",
        metrics["status"],
        "",
    ]
    output = Path(output_path)
    _write_text(output, lines)
    _write_json(output.with_suffix(".json"), [metrics])
    return metrics


def read_validation_metrics(path: str | Path) -> dict[str, Any] | None:
    metrics_path = Path(path)
    if not metrics_path.exists():
        return None
    rows = json.loads(metrics_path.read_text(encoding="utf-8"))
    if not rows:
        return None
    return rows[0]


def read_spotcheck_summary(path: str | Path) -> dict[str, Any] | None:
    summary_path = Path(path)
    if not summary_path.exists():
        return None
    rows = json.loads(summary_path.read_text(encoding="utf-8"))
    if not rows:
        return None
    return rows[0]


def _validation_rows_by_pmid(path: str | Path) -> dict[str, dict[str, str]]:
    validation_path = Path(path)
    if not validation_path.exists():
        return {}
    return {row["pmid"]: row for row in _read_validation_rows(validation_path)}


def _citation_verification_by_pmid(path: str | Path) -> dict[str, dict[str, str]]:
    verification_path = Path(path)
    if not verification_path.exists():
        return {}
    return {row.get("pmid", ""): row for row in _read_csv_rows(verification_path)}


def _review_prisma_flow_summary(path: str | Path) -> dict[str, Any] | None:
    flow_path = Path(path)
    if not flow_path.exists():
        return None
    rows = json.loads(flow_path.read_text(encoding="utf-8"))
    return rows[0] if rows else None


def _write_review_protocol(path: Path, topics: list[Any], generated: str) -> None:
    lines = [
        "# Recurring Review Protocol",
        "",
        f"- Generated at UTC: {generated}",
        "- Review type: living scoping review draft from a frozen PubMed metadata snapshot",
        "- Evidence boundary: PubMed title/abstract metadata, DOI, journal, publication date, cached accessions, and local validation labels",
        "- Claim boundary: submission-draft support only; not a completed systematic review, meta-analysis, clinical recommendation, or full-text adjudication",
        "",
        "## Topic Freeze",
        "",
        "| Topic | PubMed query | Core keywords |",
        "| --- | --- | --- |",
        *[
            (
                f"| {_table_cell(topic.name)} | {_table_cell(' '.join(str(topic.query).split()))} | "
                f"{_table_cell(', '.join(topic.core_keywords))} |"
            )
            for topic in topics
        ],
        "",
        "## Minimum Inclusion Criteria",
        "",
        "- Matches the frozen topic query and cached PubMed metadata.",
        "- Has title or abstract evidence for cancer immunotherapy, checkpoint inhibition, tumor microenvironment, transcriptomics, RNA-seq, single-cell RNA-seq, spatial transcriptomics, biomarker, response, prognosis, or related immune-contexture work.",
        "- Is retained in the frozen SQLite snapshot and can be traced by PMID.",
        "",
        "## Minimum Exclusion Criteria",
        "",
        "- Off-topic cancer, non-transcriptomics, non-biomedical, duplicate, or metadata-insufficient records.",
        "- Records requiring full text, supplements, dataset downloads, or clinical judgment are flagged for human review instead of silently included as confirmed evidence.",
        "",
        "## Review Checkpoints",
        "",
        "- AI consensus can check mechanical metadata labels, inclusion labels, accession visibility, citation-key consistency, and table completeness.",
        "- Human or venue-dependent review is still required for final claim wording, full-text eligibility, risk-of-bias assessment, clinical interpretation, target-journal formatting, and any statement that implies independent human systematic-review adjudication.",
        "",
    ]
    _write_text(path, lines)


def _write_review_search_strategy(
    path: Path,
    json_path: Path,
    topics: list[Any],
    total_count: int,
    validation_rows: dict[str, dict[str, str]],
    generated: str,
    config_path: str | Path | None,
    db_path: str | Path | None,
) -> None:
    summary = _search_strategy_summary(path.parent, topics, total_count, validation_rows, generated, config_path, db_path)
    _write_json(json_path, [summary])
    raw_count_boundary = (
        "Stored from PubMed ESearch in `reports/search_run_metadata.json`."
        if summary["raw_count_available"]
        else "Raw ESearch hit count is not stored in the current frozen review package."
    )
    raw_records_boundary = (
        "PMIDs returned by PubMed ESearch under the configured retmax."
        if summary["raw_count_available"]
        else "Do not infer or invent this value."
    )
    raw_boundary_line = (
        "- Raw PubMed hit count is stored from the latest collector run in `reports/search_run_metadata.json`."
        if summary["raw_count_available"]
        else "- Raw PubMed hit count and pre-deduplication counts are unavailable unless a future collector stores them explicitly."
    )
    coverage = summary["search_coverage_gate"]
    lines = [
        "# Review Search Strategy",
        "",
        f"Generated at UTC: {generated}. This is a dedicated PubMed-only metadata-level search strategy record for the frozen recurring review package.",
        "",
        "## Source and Scope",
        "",
        f"- Topic id(s): {summary['topic_id']}",
        f"- Snapshot id: {summary['snapshot_id']}",
        "- Database: PubMed",
        "- Search interface: PubMed/NCBI E-utilities for collection; local SQLite snapshot for package generation",
        f"- Config file: `{summary['config_file']}`",
        f"- Config SHA-256: {summary['config_sha256'] or 'not available'}",
        f"- Database file: `{summary['db_file']}`",
        f"- Database SHA-256: {summary['db_sha256'] or 'not available'}",
        "",
        "## Frozen Query Settings",
        "",
        "| Topic | Exact PubMed query | Query SHA-256 | retmax | days_back | Core keywords |",
        "| --- | --- | --- | ---: | ---: | --- |",
        *[
            (
                f"| {_table_cell(item['topic_id'])} | {_table_cell(item['exact_pubmed_query'])} | "
                f"`{item['query_sha256']}` | {item['retmax'] if item['retmax'] is not None else 'not recorded'} | "
                f"{item['days_back'] if item['days_back'] is not None else 'not recorded'} | "
                f"{_table_cell(', '.join(item['core_keywords']))} |"
            )
            for item in summary["topic_queries"]
        ],
        "",
        "## Snapshot Counts",
        "",
        "| Count field | Value | Boundary |",
        "| --- | ---: | --- |",
        f"| Raw PubMed hit count available | {str(summary['raw_count_available']).lower()} | {raw_count_boundary} |",
        f"| Raw PubMed hit count | {summary['raw_pubmed_hit_count'] if summary['raw_pubmed_hit_count'] is not None else 'not stored'} | PubMed ESearch count before retmax truncation. |",
        f"| Raw records retrieved | {summary['records_retrieved_raw'] if summary['records_retrieved_raw'] is not None else 'not stored'} | {raw_records_boundary} |",
        f"| Retrieval truncated or partial | {str(coverage['retrieval_truncated_or_partial']).lower()} | {coverage['label']} |",
        f"| Frozen snapshot records beyond latest retrieved PMID count | {coverage['frozen_snapshot_records_beyond_latest_retrieval_count']} | Retained SQLite corpus records not counted as latest ESearch retrieval. |",
        f"| Duplicates removed by PMID | {summary['duplicates_removed_by_pmid'] if summary['duplicates_removed_by_pmid'] is not None else 'not stored'} | The package starts from a PMID-deduplicated SQLite snapshot. |",
        f"| Deduplicated records | {summary['deduplicated_records']} | Frozen SQLite PMID snapshot. |",
        f"| Records in frozen snapshot | {summary['records_in_frozen_snapshot']} | Same boundary as deduplicated records for this package. |",
        f"| Validation annotated | {summary['validation_annotated']} | Local metadata-level validation labels. |",
        f"| Metadata relevant | {summary['metadata_relevant']} | `manual_relevant=yes`; not final included studies. |",
        f"| Metadata irrelevant | {summary['metadata_irrelevant']} | `manual_relevant=no`; not final full-text exclusions. |",
        f"| Full-text queue records | {summary['fulltext_queue_records']} | Human review pending. |",
        "",
        "## Reproducible Commands",
        "",
        "```bash",
        summary["collection_command"],
        summary["review_command"],
        "```",
        "",
        "## Boundary Statement",
        "",
        "- This is a PubMed-only search strategy record, not a multi-database systematic-review strategy.",
        "- The search strategy has not been librarian peer-reviewed.",
        "- The workflow is title/abstract metadata-level until the full-text queue is completed by a human reviewer.",
        "- Deduplication is by PMID only in the local SQLite snapshot.",
        raw_boundary_line,
        f"- {coverage['boundary_statement']}",
        "- This file does not establish PRISMA compliance and does not complete full-text eligibility screening.",
        "",
    ]
    _write_text(path, lines)


def _search_strategy_summary(
    output_dir: Path,
    topics: list[Any],
    total_count: int,
    validation_rows: dict[str, dict[str, str]],
    generated: str,
    config_path: str | Path | None,
    db_path: str | Path | None,
) -> dict[str, Any]:
    search_metadata = _read_search_run_metadata(output_dir / "search_run_metadata.json")
    metadata_by_topic = _search_metadata_by_topic(search_metadata)
    topic_queries = []
    for topic in topics:
        exact_query = " ".join(str(topic.query).split())
        topic_search = metadata_by_topic.get(str(topic.name), {})
        topic_queries.append(
            {
                "topic_id": str(topic.name),
                "exact_pubmed_query": exact_query,
                "query_sha256": _sha256_text(exact_query),
                "retmax": getattr(topic, "retmax", None),
                "days_back": getattr(topic, "days_back", None),
                "core_keywords": list(getattr(topic, "core_keywords", []) or []),
                "raw_pubmed_hit_count": _int_or_none(topic_search.get("raw_pubmed_hit_count")),
                "retrieved_pmids_count": _int_or_none(topic_search.get("retrieved_pmids_count")),
                "searched_at_utc": topic_search.get("searched_at_utc") or search_metadata.get("generated_at_utc"),
            }
        )
    exact_pubmed_query = " ; ".join(item["exact_pubmed_query"] for item in topic_queries)
    relevance_rows = [row for row in validation_rows.values() if _clean(row.get("manual_relevant")) in {"yes", "no", "unclear"}]
    snapshot_ids = sorted(
        {str(row.get("snapshot_id", "")).strip() for row in validation_rows.values() if str(row.get("snapshot_id", "")).strip()}
    )
    fulltext_rows = _read_csv_rows(output_dir / "review_fulltext_queue.csv")
    config_file = str(config_path) if config_path is not None else "not recorded"
    db_file = str(db_path) if db_path is not None else "not recorded"
    raw_counts = [item["raw_pubmed_hit_count"] for item in topic_queries if item["raw_pubmed_hit_count"] is not None]
    retrieved_counts = [item["retrieved_pmids_count"] for item in topic_queries if item["retrieved_pmids_count"] is not None]
    raw_count_available = bool(topic_queries) and len(raw_counts) == len(topic_queries)
    raw_hit_count = sum(raw_counts) if raw_count_available else None
    retrieved_raw = sum(retrieved_counts) if raw_count_available and len(retrieved_counts) == len(topic_queries) else None
    search_coverage_gate = _search_coverage_gate(raw_hit_count, retrieved_raw, total_count)
    return {
        "schema_version": "review_search_strategy.v1",
        "generated_at_utc": generated,
        "topic_id": ", ".join(item["topic_id"] for item in topic_queries) or "not recorded",
        "snapshot_id": ", ".join(snapshot_ids) or "not recorded",
        "database": "PubMed",
        "source_database": "PubMed only",
        "search_source": "PubMed/NCBI E-utilities for collection; local SQLite frozen snapshot for review-package generation",
        "exact_pubmed_query": exact_pubmed_query,
        "query_sha256": _sha256_text(exact_pubmed_query),
        "topic_queries": topic_queries,
        "config_file": config_file,
        "config_sha256": _file_sha256(config_path),
        "db_file": db_file,
        "db_sha256": _file_sha256(db_path),
        "retmax": ", ".join(str(item["retmax"]) for item in topic_queries if item["retmax"] is not None) or None,
        "days_back": ", ".join(str(item["days_back"]) for item in topic_queries if item["days_back"] is not None) or None,
        "search_date_or_window": search_metadata.get("generated_at_utc")
        or "Configured rolling PubMed window; exact ESearch execution timestamp is not stored in the review package.",
        "raw_pubmed_hit_count": raw_hit_count,
        "records_retrieved_raw": retrieved_raw,
        "raw_count_available": raw_count_available,
        "search_coverage_gate": search_coverage_gate,
        "search_run_metadata_file": "reports/search_run_metadata.json" if search_metadata else None,
        "duplicates_removed_by_pmid": None,
        "deduplicated_records": total_count,
        "records_in_frozen_snapshot": total_count,
        "validation_annotated": len(relevance_rows),
        "metadata_relevant": sum(1 for row in relevance_rows if _clean(row.get("manual_relevant")) == "yes"),
        "metadata_irrelevant": sum(1 for row in relevance_rows if _clean(row.get("manual_relevant")) == "no"),
        "metadata_unclear": sum(1 for row in relevance_rows if _clean(row.get("manual_relevant")) == "unclear"),
        "fulltext_queue_records": len(fulltext_rows),
        "librarian_peer_reviewed": False,
        "deduplication_key": "PMID",
        "collection_command": "python -m autobiosci_sentinel.cli worker --auto --config configs/topics.yaml --db data/papers.sqlite --report reports/daily_report.md --max-jobs 3",
        "review_command": "python -m autobiosci_sentinel.cli review --config configs/topics.yaml --db data/papers.sqlite --output-dir reports",
        "boundaries": [
            "PubMed-only",
            "metadata/title/abstract-level",
            "not multi-database",
            "not librarian peer-reviewed",
            "not full-text eligibility screening",
            "not a completed systematic review",
            (
                "raw-hit counts stored from latest PubMed ESearch run; not librarian peer-reviewed"
                if raw_count_available
                else "raw-hit counts unavailable unless stored by a future collector"
            ),
            search_coverage_gate["boundary_statement"],
            "PMID-only deduplication",
        ],
    }


def _search_coverage_gate(
    raw_pubmed_hit_count: int | None,
    latest_retrieved_pmids: int | None,
    frozen_snapshot_records: int,
) -> dict[str, Any]:
    beyond_latest = max(frozen_snapshot_records - (latest_retrieved_pmids or 0), 0)
    if raw_pubmed_hit_count is None or latest_retrieved_pmids is None:
        return {
            "status": "unknown",
            "label": "WARN: raw PubMed hit count or latest retrieval count is unavailable",
            "retrieval_truncated_or_partial": True,
            "raw_pubmed_hit_count": raw_pubmed_hit_count,
            "latest_retrieved_pmids": latest_retrieved_pmids,
            "frozen_snapshot_records": frozen_snapshot_records,
            "frozen_snapshot_records_beyond_latest_retrieval_count": beyond_latest,
            "boundary_statement": "The frozen SQLite snapshot cannot be treated as an exhaustive PubMed query corpus because latest retrieval coverage is not fully documented.",
        }
    partial = raw_pubmed_hit_count > latest_retrieved_pmids
    status = "warn" if partial else "pass"
    label = (
        f"WARN: latest retrieval captured {latest_retrieved_pmids}/{raw_pubmed_hit_count} PubMed hit(s) under retmax"
        if partial
        else f"PASS: latest retrieval count covers raw PubMed hit count ({latest_retrieved_pmids}/{raw_pubmed_hit_count})"
    )
    boundary = (
        "The frozen SQLite snapshot represents a retained surveillance corpus under the configured retrieval limit, not an exhaustive PubMed result set for the query."
        if partial
        else "The latest PubMed retrieval was not truncated relative to the raw ESearch hit count."
    )
    return {
        "status": status,
        "label": label,
        "retrieval_truncated_or_partial": partial,
        "raw_pubmed_hit_count": raw_pubmed_hit_count,
        "latest_retrieved_pmids": latest_retrieved_pmids,
        "frozen_snapshot_records": frozen_snapshot_records,
        "frozen_snapshot_records_beyond_latest_retrieval_count": beyond_latest,
        "boundary_statement": boundary,
    }


def _read_search_run_metadata(path: str | Path) -> dict[str, Any]:
    metadata_path = Path(path)
    if not metadata_path.exists():
        return {}
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, list):
        data = data[0] if data else {}
    return data if isinstance(data, dict) else {}


def _search_metadata_by_topic(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = metadata.get("topics") or []
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("topic_id", "")): row
        for row in rows
        if isinstance(row, dict) and str(row.get("topic_id", "")).strip()
    }


def _search_metadata_counts(metadata: dict[str, Any], topics: list[Any]) -> tuple[int | None, int | None]:
    by_topic = _search_metadata_by_topic(metadata)
    raw_counts: list[int] = []
    retrieved_counts: list[int] = []
    for topic in topics:
        row = by_topic.get(str(topic.name), {})
        raw_count = _int_or_none(row.get("raw_pubmed_hit_count"))
        retrieved_count = _int_or_none(row.get("retrieved_pmids_count"))
        if raw_count is None or retrieved_count is None:
            return None, None
        raw_counts.append(raw_count)
        retrieved_counts.append(retrieved_count)
    if not topics:
        return None, None
    return sum(raw_counts), sum(retrieved_counts)


def _write_review_evidence_table(
    path: Path,
    ranked: list[tuple[int, dict[str, Any]]],
    validation_rows: dict[str, dict[str, str]],
    citation_verification: dict[str, dict[str, str]] | None = None,
) -> None:
    columns = [
        "rank_position",
        "snapshot_id",
        "pmid",
        "citation_key",
        "doi",
        "title",
        "journal",
        "publication_year",
        "tool_score",
        "manual_relevant",
        "included_after_metadata_validation",
        "requires_full_text_check",
        "citation_verified",
        "manual_include",
        "exclusion_reason",
        "manual_topic_match",
        "manual_transcriptomics",
        "manual_rnaseq_or_scrnaseq",
        "review_theme",
        "metadata_cancer_type_hint",
        "metadata_immunotherapy_context_hint",
        "metadata_assay_type_hint",
        "cancer_type",
        "immunotherapy_context",
        "assay_type",
        "bulk_rnaseq_or_scrnaseq",
        "manual_biomarker_focus",
        "dataset_accession_visible",
        "accession_ids",
        "tool_accession_candidates",
        "manual_accession_present",
        "manual_accessions",
        "accession_eval_label",
        "key_finding_metadata_level",
        "evidence_note",
        "limitations_note",
        "human_verified",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for rank, paper in ranked:
            pmid = str(paper.get("pmid", ""))
            validation = validation_rows.get(pmid, {})
            citation_status = (citation_verification or {}).get(pmid, {}).get("status", "")
            citation_verified = (
                "yes"
                if citation_status == "verified"
                else "pubmed_unresolved"
                if citation_status == "pubmed_verified_unresolved"
                else "no"
                if citation_status
                else "pending"
            )
            writer.writerow(
                {
                    "rank_position": rank,
                    "snapshot_id": validation.get("snapshot_id", ""),
                    "pmid": pmid,
                    "citation_key": _citation_key(paper),
                    "doi": paper.get("doi", ""),
                    "title": paper.get("title", ""),
                    "journal": paper.get("journal", ""),
                    "publication_year": _publication_year(paper.get("pub_date", "")),
                    "tool_score": paper.get("score", 0),
                    "manual_relevant": validation.get("manual_relevant", ""),
                    "included_after_metadata_validation": "no" if _clean(validation.get("manual_relevant")) == "no" else "yes",
                    "requires_full_text_check": "yes",
                    "citation_verified": citation_verified,
                    "manual_include": "",
                    "exclusion_reason": "",
                    "manual_topic_match": validation.get("manual_topic_match", ""),
                    "manual_transcriptomics": validation.get("manual_transcriptomics", ""),
                    "manual_rnaseq_or_scrnaseq": validation.get("manual_rnaseq_or_scrnaseq", ""),
                    "review_theme": _review_theme_label(paper),
                    "metadata_cancer_type_hint": _cancer_type_hint(paper),
                    "metadata_immunotherapy_context_hint": _immunotherapy_context_hint(paper),
                    "metadata_assay_type_hint": _assay_type_hint(paper),
                    "cancer_type": "",
                    "immunotherapy_context": "",
                    "assay_type": "",
                    "bulk_rnaseq_or_scrnaseq": validation.get("manual_rnaseq_or_scrnaseq", ""),
                    "manual_biomarker_focus": validation.get("manual_biomarker_focus", ""),
                    "dataset_accession_visible": validation.get("manual_accession_present", ""),
                    "accession_ids": validation.get("manual_accessions", "") or ";".join(paper.get("accessions") or []),
                    "tool_accession_candidates": ";".join(paper.get("accessions") or []),
                    "manual_accession_present": validation.get("manual_accession_present", ""),
                    "manual_accessions": validation.get("manual_accessions", ""),
                    "accession_eval_label": validation.get("accession_eval_label", ""),
                    "key_finding_metadata_level": _metadata_summary(paper),
                    "evidence_note": "metadata-level evidence only",
                    "limitations_note": "full-text review pending",
                    "human_verified": "no",
                }
            )


def _write_review_records_jsonl(
    path: Path,
    ranked: list[tuple[int, dict[str, Any]]],
    validation_rows: dict[str, dict[str, str]],
) -> None:
    rows = []
    for rank, paper in ranked:
        pmid = str(paper.get("pmid", ""))
        rows.append(
            {
                "rank_position": rank,
                "citation_key": _citation_key(paper),
                "pmid": pmid,
                "doi": paper.get("doi", ""),
                "title": paper.get("title", ""),
                "journal": paper.get("journal", ""),
                "publication_year": _publication_year(paper.get("pub_date", "")),
                "score": paper.get("score", 0),
                "accessions": paper.get("accessions") or [],
                "validation": validation_rows.get(pmid, {}),
            }
        )
    _write_text(path, [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows])


def _read_review_records_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records_path = _resolve_review_records_path(path)
    if not records_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in records_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _resolve_review_records_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        return candidate / "review_records_frozen.jsonl"
    return candidate


def _snapshot_id_for_path(path: str | Path) -> str:
    candidate = Path(path)
    return candidate.parent.name if candidate.name == "review_records_frozen.jsonl" else candidate.name or str(path)


def _record_metadata_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    fields = ["doi", "title", "journal", "publication_year"]
    reasons = [field for field in fields if _clean(old.get(field)) != _clean(new.get(field))]
    if sorted(old.get("accessions") or []) != sorted(new.get("accessions") or []):
        reasons.append("accessions")
    return reasons


def _review_update_change(
    pmid: str,
    status: str,
    old_record: dict[str, Any] | None,
    new_record: dict[str, Any] | None,
    reasons: list[str],
    needs_reannotation: bool,
) -> dict[str, Any]:
    record = new_record or old_record or {}
    previous_validation = (old_record or {}).get("validation") or {}
    return {
        "pmid": pmid,
        "status": status,
        "citation_key": record.get("citation_key", ""),
        "title": record.get("title", ""),
        "doi": record.get("doi", ""),
        "publication_year": record.get("publication_year", ""),
        "reason": ";".join(reasons),
        "needs_reannotation": "yes" if needs_reannotation else "no",
        "previous_validation_present": "yes" if any(previous_validation.values()) else "no",
        "previous_manual_relevant": previous_validation.get("manual_relevant", ""),
        "previous_accession_eval_label": previous_validation.get("accession_eval_label", ""),
    }


def _review_update_diff_lines(summary: dict[str, Any]) -> list[str]:
    return [
        "# Review Update Diff",
        "",
        f"- Previous snapshot id: {summary['previous_snapshot_id']}",
        f"- Current snapshot id: {summary['current_snapshot_id']}",
        f"- Self-comparison: {'yes' if summary.get('self_comparison') else 'no'}",
        f"- Old records: {summary['old_records']}",
        f"- New records: {summary['new_records']}",
        f"- Added records: {summary['added_records']}",
        f"- Removed records: {summary['removed_records']}",
        f"- Unchanged records: {summary['unchanged_records']}",
        f"- Metadata-changed records: {summary['metadata_changed_records']}",
        f"- Labels carried forward: {summary['labels_carried_forward_count']}",
        f"- Records needing human review: {summary['needs_human_review_count']}",
        f"- Human update queue rows: {summary['human_update_queue_count']}",
        "",
        "## Changes",
        "",
        "| PMID | Status | Needs reannotation | Reason | Citation key | Title |",
        "| --- | --- | --- | --- | --- | --- |",
        *[
            (
                f"| {item['pmid']} | {item['status']} | {item['needs_reannotation']} | "
                f"{_table_cell(item['reason'] or '-')} | {_table_cell(item['citation_key'])} | "
                f"{_table_cell(item['title'])} |"
            )
            for item in summary["changes"]
        ],
        "",
        "## Boundary",
        "",
        "This diff is a mechanical snapshot comparison. Added or metadata-changed records should enter the human update queue before final include/exclude, full-text, or biological-interpretation claims are updated.",
        *(
            [
                "This run compared a snapshot path with itself. Treat it as a diff machinery self-check, not as evidence of a completed periodic update against an independent previous snapshot.",
            ]
            if summary.get("self_comparison")
            else []
        ),
        "",
    ]


def _write_human_update_queue(path: str | Path, changes: list[dict[str, Any]]) -> None:
    columns = [
        "pmid",
        "status",
        "citation_key",
        "title",
        "doi",
        "reason",
        "needs_reannotation",
        "previous_manual_relevant",
        "previous_accession_eval_label",
    ]
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for item in changes:
            if item["needs_reannotation"] == "yes":
                writer.writerow({column: item.get(column, "") for column in columns})


def _write_review_references(path: Path, papers: list[dict[str, Any]]) -> None:
    entries = []
    for paper in papers:
        fields = [
            ("title", paper.get("title", "")),
            ("author", paper.get("authors", "")),
            ("journal", paper.get("journal", "")),
            ("year", _publication_year(paper.get("pub_date", ""))),
            ("doi", paper.get("doi", "")),
            ("pmid", paper.get("pmid", "")),
            ("url", f"https://pubmed.ncbi.nlm.nih.gov/{paper.get('pmid', '')}/" if paper.get("pmid") else ""),
        ]
        body = "\n".join(f"  {name} = {{{_bibtex_value(value)}}}," for name, value in fields if value)
        entries.append(f"@article{{{_citation_key(paper)},\n{body}\n}}")
    _write_text(path, ["\n\n".join(entries), ""])


def _write_review_citation_audit(path: Path, papers: list[dict[str, Any]]) -> None:
    columns = [
        "pmid",
        "citation_key",
        "doi",
        "title",
        "journal",
        "publication_year",
        "doi_present",
        "bibtex_entry_present",
        "needs_metadata_verification",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for paper in papers:
            writer.writerow(
                {
                    "pmid": paper.get("pmid", ""),
                    "citation_key": _citation_key(paper),
                    "doi": paper.get("doi", ""),
                    "title": paper.get("title", ""),
                    "journal": paper.get("journal", ""),
                    "publication_year": _publication_year(paper.get("pub_date", "")),
                    "doi_present": "yes" if paper.get("doi") else "no",
                    "bibtex_entry_present": "yes",
                    "needs_metadata_verification": "yes",
                }
            )


def _write_review_fulltext_queue(
    path: Path,
    ranked: list[tuple[int, dict[str, Any]]],
    validation_rows: dict[str, dict[str, str]],
) -> None:
    columns = [
        "snapshot_id",
        "rank",
        "rank_position",
        "pmid",
        "citation_key",
        "doi",
        "title",
        "journal",
        "publication_year",
        "metadata_included",
        "included_after_metadata_validation",
        "full_text_status",
        "final_include",
        "exclusion_reason",
        "study_design",
        "population_or_model",
        "assay_type_verified",
        "assay_or_data_type",
        "accession_fulltext_verified",
        "dataset_accession_confirmed",
        "risk_of_bias_or_quality_required",
        "quality_assessment_status",
        "quality_notes",
        "human_verified",
        "reviewer_id",
        "review_date",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for rank, paper in ranked:
            pmid = str(paper.get("pmid", ""))
            validation = validation_rows.get(pmid, {})
            if _clean(validation.get("manual_relevant")) == "no":
                continue
            writer.writerow(
                {
                    "snapshot_id": validation.get("snapshot_id", ""),
                    "rank": rank,
                    "rank_position": rank,
                    "pmid": pmid,
                    "citation_key": _citation_key(paper),
                    "doi": paper.get("doi", ""),
                    "title": paper.get("title", ""),
                    "journal": paper.get("journal", ""),
                    "publication_year": _publication_year(paper.get("pub_date", "")),
                    "metadata_included": "yes",
                    "included_after_metadata_validation": "yes",
                    "full_text_status": "",
                    "final_include": "",
                    "exclusion_reason": "",
                    "study_design": "",
                    "population_or_model": "",
                    "assay_type_verified": "",
                    "assay_or_data_type": "",
                    "accession_fulltext_verified": "",
                    "dataset_accession_confirmed": "",
                    "risk_of_bias_or_quality_required": "",
                    "quality_assessment_status": "",
                    "quality_notes": "",
                    "human_verified": "no",
                    "reviewer_id": "",
                    "review_date": "",
                }
            )


def _write_review_human_checkpoints(path: Path) -> None:
    _write_text(
        path,
        [
            "# Human Review Checkpoints",
            "",
            "- Complete `review_fulltext_queue.csv` before treating the draft as a completed review.",
            "- Confirm final include/exclude labels in `review_evidence_table.csv`.",
            "- Fill `final_include`, `exclusion_reason`, `study_design`, `population_or_model`, `assay_type_verified`, `assay_or_data_type`, `accession_fulltext_verified`, `dataset_accession_confirmed`, `quality_assessment_status`, `human_verified`, `reviewer_id`, and `review_date` in `review_fulltext_queue.csv` before treating the draft as submission-ready.",
            "- Verify DOI and BibTeX metadata against publisher, CrossRef, or PubMed records.",
            "- Perform full-text eligibility and risk-of-bias or quality assessment if the target venue requires systematic-review language.",
            "- Approve final biological interpretation, clinical relevance wording, and venue-specific formatting.",
            "",
        ],
    )


def _write_review_fulltext_instructions(path: Path) -> None:
    lines = [
        "# Full-text Review Instructions",
        "",
        "Use this file with `reports/review_fulltext_queue.csv`. These instructions guide a human reviewer; they do not convert AI output into human full-text review.",
        "",
        "## Evidence Source",
        "",
        "- Use the article full text and supplements when available.",
        "- Use title/abstract metadata only to locate records, not to mark full-text eligibility complete.",
        "- Do not infer unavailable full-text facts from AI summaries or metadata-only evidence.",
        "",
        "## Required Fields",
        "",
        "| Field | Fill rule | Suggested values |",
        "| --- | --- | --- |",
        "| `full_text_status` | Whether the reviewer checked full text. | `available_checked`, `unavailable`, `not_applicable` |",
        "| `final_include` | Final human include decision after full-text review. | `yes`, `no`, `unclear` |",
        "| `exclusion_reason` | Required when `final_include` is `no` or `unclear`. | `off_topic`, `no_transcriptomics`, `no_immunotherapy_context`, `not_original_study`, `full_text_unavailable`, `other` |",
        "| `study_design` | Human-readable study type from full text. | free text |",
        "| `population_or_model` | Cancer type, cohort, model system, or sample context. | free text |",
        "| `assay_type_verified` | Whether the assay type was verified in full text. | `yes`, `no`, `unclear` |",
        "| `assay_or_data_type` | Verified assay or data type. | `bulk_rnaseq`, `scrnaseq`, `spatial`, `multiomics`, `other`, free text |",
        "| `accession_fulltext_verified` | Whether dataset accession or cohort identifiers were checked in full text/supplements. | `yes`, `no`, `not_applicable`, `unclear` |",
        "| `dataset_accession_confirmed` | Confirmed accession or cohort IDs, if any. | semicolon-separated IDs or blank |",
        "| `risk_of_bias_or_quality_required` | Whether the target review type or venue requires study-quality assessment. | `yes`, `no`, `venue_dependent`, `unclear` |",
        "| `quality_assessment_status` | Whether required quality assessment is done. | `not_started`, `pending`, `complete`, `not_applicable` |",
        "| `quality_notes` | Short notes on quality assessment or why it is not required. | free text |",
        "| `human_verified` | Set to `yes` only after the row has been reviewed and signed off. | `yes`, `no` |",
        "| `reviewer_id` | Reviewer initials or identifier. | free text |",
        "| `review_date` | Date of human full-text review. | `YYYY-MM-DD` |",
        "",
        "## Completion Rule",
        "",
        "A row is complete only when `full_text_status`, `final_include`, `human_verified`, `reviewer_id`, and `review_date` are filled, and `human_verified` is `yes`. If `final_include` is not `yes`, `exclusion_reason` must be filled.",
        "",
        "## Claim Boundary",
        "",
        "Until all included rows are human-verified and any required quality assessment is complete, the review package may be described only as a metadata-level submission draft package with pending human full-text gates.",
        "",
    ]
    _write_text(path, lines)


def _write_quality_assessment_guidance(path: Path) -> None:
    lines = [
        "# Quality and Risk-of-bias Assessment Guidance",
        "",
        "This file is a human guidance template only. No risk-of-bias or study-quality assessment has been completed by the software.",
        "",
        "Use this guidance with `reports/review_fulltext_queue.csv`. Do not treat blank or pending quality fields as evidence that a study is low quality, high quality, or not assessable.",
        "",
        "## Queue Fields",
        "",
        "| Field | Human fill rule | Suggested values |",
        "| --- | --- | --- |",
        "| `risk_of_bias_or_quality_required` | Decide after selecting the target venue, article type, and review claim level. | `yes`, `no`, `venue_dependent`, `unclear` |",
        "| `quality_assessment_status` | Record whether a required quality or risk-of-bias assessment has been completed by a human reviewer. | `not_started`, `pending`, `complete`, `not_applicable` |",
        "| `quality_notes` | Name the human-selected tool, reviewer decision, key limitations, or reason assessment is not applicable. | free text |",
        "",
        "## Tool Selection Boundary",
        "",
        "The reviewer should choose a venue- and design-appropriate tool only after the final included-study set is known. Examples may include JBI, CASP, QUADAS-2, ROBINS-I, Cochrane RoB 2, NIH tools, or MMAT, but this workflow does not select a default tool and does not score any study automatically.",
        "",
        "## Allowed Current Claim",
        "",
        "The review package includes structured human guidance and queue fields for venue-dependent quality or risk-of-bias assessment.",
        "",
        "## Forbidden Claims Until Human Completion",
        "",
        "- Do not state that risk of bias has been assessed.",
        "- Do not state that the evidence base is quality-assessed.",
        "- Do not state that AI performed quality assessment.",
        "- Do not state PRISMA compliance from this guidance file.",
        "- Do not assign high, moderate, or low study quality without human full-text assessment.",
        "",
    ]
    _write_text(path, lines)


def _write_prisma_flow(
    path: Path,
    json_path: Path,
    topics: list[Any],
    total_count: int,
    ranked: list[tuple[int, dict[str, Any]]],
    validation_rows: dict[str, dict[str, str]],
    generated: str,
) -> None:
    summary = _prisma_flow_summary(path.parent, topics, total_count, ranked, validation_rows, generated)
    _write_json(json_path, [summary])
    raw_boundary_line = (
        "- Raw PubMed hit count is stored from PubMed ESearch metadata; duplicate-removal count is still not stored separately beyond the PMID-primary-key snapshot."
        if summary["raw_pubmed_hit_count"] is not None
        else "- Raw PubMed hit count and duplicate-removal count are not stored in the current frozen package; the authoritative count starts at the deduplicated SQLite PMID snapshot."
    )
    lines = [
        "# PRISMA-oriented Metadata Flow",
        "",
        f"Generated at UTC: {generated}. This is a PubMed-only metadata-level flow; it is not a claim of PRISMA compliance and does not report completed full-text eligibility review.",
        "",
        "## Scope",
        "",
        f"- Topic id(s): {summary['topic_id']}",
        f"- Snapshot id: {summary['snapshot_id']}",
        "- Source database: PubMed only",
        f"- Search/snapshot timestamp: {summary['search_date']}",
        f"- Raw PubMed hit count: {summary['raw_records_retrieved_note']}",
        f"- Duplicate count: {summary['duplicates_removed_by_pmid_note']}",
        "",
        "## Flow Counts",
        "",
        "| Stage | Count | Boundary |",
        "| --- | ---: | --- |",
        f"| Deduplicated PubMed records | {summary['deduplicated_records']} | SQLite PMID-primary-key snapshot |",
        f"| Metadata-validated records | {summary['metadata_validated_records']} | Local validation rows with relevance labels |",
        f"| Metadata-relevant records | {summary['metadata_relevant_records']} | `manual_relevant=yes`; not final included studies |",
        f"| Metadata-irrelevant records | {summary['metadata_irrelevant_records']} | `manual_relevant=no`; not final human full-text exclusions |",
        f"| Metadata-unclear records | {summary['metadata_unclear_records']} | `manual_relevant=unclear` |",
        f"| Records routed to full-text queue | {summary['fulltext_queue_records']} | Metadata-level non-irrelevant records needing human review |",
        f"| Full-text checked records | {summary['fulltext_checked_records']} | `full_text_status` filled by human reviewer |",
        f"| Human-verified full-text records | {summary['human_verified_records']} | `human_verified=yes` |",
        f"| Final include decisions | {summary['final_include_yes']} yes; {summary['final_include_no']} no; {summary['final_include_unclear']} unclear; {summary['final_include_pending']} pending | Human completion required |",
        "",
        "## Recurring Update Counts",
        "",
        "| Update field | Count |",
        "| --- | ---: |",
        f"| Previous snapshot records | {summary['update']['old_records']} |",
        f"| Current snapshot records | {summary['update']['new_records']} |",
        f"| Added records | {summary['update']['added_records']} |",
        f"| Removed records | {summary['update']['removed_records']} |",
        f"| Unchanged records | {summary['update']['unchanged_records']} |",
        f"| Metadata-changed records | {summary['update']['metadata_changed_records']} |",
        f"| Records needing human update review | {summary['update']['needs_human_review_count']} |",
        f"| Human update queue rows | {summary['update']['human_update_queue_count']} |",
        "",
        "## Flow Diagram",
        "",
        "```mermaid",
        "flowchart TD",
        f"  A[Deduplicated PubMed records: {summary['deduplicated_records']}] --> B[Metadata validation rows: {summary['metadata_validated_records']}]",
        f"  B --> C[Metadata relevant: {summary['metadata_relevant_records']}]",
        f"  B --> D[Metadata irrelevant: {summary['metadata_irrelevant_records']}]",
        f"  C --> E[Full-text queue: {summary['fulltext_queue_records']}]",
        f"  E --> F[Full-text checked: {summary['fulltext_checked_records']}]",
        f"  E --> G[Final include pending: {summary['final_include_pending']}]",
        "```",
        "",
        "## Boundary Statement",
        "",
        "- This is a formal metadata-level flow for the frozen PubMed snapshot, not a completed systematic-review flow.",
        raw_boundary_line,
        "- Metadata-irrelevant records are not final full-text exclusion decisions.",
        "- Metadata-relevant records are not final included studies.",
        "- Full-text eligibility, final include/exclude decisions, exclusion reasons, and quality/risk-of-bias assessment remain human or venue-dependent.",
        "",
    ]
    _write_text(path, lines)


def _write_review_display_items(path: Path, json_path: Path, generated: str) -> None:
    flow = _review_prisma_flow_summary(path.parent / "review_prisma_flow.json") or {}
    evidence_rows = _read_csv_rows(path.parent / "review_evidence_table.csv")
    metadata_rows = [row for row in evidence_rows if _clean(row.get("included_after_metadata_validation")) == "yes"]
    theme_counts = Counter(row.get("review_theme") or "Uncategorized metadata records" for row in metadata_rows)
    citation_status = _citation_verification_summary(path.parent / "review_citation_verification.json")
    fulltext_status = _fulltext_queue_summary(path.parent / "review_fulltext_queue.csv")
    items = [
        {
            "item_id": "Figure 1",
            "item_type": "proposed figure",
            "proposed_title": "Metadata-level selection flow",
            "source_artifacts": [
                "reports/review_prisma_flow.md",
                "reports/review_prisma_flow.json",
                "reports/review_figure1_flow.mmd",
            ],
            "source_counts": {
                "deduplicated_records": flow.get("deduplicated_records", 0),
                "metadata_relevant_records": flow.get("metadata_relevant_records", 0),
                "fulltext_queue_records": flow.get("fulltext_queue_records", 0),
                "final_include_pending": flow.get("final_include_pending", 0),
            },
            "caption_draft": (
                "Proposed venue-neutral Figure 1. PubMed-only metadata/title/abstract-level selection flow for the "
                "frozen snapshot. Counts are not full-text-confirmed, not PRISMA-compliant, and final inclusion remains "
                "pending human review."
            ),
            "claim_boundary": "metadata-level selection flow only; not final full-text eligibility",
            "human_completion_required": "Adapt layout, exclusion reasons, and PRISMA/PRISMA-ScR wording after human full-text review.",
            "venue_dependency": "Target journal figure size, style, and checklist interpretation.",
            "status": "proposed; not final journal artwork",
        },
        {
            "item_id": "Figure 2",
            "item_type": "proposed figure",
            "proposed_title": "Metadata-level thematic distribution",
            "source_artifacts": [
                "reports/review_evidence_table.csv",
                "reports/review_draft.md",
                "reports/review_figure2_theme_distribution.csv",
                "reports/review_figure2_theme_distribution.md",
            ],
            "source_counts": {
                "metadata_relevant_records": len(metadata_rows),
                "theme_counts": dict(sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))),
            },
            "caption_draft": (
                "Proposed venue-neutral Figure 2. Distribution of PubMed metadata-level review themes among records routed "
                "to the full-text queue. Themes are title/abstract-level labels, not full-text-confirmed findings or final "
                "included-study conclusions."
            ),
            "claim_boundary": "metadata-level thematic labels only; no biological mechanism or quality claim",
            "human_completion_required": "Revise after final inclusion and full-text synthesis.",
            "venue_dependency": "Target journal figure style and whether a thematic figure is permitted.",
            "status": "proposed; not final journal artwork",
        },
        {
            "item_id": "Table 1",
            "item_type": "proposed table",
            "proposed_title": "Metadata-level evidence matrix",
            "source_artifacts": ["reports/review_evidence_table.csv"],
            "source_counts": {"evidence_rows": len(evidence_rows), "metadata_relevant_records": len(metadata_rows)},
            "caption_draft": (
                "Proposed Table 1. Metadata-level evidence matrix for the frozen PubMed snapshot, including citation keys, "
                "validation labels, review themes, metadata hints, and accession candidates. The table is not a final "
                "included-study table until human full-text eligibility is complete."
            ),
            "claim_boundary": "metadata evidence table only; no final inclusion or quality assessment",
            "human_completion_required": "Confirm fields against full texts before using as a final study characteristics table.",
            "venue_dependency": "Target journal table length and supplementary-material policy.",
            "status": "proposed; likely supplementary if full table is too long",
        },
        {
            "item_id": "Table 2",
            "item_type": "proposed table",
            "proposed_title": "Citation verification and reference metadata status",
            "source_artifacts": [
                "reports/review_citation_verification.md",
                "reports/review_citation_verification.json",
                "reports/review_citation_verification.csv",
                "reports/review_references.bib",
            ],
            "source_counts": {
                "citation_verification_status": citation_status["status"],
                "citation_verification_label": citation_status["label"],
            },
            "caption_draft": (
                "Proposed Table 2. Citation verification and PubMed-derived reference metadata status for the review package. "
                "Resolver status is a citation-metadata audit and does not substitute for target-journal reference formatting "
                "or full-text citation checking."
            ),
            "claim_boundary": "citation metadata audit only; not final venue-formatted references",
            "human_completion_required": "Resolve any journal-specific reference style, ordering, and unresolved DOI handling.",
            "venue_dependency": "Target journal reference style and supplementary table policy.",
            "status": "proposed; not final reference list",
        },
        {
            "item_id": "Supplementary Table 1",
            "item_type": "proposed supplementary table",
            "proposed_title": "Full-text queue and human checkpoint fields",
            "source_artifacts": ["reports/review_fulltext_queue.csv", "reports/review_fulltext_instructions.md", "reports/review_human_checkpoints.md"],
            "source_counts": {
                "fulltext_queue_records": fulltext_status["total_records"],
                "fulltext_completed_records": fulltext_status["fulltext_completed_count"],
                "human_verified_records": fulltext_status["human_verified_records"],
                "final_include_pending_records": fulltext_status["final_include_pending_count"],
            },
            "caption_draft": (
                "Proposed Supplementary Table 1. Human full-text review queue and checkpoint fields for completing eligibility, "
                "final inclusion, exclusion reasons, and venue-dependent quality or risk-of-bias assessment. Blank fields are "
                "pending review status, not negative evidence."
            ),
            "claim_boundary": "human review queue only; quality/RoB assessment pending or venue-dependent",
            "human_completion_required": "Complete reviewer fields before completed-review claims.",
            "venue_dependency": "Target journal supplementary-material and reporting-checklist requirements.",
            "status": "proposed; pending human completion",
        },
    ]
    lines = [
        "# Review Display Items Plan",
        "",
        f"Generated at UTC: {generated}. These are proposed, venue-neutral display items derived from existing review artifacts. They are not final journal artwork, not publication-ready figures, and not target-venue formatted tables.",
        "",
        "## Boundary",
        "",
        "Captions and source counts are PubMed-only and metadata/title/abstract-level unless a human reviewer later completes full-text eligibility. This file does not claim PRISMA compliance, full-text-confirmed findings, final included studies, clinical utility, biological mechanism, or quality-assessed evidence.",
        "",
        "## Proposed Items",
        "",
        "| Item | Type | Proposed title | Source artifacts | Status | Human/venue completion |",
        "| --- | --- | --- | --- | --- | --- |",
        *[
            (
                f"| {item['item_id']} | {item['item_type']} | {_table_cell(item['proposed_title'])} | "
                f"{_table_cell('; '.join(item['source_artifacts']))} | {_table_cell(item['status'])} | "
                f"{_table_cell(item['human_completion_required'])} |"
            )
            for item in items
        ],
        "",
        "## Draft Captions",
        "",
    ]
    for item in items:
        lines.extend(
            [
                f"### {item['item_id']}: {item['proposed_title']}",
                "",
                item["caption_draft"],
                "",
                f"- Claim boundary: {item['claim_boundary']}",
                f"- Venue dependency: {item['venue_dependency']}",
                "",
            ]
        )
    _write_text(path, lines)
    _write_json(json_path, items)


def _write_review_display_sources(
    flow_path: Path,
    theme_csv_path: Path,
    theme_md_path: Path,
    generated: str,
) -> None:
    flow = _review_prisma_flow_summary(flow_path.parent / "review_prisma_flow.json") or {}
    display_items_path = flow_path.parent / "review_display_items.json"
    items = json.loads(display_items_path.read_text(encoding="utf-8")) if display_items_path.exists() else []
    theme_counts: dict[str, int] = {}
    metadata_total = 0
    for item in items:
        if item.get("item_id") == "Figure 2":
            source_counts = item.get("source_counts") or {}
            metadata_total = int(source_counts.get("metadata_relevant_records") or 0)
            theme_counts = {str(key): int(value) for key, value in (source_counts.get("theme_counts") or {}).items()}

    flow_lines = [
        "flowchart TD",
        "  accTitle: Metadata Selection Flow",
        "  accDescr: PubMed-only metadata-level selection flow for the frozen review snapshot. Counts are not full-text-confirmed and final inclusion remains pending human review.",
        f"  dedup[\"Deduplicated PubMed records: {flow.get('deduplicated_records', 0)}\"] --> validation[\"Metadata validation rows: {flow.get('metadata_validated_records', 0)}\"]",
        f"  validation --> relevant[\"Metadata relevant: {flow.get('metadata_relevant_records', 0)}\"]",
        f"  validation --> irrelevant[\"Metadata irrelevant: {flow.get('metadata_irrelevant_records', 0)}\"]",
        f"  relevant --> queue[\"Full-text queue: {flow.get('fulltext_queue_records', 0)}\"]",
        f"  queue --> checked[\"Full-text checked: {flow.get('fulltext_checked_records', 0)}\"]",
        f"  queue --> pending[\"Final include pending: {flow.get('final_include_pending', 0)}\"]",
        "  classDef machine fill:#dbeafe,stroke:#2563eb,color:#1e3a5f",
        "  classDef human fill:#fef9c3,stroke:#ca8a04,color:#713f12",
        "  class dedup,validation,relevant,irrelevant machine",
        "  class queue,checked,pending human",
    ]
    _write_text(flow_path, flow_lines)

    theme_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with theme_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["theme", "records", "fraction_of_metadata_relevant", "claim_boundary"])
        writer.writeheader()
        for theme, records in sorted(theme_counts.items(), key=lambda item: (-item[1], item[0])):
            fraction = records / metadata_total if metadata_total else 0
            writer.writerow(
                {
                    "theme": theme,
                    "records": records,
                    "fraction_of_metadata_relevant": f"{fraction:.3f}",
                    "claim_boundary": "metadata-level theme only; not full-text-confirmed",
                }
            )

    theme_lines = [
        "# Figure 2 Source: Metadata-level Thematic Distribution",
        "",
        f"- Generated at UTC: {generated}",
        f"- Metadata-relevant denominator: {metadata_total}",
        "- Boundary: PubMed title/abstract metadata-level labels only; not final journal artwork and not full-text-confirmed synthesis.",
        "- Source files: `reports/review_display_items.json` and `reports/review_evidence_table.csv`.",
        "",
        "## Theme Counts",
        "",
        "| Theme | Records | Fraction of metadata-relevant records |",
        "| --- | ---: | ---: |",
        *[
            f"| {_table_cell(theme)} | {records} | {(records / metadata_total if metadata_total else 0):.3f} |"
            for theme, records in sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "",
        "## Mermaid Source",
        "",
        "```mermaid",
        "pie showData",
        "  title Metadata-level thematic distribution",
        *[
            f"  \"{theme.replace(chr(34), '')}\" : {records}"
            for theme, records in sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "```",
        "",
        "Human reviewers must revise captions, theme labels, and figure design after full-text eligibility and final inclusion are complete.",
        "",
    ]
    _write_text(theme_md_path, theme_lines)


def _prisma_flow_summary(
    output_dir: Path,
    topics: list[Any],
    total_count: int,
    ranked: list[tuple[int, dict[str, Any]]],
    validation_rows: dict[str, dict[str, str]],
    generated: str,
) -> dict[str, Any]:
    search_metadata = _read_search_run_metadata(output_dir / "search_run_metadata.json")
    raw_hit_count, retrieved_pmids = _search_metadata_counts(search_metadata, topics)
    relevance_rows = [row for row in validation_rows.values() if _clean(row.get("manual_relevant")) in {"yes", "no", "unclear"}]
    relevant = sum(1 for row in relevance_rows if _clean(row.get("manual_relevant")) == "yes")
    irrelevant = sum(1 for row in relevance_rows if _clean(row.get("manual_relevant")) == "no")
    unclear = sum(1 for row in relevance_rows if _clean(row.get("manual_relevant")) == "unclear")
    fulltext_rows = _read_csv_rows(output_dir / "review_fulltext_queue.csv")
    final_values = [_clean(row.get("final_include")) for row in fulltext_rows]
    snapshot_ids = sorted(
        {str(row.get("snapshot_id", "")).strip() for row in validation_rows.values() if str(row.get("snapshot_id", "")).strip()}
    )
    update_status = _review_update_summary(output_dir / "review_update_diff.json")
    return {
        "generated_at": generated,
        "topic_id": ", ".join(topic.name for topic in topics) or "not recorded",
        "snapshot_id": ", ".join(snapshot_ids) or "not recorded",
        "source_database": "PubMed only",
        "search_date": search_metadata.get("generated_at_utc") or generated,
        "search_date_note": (
            "PubMed ESearch execution timestamp from search_run_metadata.json."
            if search_metadata
            else "Package generation timestamp for the frozen snapshot; raw PubMed query execution timestamp is not separately stored in this flow."
        ),
        "raw_pubmed_hit_count": raw_hit_count,
        "raw_records_retrieved": retrieved_pmids,
        "raw_records_retrieved_note": (
            f"{raw_hit_count} PubMed ESearch hit(s); {retrieved_pmids} PMID(s) retrieved under retmax"
            if raw_hit_count is not None and retrieved_pmids is not None
            else "not stored in current frozen package"
        ),
        "search_run_metadata_file": "reports/search_run_metadata.json" if search_metadata else None,
        "duplicates_removed_by_pmid": None,
        "duplicates_removed_by_pmid_note": "not stored separately; the package starts from a PMID-deduplicated SQLite snapshot",
        "deduplicated_records": total_count,
        "ranked_records": len(ranked),
        "metadata_validated_records": len(relevance_rows),
        "metadata_relevant_records": relevant,
        "metadata_irrelevant_records": irrelevant,
        "metadata_unclear_records": unclear,
        "fulltext_queue_records": len(fulltext_rows),
        "fulltext_checked_records": sum(1 for row in fulltext_rows if _clean(row.get("full_text_status"))),
        "human_verified_records": sum(1 for row in fulltext_rows if _clean(row.get("human_verified")) == "yes"),
        "final_include_yes": sum(1 for value in final_values if value == "yes"),
        "final_include_no": sum(1 for value in final_values if value == "no"),
        "final_include_unclear": sum(1 for value in final_values if value == "unclear"),
        "final_include_pending": sum(1 for value in final_values if not value),
        "update": {
            "previous_snapshot_id": update_status["previous_snapshot_id"],
            "current_snapshot_id": update_status["current_snapshot_id"],
            "old_records": update_status["old_records"],
            "new_records": update_status["new_records"],
            "added_records": update_status["added_records"],
            "removed_records": update_status["removed_records"],
            "unchanged_records": update_status["unchanged_records"],
            "metadata_changed_records": update_status["metadata_changed_records"],
            "needs_human_review_count": update_status["needs_human_review_count"],
            "human_update_queue_count": update_status["human_update_queue_count"],
            "status": update_status["status"],
            "label": update_status["label"],
        },
        "claim_boundary": "formal PubMed-only metadata-level PRISMA-oriented flow with human full-text counts pending",
    }


def _write_review_forbidden_terms(path: Path) -> None:
    _write_text(path, ["terms:", *[f"  - {term}" for term in DEFAULT_REVIEW_RISK_TERMS], ""])


def write_review_claim_audit(
    draft_path: str | Path,
    evidence_path: str | Path,
    citations_path: str | Path,
    output_path: str | Path,
    json_path: str | Path,
    terms_path: str | Path | None = None,
) -> dict[str, Any]:
    draft = Path(draft_path).read_text(encoding="utf-8")
    evidence = _read_csv_rows(evidence_path)
    citations = _read_csv_rows(citations_path)
    terms = _read_risk_terms(terms_path)
    findings: list[dict[str, str]] = []

    _audit_required_text(draft, findings)
    _audit_counts(draft, evidence, citations, findings)
    _audit_risky_terms(draft, terms, findings)

    errors = [item for item in findings if item["severity"] == "error"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    audit = {
        "status": "fail" if errors else "pass",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "evidence_rows": len(evidence),
        "citation_rows": len(citations),
        "findings": findings,
    }
    lines = [
        "# Review Claim Audit",
        "",
        f"- Status: {audit['status']}",
        f"- Errors: {audit['error_count']}",
        f"- Warnings: {audit['warning_count']}",
        f"- Evidence rows: {audit['evidence_rows']}",
        f"- Citation rows: {audit['citation_rows']}",
        "",
        "## Findings",
        "",
        *(_claim_audit_lines(findings) if findings else ["No claim-audit findings."]),
        "",
    ]
    _write_text(Path(output_path), lines)
    _write_json(Path(json_path), [audit])
    return audit


def write_review_citation_verification(
    input_path: str | Path,
    output_path: str | Path,
    json_path: str | Path,
    csv_path: str | Path,
    timeout_seconds: float = 10,
    fetcher: Any | None = None,
) -> dict[str, Any]:
    citations = _read_csv_rows(input_path)
    fetch = fetcher or _fetch_crossref_work
    rows = []
    for row in citations:
        rows.append(_verify_citation_row(row, fetch, timeout_seconds))

    summary = {
        "total_records": len(rows),
        "verified_records": sum(1 for row in rows if row["status"] == "verified"),
        "pubmed_verified_unresolved_records": sum(1 for row in rows if row["status"] == "pubmed_verified_unresolved"),
        "warning_records": sum(1 for row in rows if row["status"] == "warning"),
        "failed_records": sum(1 for row in rows if row["status"] == "failed"),
        "network_error_records": sum(1 for row in rows if row["status"] == "network_error"),
        "rows": rows,
    }
    lines = [
        "# Review Citation Verification",
        "",
        f"- Total records: {summary['total_records']}",
        f"- Verified records: {summary['verified_records']}",
        f"- PubMed-confirmed but DOI-resolver-unresolved records: {summary['pubmed_verified_unresolved_records']}",
        f"- Warning records: {summary['warning_records']}",
        f"- Failed records: {summary['failed_records']}",
        f"- Network-error records: {summary['network_error_records']}",
        "",
        "## Findings",
        "",
        *_citation_verification_lines(rows),
        "",
    ]
    _write_text(Path(output_path), lines)
    _write_json(Path(json_path), [summary])
    _write_citation_verification_csv(Path(csv_path), rows)
    return summary


def _verify_citation_row(row: dict[str, str], fetcher: Any, timeout_seconds: float) -> dict[str, str]:
    doi = (row.get("doi") or "").strip()
    result = {
        "pmid": row.get("pmid", ""),
        "citation_key": row.get("citation_key", ""),
        "doi": doi,
        "status": "failed",
        "doi_match": "no",
        "title_check": "not_checked",
        "journal_check": "not_checked",
        "year_check": "not_checked",
        "crossref_title": "",
        "crossref_journal": "",
        "crossref_year": "",
        "warning": "",
        "error": "",
    }
    if not doi:
        result["error"] = "missing DOI"
        return result
    try:
        metadata = fetcher(doi, timeout_seconds)
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and _pubmed_confirms_doi(row.get("pmid", ""), doi, timeout_seconds):
            result["status"] = "pubmed_verified_unresolved"
            result["doi_match"] = "yes"
            result["warning"] = "doi_resolver_unresolved"
            result["error"] = "DOI present in PubMed but unresolved by CrossRef/doi.org"
            return result
        result["status"] = "failed" if exc.code == 404 else "network_error"
        result["error"] = str(exc)
        return result
    except Exception as exc:
        result["status"] = "network_error"
        result["error"] = str(exc)
        return result

    message = metadata.get("message", metadata) if isinstance(metadata, dict) else {}
    crossref_doi = str(message.get("DOI", "")).lower()
    result["doi_match"] = "yes" if crossref_doi == doi.lower() else "no"
    result["crossref_title"] = _first_text(message.get("title"))
    result["crossref_journal"] = _first_text(message.get("container-title"))
    result["crossref_year"] = _crossref_year(message)
    result["title_check"] = _metadata_text_check(row.get("title", ""), result["crossref_title"])
    result["journal_check"] = _metadata_text_check(row.get("journal", ""), result["crossref_journal"])
    result["year_check"] = "match" if not row.get("publication_year") or row.get("publication_year") == result["crossref_year"] else "mismatch"

    warnings = [
        label
        for label, value in [
            ("doi", result["doi_match"]),
            ("title", result["title_check"]),
            ("journal", result["journal_check"]),
            ("year", result["year_check"]),
        ]
        if value in {"no", "mismatch", "weak_match"}
    ]
    result["warning"] = ";".join(warnings)
    result["status"] = "verified" if result["doi_match"] == "yes" and not warnings else "warning"
    if result["doi_match"] != "yes":
        result["status"] = "failed"
    return result


def _fetch_crossref_work(doi: str, timeout_seconds: float) -> dict[str, Any]:
    quoted = urllib.parse.quote(doi, safe="")
    request = urllib.request.Request(
        f"https://api.crossref.org/works/{quoted}",
        headers={"User-Agent": "autobiosci-sentinel-lite/0.2 (mailto:example@example.com)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    fallback = urllib.request.Request(
        f"https://doi.org/{quoted}",
        headers={
            "Accept": "application/vnd.citationstyles.csl+json",
            "User-Agent": "autobiosci-sentinel-lite/0.2 (mailto:example@example.com)",
        },
    )
    with urllib.request.urlopen(fallback, timeout=timeout_seconds) as response:
        return {"message": json.loads(response.read().decode("utf-8"))}


def _pubmed_confirms_doi(pmid: str | None, doi: str, timeout_seconds: float) -> bool:
    if not pmid:
        return False
    query = urllib.parse.urlencode({"db": "pubmed", "id": pmid, "retmode": "json"})
    request = urllib.request.Request(
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{query}",
        headers={"User-Agent": "autobiosci-sentinel-lite/0.2 (mailto:example@example.com)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    ids = (data.get("result", {}).get(str(pmid), {}) or {}).get("articleids") or []
    return any(item.get("idtype") == "doi" and str(item.get("value", "")).lower() == doi.lower() for item in ids)


def _first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value or "")


def _crossref_year(message: dict[str, Any]) -> str:
    for field in ["published-print", "published-online", "issued", "created"]:
        parts = (message.get(field) or {}).get("date-parts") if isinstance(message.get(field), dict) else None
        if parts and parts[0]:
            return str(parts[0][0])
    return ""


def _metadata_text_check(local: str | None, remote: str | None) -> str:
    local_norm = _normalize_metadata_text(local)
    remote_norm = _normalize_metadata_text(remote)
    if not local_norm or not remote_norm:
        return "not_checked"
    if local_norm == remote_norm:
        return "match"
    if local_norm in remote_norm or remote_norm in local_norm:
        return "match"
    local_tokens = set(local_norm.split())
    remote_tokens = set(remote_norm.split())
    overlap = len(local_tokens & remote_tokens) / max(1, len(local_tokens | remote_tokens))
    return "weak_match" if overlap >= 0.5 else "mismatch"


def _normalize_metadata_text(value: str | None) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())


def _citation_verification_lines(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["No citation rows found."]
    return [
        "| PMID | DOI | Status | Warning | Error |",
        "| --- | --- | --- | --- | --- |",
        *[
            (
                f"| {row['pmid']} | {_table_cell(row['doi'])} | {row['status']} | "
                f"{_table_cell(row['warning']) or '-'} | {_table_cell(row['error']) or '-'} |"
            )
            for row in rows
            if row["status"] != "verified"
        ],
        *([] if any(row["status"] != "verified" for row in rows) else ["| all | - | verified | - | - |"]),
    ]


def _write_citation_verification_csv(path: Path, rows: list[dict[str, str]]) -> None:
    columns = [
        "pmid",
        "citation_key",
        "doi",
        "status",
        "doi_match",
        "title_check",
        "journal_check",
        "year_check",
        "crossref_title",
        "crossref_journal",
        "crossref_year",
        "warning",
        "error",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_risk_terms(path: str | Path | None) -> list[str]:
    if path is None or not Path(path).exists():
        return DEFAULT_REVIEW_RISK_TERMS
    terms: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text.startswith("- "):
            terms.append(text[2:].strip())
    return terms or DEFAULT_REVIEW_RISK_TERMS


def _audit_required_text(draft: str, findings: list[dict[str, str]]) -> None:
    required = {
        "metadata-level": "Draft must state the metadata-level evidence boundary.",
        "not a completed systematic review": "Draft must explicitly avoid completed systematic-review claims.",
        "human review": "Draft must keep human review checkpoints visible.",
    }
    lower = draft.lower()
    for needle, message in required.items():
        if needle not in lower:
            findings.append({"severity": "error", "kind": "missing_boundary", "message": message})


def _audit_counts(
    draft: str,
    evidence: list[dict[str, str]],
    citations: list[dict[str, str]],
    findings: list[dict[str, str]],
) -> None:
    lower = draft.lower()
    evidence_count = len(evidence)
    included_count = sum(1 for row in evidence if _clean(row.get("included_after_metadata_validation")) == "yes")
    doi_count = sum(1 for row in evidence if row.get("doi"))
    citation_count = len(citations)
    checks = [
        (str(evidence_count), f"Draft should mention frozen/evidence record count {evidence_count}."),
        (f"{included_count}/{included_count}", f"Draft should mention included DOI/abstract denominator {included_count}/{included_count}."),
    ]
    for needle, message in checks:
        if needle not in draft:
            findings.append({"severity": "warning", "kind": "count_visibility", "message": message})
    if citation_count != evidence_count:
        findings.append(
            {
                "severity": "error",
                "kind": "citation_coverage",
                "message": f"Citation rows ({citation_count}) do not match evidence rows ({evidence_count}).",
            }
        )
    if doi_count != evidence_count:
        findings.append(
            {
                "severity": "warning",
                "kind": "doi_coverage",
                "message": f"DOI strings present for {doi_count}/{evidence_count} evidence rows.",
            }
        )
    if "citation audit" not in lower:
        findings.append({"severity": "warning", "kind": "citation_visibility", "message": "Draft should mention citation audit status."})


def _audit_risky_terms(draft: str, terms: list[str], findings: list[dict[str, str]]) -> None:
    guard_words = ["not ", "does not", "pending", "human", "metadata", "limitation", "before final", "requires"]
    for line_no, line in enumerate(draft.splitlines(), 1):
        lower = line.lower()
        for term in terms:
            if term.lower() in lower:
                source_metadata = line.strip().startswith("|") or "pubmed title reports" in lower
                guarded = source_metadata or any(word in lower for word in guard_words)
                findings.append(
                    {
                        "severity": "warning" if guarded else "error",
                        "kind": "risky_term",
                        "message": f"Line {line_no}: `{term}` appears{' as source metadata' if source_metadata else ' with guard language' if guarded else ' without guard language'}.",
                    }
                )


def _claim_audit_lines(findings: list[dict[str, str]]) -> list[str]:
    return [
        "| Severity | Kind | Message |",
        "| --- | --- | --- |",
        *[f"| {item['severity']} | {item['kind']} | {_table_cell(item['message'])} |" for item in findings],
    ]


def _write_review_submission_audit(
    path: Path,
    papers: list[dict[str, Any]],
    validation: dict[str, Any] | None,
    spotcheck: dict[str, Any] | None,
    ai_spotcheck: dict[str, Any] | None,
) -> None:
    doi_count = sum(1 for paper in papers if paper.get("doi"))
    abstract_count = sum(1 for paper in papers if paper.get("abstract"))
    citation_status = _citation_verification_summary(path.parent / "review_citation_verification.json")
    update_status = _review_update_summary(path.parent / "review_update_diff.json")
    fulltext_status = _fulltext_queue_summary(path.parent / "review_fulltext_queue.csv")
    search_status = _search_strategy_status(path.parent / "review_search_strategy.json", len(papers))
    coverage_status = _search_coverage_status(path.parent / "review_search_strategy.json")
    inventory_status = _search_inventory_status(path.parent / "review_search_coverage.json")
    citation_blocker = (
        "- External citation metadata verification has not been run."
        if citation_status["status"] == "not_run"
        else f"- External citation metadata verification has {citation_status['failed_records']} failed record(s)."
        if citation_status["failed_records"]
        else ""
    )
    lines = [
        "# Review Submission Audit",
        "",
        "## Machine-checkable Gates",
        "",
        f"- Frozen records: {len(papers)}",
        f"- DOI strings present: {doi_count}/{len(papers)}",
        f"- Cached abstracts present: {abstract_count}/{len(papers)}",
        f"- Validation: {_review_validation_status(validation, expected_records=len(papers))}",
        f"- AI consensus: {_review_spotcheck_status(ai_spotcheck)}",
        f"- Human spot-check: {_review_spotcheck_status(spotcheck)}",
        f"- Search strategy documentation: {search_status['label']}",
        f"- Search coverage gate: {coverage_status['label']}",
        f"- Search coverage inventory: {inventory_status['label']}",
        f"- Citation verification: {citation_status['label']}",
        f"- Periodic update readiness: {update_status['label']}",
        f"- Full-text/quality queue: {fulltext_status['label']}",
        "",
        "## Current Verdict",
        "",
        (
            "Not yet submission-ready as a completed biological or systematic review. The package is submission-supporting "
            "as a metadata-level scoping-review protocol/tooling artifact."
        ),
        "",
        "## Hard Blockers for Completed Review Claims",
        "",
        "- Human include/exclude and full-text checkpoints are not completed.",
        *([citation_blocker] if citation_blocker else []),
        *[f"- Search strategy warning: {warning}." for warning in search_status["warnings"]],
        f"- Search coverage boundary: {coverage_status['boundary_statement']}",
        f"- Search inventory boundary: {inventory_status['boundary_statement']}",
        "- Risk-of-bias or study-quality assessment is not completed; human guidance and queue fields are present.",
        "- Biological interpretation is limited to title/abstract metadata signals.",
        *(
            ["- Added or metadata-changed update records still need human update review."]
            if update_status["needs_human_review_count"]
            else []
        ),
        "",
        "## Codex/AI-appropriate Checks",
        "",
        "- Citation-key coverage, DOI presence, evidence-table completeness, validation-label consistency, update-diff routing, and unsupported-claim detection.",
        "",
    ]
    _write_text(path, lines)


def _write_review_draft(
    path: Path,
    topics: list[Any],
    total_count: int,
    ranked: list[tuple[int, dict[str, Any]]],
    validation_rows: dict[str, dict[str, str]],
    validation: dict[str, Any] | None,
    spotcheck: dict[str, Any] | None,
    ai_spotcheck: dict[str, Any] | None,
    generated: str,
) -> None:
    included = [
        paper
        for _, paper in ranked
        if _clean(validation_rows.get(str(paper.get("pmid", "")), {}).get("manual_relevant")) != "no"
    ]
    accessions = sorted({item for paper in included for item in (paper.get("accessions") or [])})
    topic_names = ", ".join(topic.name for topic in topics) or "configured topic"
    topic_label = _human_topic_label(topics)
    doi_count = sum(1 for paper in included if paper.get("doi"))
    abstract_count = sum(1 for paper in included if paper.get("abstract"))
    theme_rows = _review_theme_rows(included)
    update_status = _review_update_summary(path.parent / "review_update_diff.json")
    fulltext_status = _fulltext_queue_summary(path.parent / "review_fulltext_queue.csv")
    citation_status = _citation_verification_summary(path.parent / "review_citation_verification.json")
    coverage_status = _search_coverage_status(path.parent / "review_search_strategy.json")
    inventory_status = _search_inventory_status(path.parent / "review_search_coverage.json")
    citation_verification = _citation_verification_by_pmid(path.parent / "review_citation_verification.csv")
    if citation_status["status"] == "complete":
        citation_boundary = (
            "`reports/review_citation_verification.*` records external DOI resolver and PubMed-confirmation "
            "status for each reference; unresolved DOI resolver cases remain flagged for human or venue handling "
            "before final submission."
        )
        citation_readiness_gate = "any unresolved citation-verification cases are handled according to target venue rules"
        citation_limit = (
            "Citation verification has been run, but DOI resolver-unresolved cases and venue-specific reference "
            "formatting still require human or venue handling"
        )
    else:
        citation_boundary = (
            "`reports/review_citation_audit.csv` marks each reference for external metadata verification before "
            "final submission, because local DOI presence is not the same as publisher/CrossRef validation."
        )
        citation_readiness_gate = "citation verification is completed"
        citation_limit = "Citation verification remains incomplete"
    flow_summary = _review_prisma_flow_summary(path.parent / "review_prisma_flow.json") or _prisma_flow_summary(
        path.parent, topics, total_count, ranked, validation_rows, generated
    )
    theme_synthesis_lines = _metadata_theme_synthesis_lines(path.parent / "review_evidence_table.csv", fulltext_status)
    coverage_inventory_files = (
        "`reports/review_search_coverage.md`, `reports/review_search_coverage.json`, "
        "`reports/review_search_coverage.csv`, "
        if (path.parent / "review_search_coverage.json").exists()
        else ""
    )
    lines = [
        f"# Metadata-level scoping review draft for {topic_label} surveillance",
        "",
        "## Abstract",
        "",
        (
            f"This AI-assisted, PubMed-only metadata-level draft describes a recurring surveillance workflow for "
            f"{topic_label}. Records were collected from a frozen PubMed/SQLite snapshot, deduplicated by PMID, joined "
            "to local metadata-level validation labels, and exported with a protocol, search strategy appendix, evidence "
            f"matrix, BibTeX file, PRISMA-oriented flow, and human review checkpoints. The current snapshot contains "
            f"{total_count} deduplicated record(s), of which {len(included)} were not locally labeled irrelevant; "
            f"{doi_count}/{len(included)} metadata-included record(s) have DOI metadata, {abstract_count}/{len(included)} "
            f"have cached abstracts, and {len(accessions)} tool-detected accession candidate(s) were visible in metadata. "
            f"{coverage_status['boundary_statement']} "
            "The package is suitable as a human-auditable review draft and submission-support artifact, while human "
            "full-text eligibility, final inclusion, quality or risk-of-bias assessment, and venue-specific formatting remain pending."
        ),
        "",
        "## Introduction",
        "",
        (
            "Cancer immunotherapy studies increasingly use bulk RNA-seq, single-cell RNA-seq, spatial transcriptomics, "
            "and multi-omics profiling to describe tumor microenvironment state, response-associated biomarkers, and "
            "candidate prognostic signatures. A recurring metadata-level review can help keep this literature visible "
            "without hiding search settings, ranking rules, validation labels, or citation state."
        ),
        "",
        "## Methods",
        "",
        (
            "Records were collected from PubMed with the frozen topic query documented in `reports/review_protocol.md` "
            "and `reports/review_search_strategy.md`, deduplicated by PMID in SQLite, ranked with deterministic keyword "
            "and accession heuristics, and joined to local metadata-level validation labels. The review package exports "
            "`reports/review_records_frozen.jsonl`, `reports/review_evidence_table.csv`, `reports/review_references.bib`, "
            "`reports/review_citation_audit.csv`, `reports/review_citation_verification.*`, `reports/review_prisma_flow.*`, "
            "`reports/review_claim_audit.*`, `reports/review_fulltext_queue.csv`, and `reports/review_quality_assessment_guidance.md`. "
            "The search is PubMed-only, not librarian peer-reviewed, and not multi-database; inclusion and exclusion "
            f"decisions remain metadata-level unless a human reviewer completes the full-text checkpoints. Search coverage gate: {coverage_status['label']}. "
            f"Search coverage inventory: {inventory_status['label']}."
        ),
        "",
        "## Metadata-Level Selection Flow",
        "",
        (
            "This draft mirrors the machine-readable flow in `reports/review_prisma_flow.json`, with a human-readable "
            "companion in `reports/review_prisma_flow.md`. The flow is PubMed-only and metadata/title/abstract-level; "
            "it is not a claim of PRISMA compliance, multi-database coverage, librarian peer review, completed full-text "
            "eligibility, or final systematic-review inclusion."
        ),
        "",
        "| Stage | Count | Boundary |",
        "| --- | ---: | --- |",
        *_metadata_selection_flow_table_lines(flow_summary),
        "",
        f"Recurring update status: {flow_summary.get('update', {}).get('label', 'not run')}.",
        "",
        "## Results",
        "",
        *_review_metric_lines(validation, ai_spotcheck, spotcheck, citation_status, update_status, fulltext_status),
        "",
        "### Thematic Metadata Map",
        "",
        "| Theme | Records | Example citation keys |",
        "| --- | ---: | --- |",
        *_review_theme_table_lines(theme_rows),
        "",
        "### Evidence Table Preview",
        "",
        "| Rank | PMID | Citation key | Title | Journal | Year | Validation | Accessions |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        *[
            _review_preview_line(rank, paper, validation_rows.get(str(paper.get("pmid", "")), {}))
            for rank, paper in ranked[:10]
        ],
        "",
        "## Draft Synthesis",
        "",
        (
            "The metadata map suggests four recurring review themes: spatial or tissue-context transcriptomics, "
            "single-cell tumor microenvironment atlases, multi-omics or computational biomarker modeling, and "
            "signature-oriented prognosis or treatment-response studies. These themes should be interpreted as "
            "title/abstract-level signals rather than confirmed biological conclusions. The strongest submission-safe "
            "claim is workflow-oriented: the package can freeze a topic, preserve search results, expose deterministic "
            "prioritization, export citations and evidence tables, and separate AI-assisted consistency checks from "
            "human or venue-dependent interpretation."
        ),
        "",
        "Human review should revise this section after checking full texts for final thematic claims, study-design details, and risk-of-bias language.",
        "",
        "## Metadata-Level Thematic Synthesis",
        "",
        *theme_synthesis_lines,
        "",
        "## Changes Since Previous Snapshot",
        "",
        update_status["draft_text"],
        "",
        "## Citation and Metadata Status",
        "",
        (
            f"Cached abstracts are present for {abstract_count}/{len(included)} included metadata-level record(s), "
            f"and DOI strings are present for {doi_count}/{len(included)}. "
            f"The citation audit status is {citation_status['label']}. {citation_boundary}"
        ),
        "",
        "## Reference Metadata: PubMed-derived records included at metadata level",
        "",
        (
            f"This section lists {len(included)} metadata-included record(s) for draft inspection; the full "
            f"{total_count}-record frozen snapshot remains available in `reports/review_records_frozen.jsonl` and "
            "`reports/review_evidence_table.csv`. Target-journal reference styling and final citation selection require "
            "human or venue review."
        ),
        "",
        "| Citation key | PMID | DOI | Journal | Year | Citation verification | Title |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
        *_reference_metadata_table_lines(included, citation_verification),
        "",
        "## Submission Readiness",
        "",
        (
            "This version is closest to a submission-supporting living scoping-review protocol or methods/tooling "
            "manuscript. It is not ready to be submitted as a completed biological review until the human checkpoints "
            f"are filled, {citation_readiness_gate}, and any target venue requirements for full-text "
            f"screening or quality assessment are satisfied. Full-text/quality queue status: {fulltext_status['label']}."
        ),
        "",
        "## Limitations",
        "",
        (
            "This is not a completed systematic review. It uses PubMed metadata rather than full text and does not "
            "perform risk-of-bias assessment or validate datasets outside metadata-visible accession strings. "
            f"{coverage_status['boundary_statement']} {citation_limit}. AI consensus is suitable for mechanical consistency checks only."
        ),
        "",
        "## Data Availability",
        "",
        (
            "The reproducible review package consists of `reports/review_protocol.md`, "
            "`reports/review_search_strategy.md`, `reports/review_search_strategy.json`, "
            f"{coverage_inventory_files}"
            "`reports/review_records_frozen.jsonl`, `reports/review_evidence_table.csv`, "
            "`reports/review_references.bib`, `reports/review_citation_audit.csv`, "
            "`reports/review_citation_verification.*`, `reports/review_update_diff.*`, "
            "`reports/review_fulltext_queue.csv`, `reports/human_update_queue.csv`, "
            "`reports/review_fulltext_instructions.md`, `reports/review_quality_assessment_guidance.md`, "
            "`reports/review_human_checkpoints.md`, "
            "`reports/review_submission_audit.md`, `reports/review_draft.md`, "
            "`reports/review_prisma_flow.md`, `reports/review_prisma_flow.json`, "
            "`reports/review_display_items.md`, `reports/review_display_items.json`, "
            "`reports/review_figure1_flow.mmd`, `reports/review_figure2_theme_distribution.csv`, "
            "`reports/review_figure2_theme_distribution.md`, "
            "`reports/review_manifest.md`, `reports/review_manifest.json`, `reports/submission_manifest.md`, "
            "`reports/review_submission_declarations.md`, `reports/review_submission_checklist.md`, and "
            "`reports/review_prisma_checklist.md`. "
            f"This draft was generated at {generated}."
        ),
        "",
    ]
    _write_text(path, lines)


def _write_review_manifest(
    path: Path,
    paths: dict[str, Path],
    validation: dict[str, Any] | None,
    spotcheck: dict[str, Any] | None,
    ai_spotcheck: dict[str, Any] | None,
    generated: str,
) -> None:
    citation_status = _citation_verification_summary(path.parent / "review_citation_verification.json")
    update_status = _review_update_summary(path.parent / "review_update_diff.json")
    fulltext_status = _fulltext_queue_summary(path.parent / "review_fulltext_queue.csv")
    record_count = len(_read_review_records_jsonl(paths["records"]))
    search_status = _search_strategy_status(path.parent / "review_search_strategy.json", record_count)
    coverage_status = _search_coverage_status(path.parent / "review_search_strategy.json")
    inventory_status = _search_inventory_status(path.parent / "review_search_coverage.json")
    lines = [
        "# Review Package Manifest",
        "",
        f"- Generated at UTC: {generated}",
        "- Command: `python -m autobiosci_sentinel.cli review --config configs/topics.yaml --db data/papers.sqlite --output-dir reports`",
        "",
        "## Files",
        "",
        "| File | Purpose |",
        "| --- | --- |",
        *[f"| `{path.as_posix()}` | {name} |" for name, path in paths.items()],
        "",
        "## Current Gates",
        "",
        f"- Validation coverage: {_review_validation_status(validation, expected_records=record_count)}",
        f"- AI consensus: {_review_spotcheck_status(ai_spotcheck)}",
        f"- Human spot-check: {_review_spotcheck_status(spotcheck)}",
        f"- Search strategy documentation: {search_status['label']}",
        f"- Search coverage gate: {coverage_status['label']}",
        f"- Search coverage inventory: {inventory_status['label']}",
        f"- Citation verification: {citation_status['label']}",
        f"- Periodic update readiness: {update_status['label']}",
        f"- Full-text/quality queue: {fulltext_status['label']}",
        f"- Previous snapshot id: {update_status['previous_snapshot_id'] or 'not available'}",
        f"- Current snapshot id: {update_status['current_snapshot_id'] or 'not available'}",
        f"- Previous snapshot records: {update_status['old_records']}",
        f"- Current snapshot records: {update_status['new_records']}",
        f"- New records: {update_status['added_records']}",
        f"- Metadata-changed records: {update_status['metadata_changed_records']}",
        f"- Labels carried forward: {update_status['labels_carried_forward_count']}",
        f"- Records needing human update review: {update_status['needs_human_review_count']}",
        f"- Human update queue rows: {update_status['human_update_queue_count']}",
        f"- Full-text queue records: {fulltext_status['total_records']}",
        f"- Full-text completed records: {fulltext_status['fulltext_completed_count']}",
        f"- Final-include pending records: {fulltext_status['final_include_pending_count']}",
        f"- Full-text queue human-verified records: {fulltext_status['human_verified_records']}",
        "- Human/venue-dependent before submission: full-text eligibility, final synthesis wording, risk-of-bias/quality assessment if required, unresolved citation correction, and target-journal formatting.",
        "",
    ]
    _write_text(path, lines)


def _write_submission_manifest(
    path: Path,
    paths: dict[str, Path],
    topics: list[Any],
    validation: dict[str, Any] | None,
    spotcheck: dict[str, Any] | None,
    ai_spotcheck: dict[str, Any] | None,
    generated: str,
) -> None:
    citation_status = _citation_verification_summary(path.parent / "review_citation_verification.json")
    update_status = _review_update_summary(path.parent / "review_update_diff.json")
    fulltext_status = _fulltext_queue_summary(path.parent / "review_fulltext_queue.csv")
    record_count = len(_read_review_records_jsonl(paths["records"]))
    search_status = _search_strategy_status(path.parent / "review_search_strategy.json", record_count)
    coverage_status = _search_coverage_status(path.parent / "review_search_strategy.json")
    inventory_status = _search_inventory_status(path.parent / "review_search_coverage.json")
    topic_ids = ", ".join(topic.name for topic in topics) or "not recorded"
    test_status = os.environ.get("AUTOBIOSCI_TEST_STATUS", "not recorded in manifest; run `python -m pytest` before submission")
    package_missing = [name for name, file_path in paths.items() if name != "submission_manifest" and not file_path.exists()]
    package_consistency = (
        f"PASS: {len(paths)} listed file(s) present"
        if not package_missing
        else f"FAIL: missing {', '.join(package_missing)}"
    )
    lines = [
        "# Submission Packet Manifest",
        "",
        f"- Generated at UTC: {generated}",
        f"- Topic id(s): {topic_ids}",
        f"- Previous snapshot id: {update_status['previous_snapshot_id'] or 'not available'}",
        f"- Current snapshot id: {update_status['current_snapshot_id'] or 'not available'}",
        f"- Test suite: {test_status}",
        "- Intended claim boundary: submission-oriented metadata-level review draft package with structured human checkpoints.",
        "",
        "## Packet Files",
        "",
        "| File | Purpose |",
        "| --- | --- |",
        *[f"| `{file_path.as_posix()}` | {name} |" for name, file_path in paths.items()],
        "",
        "## Machine Gates",
        "",
        f"- Validation: {_review_validation_status(validation, expected_records=record_count)}",
        f"- AI consensus: {_review_spotcheck_status(ai_spotcheck)}",
        f"- Search strategy documentation: {search_status['label']}",
        f"- Search coverage gate: {coverage_status['label']}",
        f"- Search coverage inventory: {inventory_status['label']}",
        f"- Citation verification: {citation_status['label']}",
        f"- Periodic update readiness: {update_status['label']}",
        f"- Package consistency: {package_consistency}",
        f"- Claim audit: see `{paths['claim_audit'].as_posix()}` and `{paths['claim_audit_json'].as_posix()}`.",
        f"- Display-item sources: proposed venue-neutral items and reproducible text sources in `{paths['display_items'].as_posix()}`, `{paths['display_items_json'].as_posix()}`, `{paths['figure1_flow_source'].as_posix()}`, `{paths['figure2_theme_distribution_csv'].as_posix()}`, and `{paths['figure2_theme_distribution_md'].as_posix()}`; not final journal artwork.",
        "",
        "## Human Gates",
        "",
        f"- Independent human spot-check: {_review_spotcheck_status(spotcheck)}",
        f"- Full-text and quality queue: {fulltext_status['label']}",
        "- Final include/exclude, full-text eligibility, study-quality assessment, and final biological interpretation are human or venue-dependent.",
        "",
        "## Reproducible Commands",
        "",
        "```bash",
        "python -m autobiosci_sentinel.cli worker --auto --config configs/topics.yaml --db data/papers.sqlite --report reports/daily_report.md --max-jobs 3",
        "python -m autobiosci_sentinel.cli validation-metrics --input reports/validation_template.csv --output reports/validation_metrics.md",
        "python -m autobiosci_sentinel.cli spotcheck-summary --input reports/ai_consensus_spotcheck.csv --validation reports/validation_template.csv --output reports/ai_consensus_spotcheck_summary.md --title \"AI-assisted Consensus Spot-check Summary\"",
        "python -m autobiosci_sentinel.cli review-search-coverage --config configs/topics.yaml --db data/papers.sqlite --output reports/review_search_coverage.md --json reports/review_search_coverage.json --csv reports/review_search_coverage.csv",
        "python -m autobiosci_sentinel.cli review --config configs/topics.yaml --db data/papers.sqlite --output-dir reports",
        "python -m autobiosci_sentinel.cli review-citation-verify --input reports/review_citation_audit.csv --output reports/review_citation_verification.md --json reports/review_citation_verification.json --csv reports/review_citation_verification.csv",
        "python -m autobiosci_sentinel.cli review-update-diff --old .review_prev --new reports --output reports/review_update_diff.md --json reports/review_update_diff.json --queue reports/human_update_queue.csv",
        "python -m autobiosci_sentinel.cli review-claim-audit --draft reports/review_draft.md --evidence reports/review_evidence_table.csv --citations reports/review_citation_audit.csv --output reports/review_claim_audit.md --json reports/review_claim_audit.json",
        "python -m pytest",
        "```",
        "",
        "## Allowed Claims",
        "",
        "- The package generates a submission-oriented review draft from a frozen PubMed metadata snapshot.",
        f"- Search coverage is explicitly bounded: {coverage_status['boundary_statement']}",
        "- The package includes citation verification, update-diff routing, evidence tables, BibTeX, claim audit, venue-neutral display-item source files, and structured human full-text/quality checkpoints.",
        "- AI-assisted checks are mechanical consistency checks, not independent human review.",
        "",
        "## Forbidden Until Human/Venue Gates Are Complete",
        "",
        "- Do not claim a completed systematic review, completed full-text synthesis, quality-assessed evidence base, clinical recommendation, treatment efficacy, or confirmed biological mechanism.",
        "- Do not treat empty `review_fulltext_queue.csv` fields as negative evidence.",
        "- Do not replace target-journal formatting, completed author declarations, cover letter, or title page with this manifest, `reports/review_submission_declarations.md`, or `reports/review_submission_templates.md`.",
        "",
    ]
    _write_text(path, lines)


def _write_submission_declarations(path: Path, generated: str) -> None:
    lines = [
        "# Submission Declarations Template",
        "",
        f"Generated at UTC: {generated}. These statements are placeholders for human completion before journal submission.",
        "",
        "## Data Availability",
        "",
        "The reproducible review package is generated from the frozen PubMed metadata snapshot, local SQLite database, validation files, evidence table, BibTeX file, citation-verification outputs, update-diff outputs, and human review queues listed in `reports/submission_manifest.md`. A human submitter should replace this sentence with the repository, archive, or supplementary-material location required by the target journal.",
        "",
        "## Code Availability",
        "",
        "The code used to generate the review package is contained in the AutoBioSci Sentinel project source tree. A human submitter should provide the repository URL, commit hash, license, and any archival DOI required by the target journal.",
        "",
        "## Funding",
        "",
        "[To be completed by the submitting authors. Do not state that no funding was received unless the authors have verified that claim.]",
        "",
        "## Competing Interests",
        "",
        "[To be completed by the submitting authors. Do not state that there are no competing interests unless the authors have verified that claim.]",
        "",
        "## Author Contributions",
        "",
        "[To be completed by the submitting authors using the target journal's required taxonomy, such as CRediT if applicable.]",
        "",
        "## Ethics Approval",
        "",
        "This metadata-level review package does not involve new human participant enrollment, animal experiments, or wet-lab data generation by the AutoBioSci Sentinel workflow. A human submitter must still verify whether the target journal requires an ethics statement for literature-review manuscripts and must not use this placeholder for any included primary study.",
        "",
        "## AI Assistance Disclosure",
        "",
        "AI-assisted checks were used for mechanical metadata consistency, claim-boundary review, and drafting support. AI output was not treated as independent human full-text eligibility review, study-quality assessment, clinical interpretation, or biological discovery evidence. A human submitter should revise this disclosure to match the target journal's AI-use policy.",
        "",
        "## Review Status Disclosure",
        "",
        "At the time this template was generated, full-text eligibility, final include/exclude decisions, study-quality assessment, and final biological interpretation remained human or venue-dependent gates unless `reports/review_fulltext_queue.csv` and related review files show otherwise.",
        "",
    ]
    _write_text(path, lines)


def _write_submission_templates(path: Path, generated: str) -> None:
    lines = [
        "# Submission Administrative Templates",
        "",
        f"Generated at UTC: {generated}. Draft template only; not submission-ready until completed and approved by the submitting authors.",
        "",
        "This file is an administrative scaffold for target-journal preparation. It does not select a venue, name authors, complete declarations, or convert the review package into a completed full-text systematic review.",
        "",
        "## Target Journal Metadata",
        "",
        "| Field | Value |",
        "| --- | --- |",
        "| Target journal or venue | [TO BE COMPLETED BY AUTHORS] |",
        "| Article type | [TO BE COMPLETED BY AUTHORS] |",
        "| Reporting guideline required by venue | [TO BE COMPLETED BY AUTHORS] |",
        "| Reference style | [TO BE COMPLETED BY AUTHORS] |",
        "| Word limit | [TO BE COMPLETED BY AUTHORS] |",
        "| Figure/table limits | [TO BE COMPLETED BY AUTHORS] |",
        "| AI-use disclosure policy checked | [TO BE COMPLETED BY AUTHORS] |",
        "",
        "## Title Page Template",
        "",
        "| Field | Value |",
        "| --- | --- |",
        "| Manuscript title | [TO BE COMPLETED BY AUTHORS] |",
        "| Running title | [TO BE COMPLETED BY AUTHORS] |",
        "| Author list and order | [TO BE COMPLETED BY AUTHORS] |",
        "| Affiliations | [TO BE COMPLETED BY AUTHORS] |",
        "| Corresponding author | [TO BE COMPLETED BY AUTHORS] |",
        "| Keywords | [TO BE COMPLETED BY AUTHORS] |",
        "| Word count | [TO BE COMPLETED BY AUTHORS] |",
        "| Tables and figures | [TO BE COMPLETED BY AUTHORS] |",
        "",
        "## Cover Letter Skeleton",
        "",
        "[TO BE COMPLETED BY AUTHORS: date, editor name, journal name, manuscript title, author names, and corresponding-author contact details.]",
        "",
        "Dear [TO BE COMPLETED BY AUTHORS],",
        "",
        "We submit [TO BE COMPLETED BY AUTHORS: manuscript title] for consideration as [TO BE COMPLETED BY AUTHORS: article type]. The manuscript should be described according to the completed human-review state of the package. If the full-text and quality gates remain pending, describe it only as an AI-assisted metadata-level review draft package with structured human checkpoints.",
        "",
        "The submission package includes a frozen PubMed metadata snapshot, protocol, evidence table, BibTeX references, citation checks, update-diff routing, claim-boundary audit, PRISMA-oriented pre-submission checklist, and human full-text/quality review queue. AI-assisted checks were used for mechanical consistency only and were not treated as independent human full-text eligibility review, study-quality assessment, clinical interpretation, or biological discovery evidence.",
        "",
        "[TO BE COMPLETED BY AUTHORS: venue fit, novelty, declarations, suggested reviewers if requested by the venue, and any required confirmations.]",
        "",
        "Sincerely,",
        "",
        "[TO BE COMPLETED BY AUTHORS]",
        "",
        "## Required Files Checklist",
        "",
        "- [ ] Main manuscript or review draft formatted for the target venue.",
        "- [ ] Evidence table and supplementary review files selected for submission or archive.",
        "- [ ] References formatted in the target venue style.",
        "- [ ] Author declarations completed in `reports/review_submission_declarations.md` or venue forms.",
        "- [ ] Full-text and quality/risk-of-bias gates completed or explicitly declared not applicable.",
        "- [ ] Cover letter completed by authors.",
        "- [ ] Title page completed by authors.",
        "",
        "## Claim Boundary Statement",
        "",
        "Allowed before human full-text completion: AI-assisted metadata-level review draft package, frozen PubMed snapshot, citation checks, evidence table, update routing, and structured human checkpoints.",
        "",
        "Not allowed before human/venue gates are complete: completed systematic review, completed full-text synthesis, quality-assessed evidence base, clinical recommendation, treatment efficacy, or confirmed biological mechanism.",
        "",
        "## Human Completion Sign-off",
        "",
        "- [ ] Target journal or venue selected by authors.",
        "- [ ] Author list, affiliations, and corresponding author verified.",
        "- [ ] Funding, competing interests, ethics, acknowledgements, and author contributions verified.",
        "- [ ] AI-use disclosure revised to match the target journal policy.",
        "- [ ] Cover letter and title page completed by authors.",
        "- [ ] Final submission package approved by the corresponding author.",
        "",
    ]
    _write_text(path, lines)


def _write_submission_checklist(
    path: Path,
    paths: dict[str, Path],
    validation: dict[str, Any] | None,
    spotcheck: dict[str, Any] | None,
    ai_spotcheck: dict[str, Any] | None,
    generated: str,
) -> None:
    citation_status = _citation_verification_summary(path.parent / "review_citation_verification.json")
    update_status = _review_update_summary(path.parent / "review_update_diff.json")
    fulltext_status = _fulltext_queue_summary(path.parent / "review_fulltext_queue.csv")
    test_status = os.environ.get("AUTOBIOSCI_TEST_STATUS", "not recorded; run `python -m pytest` before submission")
    missing = [name for name, file_path in paths.items() if name != "submission_checklist" and not file_path.exists()]
    package_status = "PASS" if not missing else f"FAIL: missing {', '.join(missing)}"
    record_count = len(_read_review_records_jsonl(paths["records"]))
    search_status = _search_strategy_status(path.parent / "review_search_strategy.json", record_count)
    coverage_status = _search_coverage_status(path.parent / "review_search_strategy.json")
    inventory_status = _search_inventory_status(path.parent / "review_search_coverage.json")
    lines = [
        "# Review Submission Checklist",
        "",
        f"Generated at UTC: {generated}. This is the human sign-off gate for the recurring review package.",
        "",
        "## Current Verdict",
        "",
        (
            "Ready for human submission review as a metadata-level scoping-review draft package; not ready to submit as "
            "a completed full-text systematic review or biological synthesis until the human and venue-dependent gates "
            "below are completed."
        ),
        "",
        "## Machine Gates",
        "",
        "| Gate | Status | Evidence |",
        "| --- | --- | --- |",
        f"| Package files present | {package_status} | `{paths['submission_manifest'].as_posix()}` |",
        f"| Test suite | {test_status} | `python -m pytest` |",
        f"| Validation labels | {_review_validation_status(validation, expected_records=record_count)} | `reports/validation_metrics.md` |",
        f"| AI-assisted consensus | {_review_spotcheck_status(ai_spotcheck)} | `reports/ai_consensus_spotcheck_summary.md` |",
        f"| Search strategy documentation | {search_status['label']} | `reports/review_search_strategy.md` and `reports/review_search_strategy.json` |",
        f"| Search coverage gate | {coverage_status['label']} | `reports/review_search_strategy.json` |",
        f"| Search coverage inventory | {inventory_status['label']} | `reports/review_search_coverage.md`, `reports/review_search_coverage.json`, and `reports/review_search_coverage.csv` |",
        f"| Citation verification | {citation_status['label']} | `reports/review_citation_verification.md` |",
        f"| Periodic update diff | {update_status['label']} | `reports/review_update_diff.md` and `reports/human_update_queue.csv` |",
        f"| Claim boundary audit | generated | `{paths['claim_audit'].as_posix()}` |",
        f"| Venue-neutral display-item sources | proposed; reproducible text sources; not final journal artwork | `{paths['display_items'].as_posix()}`, `{paths['display_items_json'].as_posix()}`, `{paths['figure1_flow_source'].as_posix()}`, `{paths['figure2_theme_distribution_csv'].as_posix()}`, and `{paths['figure2_theme_distribution_md'].as_posix()}` |",
        "",
        "## Human Gates",
        "",
        "| Gate | Current status | Required before completed-review claims |",
        "| --- | --- | --- |",
        f"| Independent human spot-check | {_review_spotcheck_status(spotcheck)} | Complete reviewer rows and adjudicate disagreements if the venue requires independent human checking. |",
        f"| Full-text eligibility and final inclusion | {fulltext_status['label']} | Fill `reports/review_fulltext_queue.csv` using `reports/review_fulltext_instructions.md`. |",
        "| Evidence table verification | pending human full-text review | Confirm extraction fields against included full texts before final thematic synthesis. |",
        "| Risk-of-bias or quality assessment | guidance available; human completion pending | Use `reports/review_quality_assessment_guidance.md` with `reports/review_fulltext_queue.csv` if required by the review type or target venue. |",
        "| Author declarations | placeholders only | Complete funding, competing interests, author contributions, ethics, data/code availability, and AI-use disclosure. |",
        "| Venue formatting | not selected | Apply target journal word limits, reference style, figure/table rules, reporting checklist, and AI policy. |",
        "| Cover letter and title page | template generated; human completion required | Complete `reports/review_submission_templates.md` after target journal and author list are known. |",
        "| Formal PRISMA item mapping | generated as conservative pre-submission audit | Complete venue-specific PRISMA/PRISMA-ScR interpretation before claiming checklist compliance. |",
        "",
        "## Claim Boundary",
        "",
        "- Allowed now: reproducible metadata-level review draft package, evidence table, BibTeX, citation checks, update routing, and AI-assisted mechanical consistency checks.",
        "- Not allowed yet: completed systematic review, completed full-text synthesis, quality-assessed evidence base, clinical recommendation, treatment efficacy, or confirmed biological mechanism.",
        "- AI consensus may support mechanical metadata checks; it is not independent human full-text review.",
        "",
        "## Final Human Sign-off",
        "",
        "- [ ] Target journal or venue selected.",
        "- [ ] Full-text queue completed and reviewed.",
        "- [ ] Final include/exclude decisions signed off.",
        "- [ ] Evidence table checked against included full texts.",
        "- [ ] Required quality/risk-of-bias assessment completed or documented as not applicable.",
        "- [ ] Declarations completed by submitting authors.",
        "- [ ] Draft, references, tables, and reporting checklist formatted for the target venue.",
        "- [ ] Cover letter and title page completed from template if required.",
        "",
    ]
    _write_text(path, lines)


def _write_prisma_checklist(
    path: Path,
    validation: dict[str, Any] | None,
    spotcheck: dict[str, Any] | None,
    ai_spotcheck: dict[str, Any] | None,
    generated: str,
) -> None:
    fulltext_status = _fulltext_queue_summary(path.parent / "review_fulltext_queue.csv")
    citation_status = _citation_verification_summary(path.parent / "review_citation_verification.json")
    update_status = _review_update_summary(path.parent / "review_update_diff.json")
    rows = [
        (
            "Title and abstract",
            "Identify the review as a metadata-level living scoping-review draft and summarize methods/results.",
            "partial",
            "`reports/review_draft.md` abstract",
            "Final review type and venue wording must be selected by submitters.",
            "Revise title/abstract after full-text and target-journal decisions.",
        ),
        (
            "Rationale and objectives",
            "Explain why recurring surveillance is needed and define the review topic.",
            "met",
            "`reports/review_protocol.md`; `reports/review_draft.md` Introduction",
            "None for metadata-level package; venue may require a narrower question format.",
            "Tighten objective wording for the chosen venue.",
        ),
        (
            "Eligibility criteria",
            "State inclusion/exclusion boundaries and evidence limits.",
            "partial",
            "`reports/review_protocol.md` Minimum Inclusion/Exclusion Criteria",
            "Full-text eligibility and final include/exclude decisions are not complete.",
            "Complete `reports/review_fulltext_queue.csv` before completed-review claims.",
        ),
        (
            "Information sources and search strategy",
            "Report source, query, and update snapshot boundary.",
            "partial",
            "`reports/review_search_strategy.md`; `reports/review_search_strategy.json`; `reports/review_protocol.md` Topic Freeze",
            "Dedicated PubMed-only metadata-level search strategy generated; raw PubMed hit count, librarian review, multi-database search, and full-text search remain unavailable or pending.",
            "Add librarian-reviewed database-specific appendices only if expanding beyond PubMed or required by the target venue.",
        ),
        (
            "Selection process",
            "Separate AI-assisted metadata checks from human decisions.",
            "partial",
            "`reports/validation_template.csv`; `reports/ai_consensus_spotcheck_summary.md`; `reports/review_fulltext_queue.csv`",
            f"Human full-text status: {fulltext_status['label']}. Human spot-check: {_review_spotcheck_status(spotcheck)}.",
            "Record human full-text decisions and adjudication.",
        ),
        (
            "Data collection and data items",
            "Export metadata fields, citation keys, validation labels, and accession fields.",
            "partial",
            "`reports/review_evidence_table.csv`; `reports/review_records_frozen.jsonl`",
            "Extraction is metadata-level; full-text span verification is not present.",
            "Verify extraction fields against included full texts.",
        ),
        (
            "Risk of bias or study quality",
            "Assess individual study quality if required by the review type.",
            "partial",
            "`reports/review_quality_assessment_guidance.md`; `reports/review_fulltext_queue.csv`",
            "Guidance and queue fields exist, but no human quality or risk-of-bias assessment has been completed.",
            "Select and apply a venue-appropriate quality tool if needed; keep status pending until human completion.",
        ),
        (
            "Synthesis methods",
            "Describe how evidence is summarized.",
            "partial",
            "`reports/review_draft.md` Thematic Metadata Map and Metadata-Level Thematic Synthesis; `reports/review_display_items.md`",
            "Synthesis and display items are title/abstract metadata-level and not full-text biological synthesis.",
            "Revise synthesis and captions after full-text review.",
        ),
        (
            "Study selection flow",
            "Show record counts and update routing.",
            "partial",
            "`reports/review_prisma_flow.md`; `reports/review_prisma_flow.json`; `reports/review_update_diff.md`",
            "Formal PubMed-only metadata-level flow is generated; human full-text and final exclusion counts are pending.",
            "Complete human full-text review before reporting final included/excluded study counts.",
        ),
        (
            "Results and included studies",
            "Present included metadata-level records and citation coverage.",
            "partial",
            "`reports/review_evidence_table.csv`; `reports/review_citation_verification.md`",
            f"Citation verification: {citation_status['label']}; final included studies depend on full-text review.",
            "Lock final included set after human review.",
        ),
        (
            "Discussion and limitations",
            "State limitations, automation boundary, and forbidden claims.",
            "met",
            "`reports/review_draft.md` Limitations; `reports/review_claim_audit.md`; `reports/review_forbidden_terms.yaml`",
            "Venue may require different limitation placement or language.",
            "Reword for target journal without expanding claims.",
        ),
        (
            "Registration, protocol, and availability",
            "Provide protocol, frozen files, commands, declarations, and data/code availability placeholders.",
            "partial",
            "`reports/review_protocol.md`; `reports/submission_manifest.md`; `reports/review_submission_declarations.md`",
            "No external registration/archive URL or author-completed declarations are present.",
            "Add repository/archive/registration details before submission if required.",
        ),
        (
            "Automation and AI disclosure",
            "Disclose AI-assisted checks and keep them separate from human review.",
            "met",
            "`reports/review_submission_declarations.md`; `reports/review_submission_checklist.md`",
            f"AI consensus status: {_review_spotcheck_status(ai_spotcheck)}.",
            "Adapt disclosure to the target journal policy.",
        ),
        (
            "Living review update status",
            "Document snapshot comparison and records needing human update review.",
            "met" if update_status["status"] in {"pass", "initial_snapshot"} else "partial",
            "`reports/review_update_diff.md`; `reports/human_update_queue.csv`",
            update_status["label"],
            "Review queued changes before updating final claims.",
        ),
    ]
    lines = [
        "# PRISMA-Oriented Reporting Checklist",
        "",
        f"Generated at UTC: {generated}. This is a conservative PRISMA/PRISMA-ScR-oriented mapping for the metadata-level review package; it is not a claim of PRISMA compliance.",
        "",
        "Status values: `met` means the current package has a metadata-level reporting artifact; `partial` means the artifact exists but human or venue work remains; `missing` means the package has no adequate artifact; `N/A` means the item is not applicable to this bounded package.",
        "",
        "| Reporting area | Item | Status | Evidence location | Human/venue gap | Next correction |",
        "| --- | --- | --- | --- | --- | --- |",
        *[
            (
                f"| {_table_cell(area)} | {_table_cell(item)} | {status} | {evidence} | "
                f"{_table_cell(gap)} | {_table_cell(next_step)} |"
            )
            for area, item, status, evidence, gap, next_step in rows
        ],
        "",
        "## Boundary Statement",
        "",
        "This checklist supports pre-submission reporting audit only. It does not replace human full-text eligibility review, final included-study confirmation, study-quality assessment, author declarations, target-journal formatting, or a venue-specific PRISMA/PRISMA-ScR checklist.",
        "",
    ]
    _write_text(path, lines)




def write_spotcheck_summary(
    spotcheck_path: str | Path,
    validation_path: str | Path,
    output_path: str | Path,
    title: str = "Human Spot-check Summary",
) -> dict[str, Any]:
    spotcheck_rows = _read_spotcheck_rows(spotcheck_path)
    validation_rows = {row["pmid"]: row for row in _read_validation_rows(validation_path)}
    pending: list[str] = []
    missing_validation: list[str] = []
    disagreements: list[dict[str, str]] = []
    completed = 0
    agreed_rows = 0
    disagreed_rows = 0

    for row in spotcheck_rows:
        pmid = row.get("pmid", "")
        if not _spotcheck_completed(row):
            pending.append(pmid)
            continue
        completed += 1
        validation_row = validation_rows.get(pmid)
        if validation_row is None:
            missing_validation.append(pmid)
            disagreed_rows += 1
            continue
        row_disagreements = _spotcheck_disagreements(pmid, validation_row, row)
        if row_disagreements:
            disagreements.extend(row_disagreements)
            disagreed_rows += 1
        else:
            agreed_rows += 1

    summary = {
        "total_records": len(spotcheck_rows),
        "completed_records": completed,
        "pending_records": len(pending),
        "agreed_records": agreed_rows,
        "disagreed_records": disagreed_rows,
        "field_disagreements": len(disagreements),
        "missing_validation_records": missing_validation,
        "pending_pmids": pending,
        "disagreements": disagreements,
    }
    lines = [
        f"# {title}",
        "",
        f"- Spot-check records: {summary['total_records']}",
        f"- Completed reviewer rows: {summary['completed_records']}/{summary['total_records']}",
        f"- Pending reviewer rows: {summary['pending_records']}",
        f"- Row agreements: {summary['agreed_records']}",
        f"- Row disagreements: {summary['disagreed_records']}",
        f"- Field disagreements: {summary['field_disagreements']}",
        "",
        "## Disagreements",
        "",
        *(
            ["Not available until reviewer rows are completed."]
            if completed == 0
            else _spotcheck_disagreement_lines(disagreements)
        ),
        "",
        "## Pending Rows",
        "",
        *_spotcheck_pending_lines(pending),
        "",
        "## Missing Validation Rows",
        "",
        *_spotcheck_pending_lines(missing_validation),
        "",
    ]
    output = Path(output_path)
    _write_text(output, lines)
    _write_json(output.with_suffix(".json"), [summary])
    return summary


def validation_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    total = len(rows)
    fully_annotated = sum(1 for row in rows if _has_relevance_label(row) and _has_accession_label(row))
    pending = total - fully_annotated
    relevance_denominator = [row for row in rows if _clean(row.get("manual_relevant")) in {"yes", "no"}]
    relevance_top10 = [
        row
        for row in relevance_denominator
        if _int_or_none(row.get("rank_position")) is not None and int(row["rank_position"]) <= 10
    ]
    accession_counts = {label: 0 for label in ["TP", "FP", "TN", "FN", "unclear"]}
    for row in rows:
        label = _clean(row.get("accession_eval_label")).upper()
        if label in {"TP", "FP", "TN", "FN"}:
            accession_counts[label] += 1
        elif label == "UNCLEAR":
            accession_counts["unclear"] += 1

    return {
        "total_records": total,
        "fully_annotated_records": fully_annotated,
        "pending_records": pending,
        "unclear_relevance_records": sum(1 for row in rows if _clean(row.get("manual_relevant")) == "unclear"),
        "top10_coverage": _top10_coverage(rows),
        "precision_at_10": _yes_ratio(relevance_top10, "manual_relevant"),
        "overall_relevance_precision": _yes_ratio(relevance_denominator, "manual_relevant"),
        "accession_candidate_precision": _ratio(accession_counts["TP"], accession_counts["TP"] + accession_counts["FP"]),
        "accession_recall": _ratio(accession_counts["TP"], accession_counts["TP"] + accession_counts["FN"]),
        "accession_counts": accession_counts,
        "audit": validation_audit(rows),
        "status": (
            "AI-assisted validation-label coverage is complete; interpret metrics using judged-row denominators. Independent human review is tracked separately."
            if pending == 0
            else "AI-assisted validation-label coverage is incomplete; metrics are provisional until all validation rows are annotated. Independent human review is tracked separately."
        ),
    }


def _read_validation_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in VALIDATION_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"validation CSV missing required columns: {', '.join(missing)}")
        return [dict(row) for row in reader]


def _read_spotcheck_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"pmid", *SPOTCHECK_REQUIRED_REVIEWER_FIELDS}
        missing = [column for column in required if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"spot-check CSV missing required columns: {', '.join(sorted(missing))}")
        return [dict(row) for row in reader]


def _spotcheck_completed(row: dict[str, str]) -> bool:
    return all(_clean(row.get(field)) for field in SPOTCHECK_REQUIRED_REVIEWER_FIELDS)


def _spotcheck_disagreements(
    pmid: str,
    validation_row: dict[str, str],
    spotcheck_row: dict[str, str],
) -> list[dict[str, str]]:
    disagreements: list[dict[str, str]] = []
    for validation_field, reviewer_field in SPOTCHECK_COMPARE_FIELDS:
        validation_value = _normalize_spotcheck_value(validation_field, validation_row.get(validation_field))
        reviewer_value = _normalize_spotcheck_value(validation_field, spotcheck_row.get(reviewer_field))
        if validation_value != reviewer_value:
            disagreements.append(
                {
                    "pmid": pmid,
                    "field": validation_field,
                    "validation": validation_value,
                    "reviewer": reviewer_value,
                }
            )
    return disagreements


def _normalize_spotcheck_value(field: str, value: str | None) -> str:
    text = (value or "").strip()
    if field in {"manual_accessions", "reviewer_accessions"}:
        return ";".join(sorted(part.strip().upper() for part in text.split(";") if part.strip()))
    if field == "accession_eval_label":
        return text.upper()
    return text.lower()


def _spotcheck_disagreement_lines(disagreements: list[dict[str, str]]) -> list[str]:
    if not disagreements:
        return ["No reviewer disagreements recorded."]
    return [
        "| PMID | Field | Validation | Reviewer |",
        "| --- | --- | --- | --- |",
        *[
            (
                f"| {item['pmid']} | {item['field']} | {_table_cell(item['validation']) or 'blank'} | "
                f"{_table_cell(item['reviewer']) or 'blank'} |"
            )
            for item in disagreements
        ],
    ]


def _spotcheck_pending_lines(pmids: list[str]) -> list[str]:
    if not pmids:
        return ["None."]
    return [f"- {pmid}" for pmid in pmids]


def validation_audit(rows: list[dict[str, str]]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    allowed = {
        "manual_relevant": {"", "yes", "no", "unclear"},
        "manual_topic_match": {"", "yes", "no", "unclear"},
        "manual_transcriptomics": {"", "yes", "no", "unclear"},
        "manual_rnaseq_or_scrnaseq": {"", "bulk_rnaseq", "scrnaseq", "both", "other", "none", "unclear"},
        "manual_biomarker_focus": {"", "yes", "no", "unclear"},
        "manual_accession_present": {"", "yes", "no", "unclear"},
        "tool_accession_candidate_present": {"yes", "no"},
        "accession_match_status": {"", "exact", "partial", "wrong", "missed", "not_applicable", "unclear"},
        "accession_eval_label": {"", "TP", "FP", "TN", "FN", "UNCLEAR"},
        "error_category": {
            "",
            "irrelevant_topic",
            "non_transcriptomics",
            "no_accession",
            "missed_accession",
            "wrong_accession",
            "ambiguous_abstract",
            "metadata_limit",
            "other",
        },
    }
    expected_accession = {
        "TP": ("yes", "yes"),
        "FP": ("yes", "no"),
        "TN": ("no", "no"),
        "FN": ("no", "yes"),
    }
    for row in rows:
        pmid = row.get("pmid", "")
        for field, values in allowed.items():
            value = (row.get(field) or "").strip()
            normalized = value.upper() if field == "accession_eval_label" else value.lower()
            if normalized not in values:
                issues.append({"pmid": pmid, "field": field, "message": f"unexpected value: {value}"})
        label = (row.get("accession_eval_label") or "").strip().upper()
        if label in expected_accession:
            expected_tool, expected_manual = expected_accession[label]
            tool = _clean(row.get("tool_accession_candidate_present"))
            manual = _clean(row.get("manual_accession_present"))
            if tool and tool != expected_tool:
                issues.append({"pmid": pmid, "field": "accession_eval_label", "message": f"{label} conflicts with tool_accession_candidate_present={tool}"})
            if manual and manual != expected_manual:
                issues.append({"pmid": pmid, "field": "accession_eval_label", "message": f"{label} conflicts with manual_accession_present={manual}"})
            if not manual:
                issues.append({"pmid": pmid, "field": "manual_accession_present", "message": f"{label} requires manual_accession_present"})
    return {"issue_count": len(issues), "issues": issues}


def _citation_key(paper: dict[str, Any]) -> str:
    year = _publication_year(paper.get("pub_date", "")) or "nd"
    pmid = str(paper.get("pmid", "pmid")).strip() or "pmid"
    title_word = ""
    for part in str(paper.get("title", "")).replace("-", " ").split():
        cleaned = "".join(ch for ch in part if ch.isalnum())
        if cleaned:
            title_word = cleaned.lower()
            break
    return f"pmid{pmid}_{year}_{title_word or 'record'}"


def _bibtex_value(value: str) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("{", "(").replace("}", ")")


def _review_metric_lines(
    validation: dict[str, Any] | None,
    ai_spotcheck: dict[str, Any] | None,
    spotcheck: dict[str, Any] | None,
    citation_status: dict[str, Any] | None = None,
    update_status: dict[str, Any] | None = None,
    fulltext_status: dict[str, Any] | None = None,
) -> list[str]:
    if not validation:
        return ["Validation metrics are not available for this snapshot."]
    citation_label = citation_status["label"] if citation_status else "not run"
    update_label = update_status["label"] if update_status else "not run"
    fulltext_label = fulltext_status["label"] if fulltext_status else "not generated"
    return [
        (
            f"Metadata validation covered {validation['fully_annotated_records']}/{validation['total_records']} record(s), "
            f"with Precision@10: {_format_ratio(validation['precision_at_10'])}, overall relevance: "
            f"{_format_ratio(validation['overall_relevance_precision'])}, metadata-visible accession precision: "
            f"{_format_ratio(validation['accession_candidate_precision'])}, and metadata-visible accession recall: "
            f"{_format_ratio(validation['accession_recall'])}. The validation audit reported "
            f"{validation['audit']['issue_count']} issue(s)."
        ),
        "",
        (
            f"AI-assisted consensus spot-check status was {_review_spotcheck_status(ai_spotcheck)}, while the independent "
            f"human spot-check status was {_review_spotcheck_status(spotcheck)}. Citation verification was {citation_label}. "
            f"The recurring update diff was {update_label}. Full-text and quality gate status was {fulltext_label}."
        ),
    ]


def _human_topic_label(topics: list[Any]) -> str:
    if not topics:
        return "the configured biomedical topic"
    labels = []
    for topic in topics:
        keywords = list(getattr(topic, "core_keywords", []) or [])
        if {"cancer immunotherapy", "transcriptomics"}.issubset(set(keywords)):
            labels.append("cancer immunotherapy transcriptomics")
        else:
            labels.append(" ".join(str(getattr(topic, "name", "configured topic")).replace("_", " ").split()))
    return ", ".join(labels)


def _review_theme_rows(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for paper in papers:
        grouped.setdefault(_review_theme_label(paper), []).append(paper)
    return [
        {"theme": theme, "papers": rows}
        for theme, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _review_theme_label(paper: dict[str, Any]) -> str:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    if "multi-omics" in text or "multiomics" in text or "metabolic" in text:
        return "Multi-omics and computational modeling"
    if "spatial" in text:
        return "Spatial transcriptomics and tissue context"
    if "single-cell" in text or "single cell" in text or "scrna" in text:
        return "Single-cell tumor microenvironment atlases"
    if any(term in text for term in ["signature", "biomarker", "prognosis", "predict", "response"]):
        return "Biomarker and response signatures"
    return "Other transcriptomics surveillance records"


def _cancer_type_hint(paper: dict[str, Any]) -> str:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    hints = [
        ("ovarian", "ovarian cancer"),
        ("hepatocellular", "hepatocellular carcinoma"),
        ("liver cancer", "liver cancer"),
        ("breast", "breast cancer"),
        ("nasopharyngeal", "nasopharyngeal carcinoma"),
        ("bladder", "bladder cancer"),
        ("melanoma", "melanoma"),
        ("glioma", "glioma"),
        ("colorectal", "colorectal cancer"),
        ("gastric", "gastric cancer"),
        ("lung", "lung cancer"),
        ("pan-cancer", "pan-cancer"),
    ]
    return next((label for needle, label in hints if needle in text), "not specified in metadata")


def _immunotherapy_context_hint(paper: dict[str, Any]) -> str:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    if "checkpoint" in text or "pd-1" in text or "pd-l1" in text or "ctla" in text:
        return "checkpoint inhibitor context"
    if "immunotherapy" in text:
        return "immunotherapy context"
    if "immune infiltration" in text or "immune-cold" in text or "immune contexture" in text:
        return "immune microenvironment context"
    if "tumor microenvironment" in text:
        return "tumor microenvironment context"
    return "not specified in metadata"


def _assay_type_hint(paper: dict[str, Any]) -> str:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    if "spatial" in text:
        return "spatial transcriptomics"
    if "single-cell" in text or "single cell" in text or "scrna" in text:
        return "single-cell RNA-seq"
    if "rna-seq" in text or "rnaseq" in text:
        return "RNA-seq"
    if "multi-omics" in text or "multiomics" in text:
        return "multi-omics"
    if "transcriptomic" in text or "transcriptome" in text:
        return "transcriptomics"
    return "not specified in metadata"


def _metadata_summary(paper: dict[str, Any]) -> str:
    title = " ".join(str(paper.get("title", "")).split())
    if not title:
        return "No title available in cached metadata."
    return f"PubMed title reports: {title}"


def _review_theme_table_lines(theme_rows: list[dict[str, Any]]) -> list[str]:
    if not theme_rows:
        return ["| No included records | 0 | - |"]
    lines = []
    for row in theme_rows:
        examples = ", ".join(_citation_key(paper) for paper in row["papers"][:3]) or "-"
        lines.append(f"| {row['theme']} | {len(row['papers'])} | {_table_cell(examples)} |")
    return lines


def _review_preview_line(rank: int, paper: dict[str, Any], validation: dict[str, str]) -> str:
    label = validation.get("manual_relevant", "") or "unvalidated"
    accessions = ", ".join(paper.get("accessions") or []) or "None"
    return (
        f"| {rank} | {paper.get('pmid', '')} | {_citation_key(paper)} | "
        f"{_table_cell(paper.get('title', ''))} | {_table_cell(paper.get('journal', ''))} | "
        f"{_publication_year(paper.get('pub_date', ''))} | {label} | {_table_cell(accessions)} |"
    )


def _metadata_selection_flow_table_lines(flow: dict[str, Any]) -> list[str]:
    final_include = (
        f"{flow.get('final_include_yes', 0)} yes; {flow.get('final_include_no', 0)} no; "
        f"{flow.get('final_include_unclear', 0)} unclear; {flow.get('final_include_pending', 0)} pending"
    )
    return [
        f"| Deduplicated PubMed records | {flow.get('deduplicated_records', 0)} | SQLite PMID-primary-key snapshot |",
        f"| Metadata-validated records | {flow.get('metadata_validated_records', 0)} | Local validation rows with relevance labels |",
        f"| Metadata-relevant records | {flow.get('metadata_relevant_records', 0)} | `manual_relevant=yes`; not final included studies |",
        f"| Metadata-irrelevant records | {flow.get('metadata_irrelevant_records', 0)} | `manual_relevant=no`; not final human full-text exclusions |",
        f"| Metadata-unclear records | {flow.get('metadata_unclear_records', 0)} | `manual_relevant=unclear` |",
        f"| Records routed to full-text queue | {flow.get('fulltext_queue_records', 0)} | Metadata-level non-irrelevant records needing human review |",
        f"| Full-text checked records | {flow.get('fulltext_checked_records', 0)} | Human reviewer field; pending in current package |",
        f"| Human-verified full-text records | {flow.get('human_verified_records', 0)} | `human_verified=yes` |",
        f"| Final include decisions | {final_include} | Human completion required |",
    ]


def _metadata_theme_synthesis_lines(evidence_path: str | Path, fulltext_status: dict[str, Any]) -> list[str]:
    rows = [
        row
        for row in _read_csv_rows(evidence_path)
        if _clean(row.get("included_after_metadata_validation")) == "yes"
    ]
    if not rows:
        return ["No metadata-relevant evidence-table rows are available for thematic synthesis."]
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        theme = row.get("review_theme") or "Uncategorized metadata records"
        grouped.setdefault(theme, []).append(row)
    lines = [
        (
            "These themes are derived from PubMed metadata and local evidence-table labels; they do not represent "
            "full-text-confirmed findings or final included-study conclusions. The denominator is "
            f"{len(rows)} metadata-relevant record(s) routed to the full-text queue. Current human gate status is "
            f"{fulltext_status['label']}."
        ),
        "",
    ]
    for theme, theme_rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        examples = "; ".join(
            f"{row.get('citation_key') or 'no_citation_key'} (PMID {row.get('pmid') or 'not recorded'})"
            for row in theme_rows[:4]
        )
        accession_count = sum(
            1
            for row in theme_rows
            if _clean(row.get("dataset_accession_visible")) == "yes" or str(row.get("accession_ids", "")).strip()
        )
        lines.append(
            f"{theme} accounted for {len(theme_rows)}/{len(rows)} metadata-relevant record(s). Inspection pointers include "
            f"{examples}. Common metadata hints were cancer context: "
            f"{_metadata_hint_summary(theme_rows, 'metadata_cancer_type_hint')}; immunotherapy context: "
            f"{_metadata_hint_summary(theme_rows, 'metadata_immunotherapy_context_hint')}; and assay context: "
            f"{_metadata_hint_summary(theme_rows, 'metadata_assay_type_hint')}. Metadata-visible accession candidates were "
            f"recorded for {accession_count} record(s). These are title/abstract-level signals for human review, not "
            "final biological conclusions."
        )
        lines.append("")
    return lines[:-1]


def _metadata_hint_summary(rows: list[dict[str, str]], field: str, limit: int = 3) -> str:
    values = [
        value
        for row in rows
        if (value := str(row.get(field, "")).strip())
        and value.lower() != "not specified in metadata"
    ]
    if not values:
        return "not specified in metadata"
    counts = Counter(values)
    return ", ".join(
        f"{value} ({count})"
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    )


def _reference_metadata_table_lines(
    papers: list[dict[str, Any]],
    citation_verification: dict[str, dict[str, str]],
) -> list[str]:
    if not papers:
        return ["| - | - | - | - | - | - | No metadata-included records |"]
    lines = []
    for paper in papers:
        pmid = str(paper.get("pmid", ""))
        verification = citation_verification.get(pmid, {})
        status = verification.get("status") or "not_run"
        warning = verification.get("warning") or verification.get("error") or ""
        verification_label = f"{status}: {warning}" if warning else status
        lines.append(
            f"| {_citation_key(paper)} | {pmid} | {_table_cell(paper.get('doi') or 'not recorded')} | "
            f"{_table_cell(paper.get('journal', ''))} | {_publication_year(paper.get('pub_date', ''))} | "
            f"{_table_cell(verification_label)} | {_table_cell(paper.get('title', ''))} |"
        )
    return lines


def _review_validation_status(validation: dict[str, Any] | None, expected_records: int | None = None) -> str:
    if not validation:
        return "not generated"
    total = int(validation["total_records"])
    status = f"{validation['fully_annotated_records']}/{total}; audit issues {validation['audit']['issue_count']}"
    if expected_records is None or expected_records == total:
        return status
    if expected_records > total:
        return f"{status}; frozen snapshot records {expected_records}; validation rows missing for {expected_records - total}"
    return f"{status}; frozen snapshot records {expected_records}; validation rows exceed snapshot by {total - expected_records}"


def _review_spotcheck_status(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "not generated"
    if summary["completed_records"] == 0:
        return f"0/{summary['total_records']} completed; disagreements not available until review is completed"
    return (
        f"{summary['completed_records']}/{summary['total_records']} completed; "
        f"{summary['field_disagreements']} field disagreement(s)"
    )


def _citation_verification_summary(path: str | Path) -> dict[str, Any]:
    verification_path = Path(path)
    if not verification_path.exists():
        return {
            "status": "not_run",
            "label": "not run",
            "failed_records": 0,
        }
    rows = json.loads(verification_path.read_text(encoding="utf-8"))
    summary = rows[0] if rows else {}
    total = summary.get("total_records", 0)
    verified = summary.get("verified_records", 0)
    pubmed_unresolved = summary.get("pubmed_verified_unresolved_records", 0)
    failed = summary.get("failed_records", 0)
    network = summary.get("network_error_records", 0)
    return {
        "status": "complete" if total and not failed and not network else "incomplete",
        "label": f"{verified}/{total} resolver-verified; PubMed-confirmed unresolved {pubmed_unresolved}; failed {failed}; network errors {network}",
        "failed_records": failed,
    }


def _review_update_summary(path: str | Path) -> dict[str, Any]:
    diff_path = Path(path)
    empty = {
        "status": "not_run",
        "label": "FAIL: update diff not run",
        "previous_snapshot_id": "",
        "current_snapshot_id": "",
        "self_comparison": False,
        "old_records": 0,
        "new_records": 0,
        "added_records": 0,
        "removed_records": 0,
        "unchanged_records": 0,
        "metadata_changed_records": 0,
        "labels_carried_forward_count": 0,
        "needs_human_review_count": 0,
        "human_update_queue_count": 0,
        "update_diff_file": "",
        "human_update_queue_file": "",
        "draft_text": "No previous-snapshot diff has been generated yet.",
    }
    if not diff_path.exists():
        return empty
    rows = json.loads(diff_path.read_text(encoding="utf-8"))
    summary = rows[0] if rows else {}
    result = {**empty, **{key: summary.get(key, empty[key]) for key in empty if key not in {"status", "label", "draft_text"}}}
    queue_path = Path(str(result["human_update_queue_file"] or diff_path.parent / "human_update_queue.csv"))
    queue_count = _count_csv_data_rows(queue_path)
    needs_review = int(result["needs_human_review_count"] or 0)
    result["human_update_queue_count"] = queue_count
    stats_total = int(result["added_records"] or 0) + int(result["removed_records"] or 0) + int(result["unchanged_records"] or 0) + int(result["metadata_changed_records"] or 0)
    if not queue_path.exists() or queue_count != needs_review or stats_total != int(result["new_records"] or 0) + int(result["removed_records"] or 0):
        result["status"] = "fail"
    elif int(result["old_records"] or 0) == 0 and int(result["new_records"] or 0) > 0:
        result["status"] = "initial_snapshot"
    elif result["self_comparison"]:
        result["status"] = "self_check"
    elif needs_review:
        result["status"] = "warn"
    else:
        result["status"] = "pass"
    prefix = {
        "pass": "PASS",
        "warn": "WARN",
        "fail": "FAIL",
        "initial_snapshot": "INITIAL",
        "self_check": "SELF-CHECK",
    }[result["status"]]
    result["label"] = (
        f"{prefix}: {result['added_records']} added; {result['metadata_changed_records']} metadata-changed; "
        f"{result['removed_records']} removed; {needs_review} need human update review; queue rows {queue_count}"
    )
    if result["status"] == "initial_snapshot":
        result["draft_text"] = "Initial snapshot; no prior update comparison is available yet."
    elif result["status"] == "self_check":
        result["draft_text"] = (
            "This update diff is a self-check against the same snapshot path. It verifies that the diff machinery runs, "
            "but it is not evidence of a completed periodic update comparison against an independent previous snapshot."
        )
    else:
        result["draft_text"] = (
            f"Compared with the previous frozen snapshot, this package has {result['added_records']} added record(s), "
            f"{result['metadata_changed_records']} metadata-changed record(s), {result['removed_records']} removed record(s), "
            f"and {needs_review} record(s) routed to `reports/human_update_queue.csv` for human update review."
        )
    return result


def _count_csv_data_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _fulltext_queue_summary(path: str | Path) -> dict[str, Any]:
    queue_path = Path(path)
    if not queue_path.exists():
        return {
            "status": "not_run",
            "label": "not generated",
            "total_records": 0,
            "fulltext_completed_count": 0,
            "final_include_pending_count": 0,
            "human_verified_records": 0,
            "pending_records": 0,
        }
    rows = _read_csv_rows(queue_path)
    fulltext_completed = sum(1 for row in rows if _clean(row.get("full_text_status")))
    final_include_pending = sum(1 for row in rows if not _clean(row.get("final_include")))
    verified = sum(1 for row in rows if _clean(row.get("human_verified")) == "yes")
    pending = len(rows) - verified
    return {
        "status": "complete" if rows and pending == 0 else "pending",
        "label": (
            f"{fulltext_completed}/{len(rows)} full-text checked; "
            f"{verified}/{len(rows)} human-verified; {final_include_pending} final-include pending"
        ),
        "total_records": len(rows),
        "fulltext_completed_count": fulltext_completed,
        "final_include_pending_count": final_include_pending,
        "human_verified_records": verified,
        "pending_records": pending,
    }


def _search_strategy_status(path: str | Path, expected_records: int) -> dict[str, Any]:
    strategy_path = Path(path)
    if not strategy_path.exists():
        return {
            "status": "fail",
            "label": "FAIL: search strategy not generated",
            "problems": ["search strategy file is missing"],
            "warnings": [],
        }
    rows = json.loads(strategy_path.read_text(encoding="utf-8"))
    summary = rows[0] if rows else {}
    problems: list[str] = []
    warnings: list[str] = []
    if not str(summary.get("exact_pubmed_query", "")).strip():
        problems.append("missing exact PubMed query")
    if summary.get("records_in_frozen_snapshot") != expected_records:
        problems.append("frozen snapshot count conflicts with package records")
    if not summary.get("raw_count_available"):
        warnings.append("raw PubMed hit count unavailable")
    coverage = summary.get("search_coverage_gate") or {}
    if coverage.get("status") == "warn":
        warnings.append("latest PubMed retrieval is retmax-limited/partial")
    elif coverage.get("status") == "unknown":
        warnings.append("search coverage unavailable")
    if summary.get("librarian_peer_reviewed") is False:
        warnings.append("not librarian-reviewed")
    if problems:
        status = "fail"
        label = f"FAIL: {'; '.join(problems)}"
    elif warnings:
        status = "warn"
        label = f"WARN: generated; {'; '.join(warnings)}"
    else:
        status = "pass"
        label = "PASS: generated with query, snapshot count, and command"
    return {
        "status": status,
        "label": label,
        "problems": problems,
        "warnings": warnings,
    }


def _search_coverage_status(path: str | Path) -> dict[str, Any]:
    strategy_path = Path(path)
    empty = {
        "status": "unknown",
        "label": "WARN: search coverage gate not generated",
        "retrieval_truncated_or_partial": True,
        "raw_pubmed_hit_count": None,
        "latest_retrieved_pmids": None,
        "frozen_snapshot_records": 0,
        "frozen_snapshot_records_beyond_latest_retrieval_count": 0,
        "boundary_statement": "The frozen SQLite snapshot cannot be treated as an exhaustive PubMed query corpus because search coverage has not been generated.",
    }
    if not strategy_path.exists():
        return empty
    rows = json.loads(strategy_path.read_text(encoding="utf-8"))
    summary = rows[0] if rows else {}
    gate = summary.get("search_coverage_gate") or {}
    return {**empty, **gate}


def _search_inventory_status(path: str | Path) -> dict[str, Any]:
    inventory_path = Path(path)
    empty = {
        "status": "not_run",
        "label": "WARN: search coverage inventory not generated",
        "unique_esearch_pmid_count": 0,
        "frozen_snapshot_count": 0,
        "missing_from_frozen_count": 0,
        "frozen_not_in_current_query_count": 0,
        "boundary_statement": "The full PubMed ESearch PMID inventory has not been compared with the frozen snapshot.",
    }
    if not inventory_path.exists():
        return empty
    try:
        rows = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {**empty, "label": "WARN: search coverage inventory is unreadable"}
    summary = rows[0] if isinstance(rows, list) and rows else rows if isinstance(rows, dict) else {}
    if not isinstance(summary, dict):
        return empty
    return {
        **empty,
        "status": summary.get("coverage_status") or "warn",
        "label": summary.get("label") or empty["label"],
        "unique_esearch_pmid_count": _int_or_none(summary.get("unique_esearch_pmid_count")) or 0,
        "frozen_snapshot_count": _int_or_none(summary.get("frozen_snapshot_count")) or 0,
        "missing_from_frozen_count": _int_or_none(summary.get("missing_from_frozen_count")) or 0,
        "frozen_not_in_current_query_count": _int_or_none(summary.get("frozen_not_in_current_query_count")) or 0,
        "boundary_statement": summary.get("boundary_statement") or empty["boundary_statement"],
    }


def _paper_block(index: int, paper: dict[str, Any]) -> list[str]:
    pmid = paper.get("pmid", "")
    reasons = paper.get("score_reasons") or []
    accessions = paper.get("accessions") or []
    abstract = " ".join((paper.get("abstract") or "").split())
    if len(abstract) > 500:
        abstract = f"{abstract[:497]}..."
    return [
        f"### {index}. {paper.get('title', '').strip() or 'Untitled'}",
        "",
        f"- PMID: {pmid}",
        f"- PubMed link: https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        f"- Journal: {paper.get('journal', '')}",
        f"- Publication date: {paper.get('pub_date', '')}",
        f"- Score: {paper.get('score', 0)}",
        f"- Score reasons: {', '.join(reasons) if reasons else 'None'}",
        f"- Accessions: {_format_accessions(paper) if accessions else 'None'}",
        f"- Abstract preview: {abstract if abstract else 'No abstract available.'}",
        "",
    ]


def _paper_summary_lines(papers: list[dict[str, Any]]) -> list[str]:
    if not papers:
        return ["No papers found."]
    return [
        f"{index}. [{paper.get('pmid', '')}] {paper.get('title', '').strip()} - {_format_accessions(paper) or 'None'}"
        for index, paper in enumerate(papers, 1)
    ]


def _top_table_lines(papers: list[dict[str, Any]]) -> list[str]:
    if not papers:
        return ["| - | - | No papers found. | - | - | - | - |"]
    return [
        (
            f"| {index} | {paper.get('pmid', '')} | {_table_cell(paper.get('title', ''))} | "
            f"{_table_cell(paper.get('journal', ''))} | {_table_cell(paper.get('pub_date', ''))} | "
            f"{paper.get('score', 0)} | {_table_cell(', '.join(paper.get('accessions') or []) or 'None')} |"
        )
        for index, paper in enumerate(papers, 1)
    ]


def _accession_table_lines(papers: list[dict[str, Any]]) -> list[str]:
    if not papers:
        return ["| - | No accession candidates found. | - |"]
    return [
        (
            f"| {paper.get('pmid', '')} | {_table_cell(paper.get('title', ''))} | "
            f"{_table_cell(_format_accessions(paper) or ', '.join(paper.get('accessions') or []))} |"
        )
        for paper in papers
    ]


def _validation_metric_labels(metrics: dict[str, Any]) -> tuple[str, str, str, str]:
    if metrics.get("pending_records", 0):
        return (
            "Pilot top-10 judged precision, provisional",
            "Annotated subset relevance precision, provisional",
            "Pilot record-level accession candidate precision, metadata-visible, provisional",
            "Pilot record-level accession recall, metadata-visible, provisional",
        )
    return (
        "Precision@10, judged rows only",
        "Overall relevance precision, judged rows only",
        "Record-level accession candidate precision, metadata-visible",
        "Record-level accession recall, metadata-visible",
    )


def _validation_section_lines(
    metrics: dict[str, Any] | None,
    spotcheck: dict[str, Any] | None = None,
    ai_spotcheck: dict[str, Any] | None = None,
) -> list[str]:
    if not metrics:
        return [
            "### Validation labels",
            "",
            "Validation label metrics have not been generated yet.",
        ]
    precision_label, relevance_label, accession_precision_label, accession_recall_label = _validation_metric_labels(metrics)
    review_scope = (
        "single-reviewer, AI-assisted, metadata-level pilot validation-label pass"
        if metrics["pending_records"]
        else "single-reviewer, AI-assisted, metadata-level validation-label pass"
    )
    return [
        "### Validation labels",
        "",
        f"Validation label status: {metrics['status']}",
        f"Validation label design: {review_scope} across {metrics['fully_annotated_records']}/{metrics['total_records']} records.",
        *_ai_spotcheck_design_lines(ai_spotcheck),
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Fully annotated records | {metrics['fully_annotated_records']}/{metrics['total_records']} |",
        f"| Judged top-10 records | {metrics['top10_coverage']['judged']}/10 |",
        f"| Blank top-10 records | {metrics['top10_coverage']['blank']} |",
        f"| {precision_label} | {_format_ratio(metrics['precision_at_10'])} |",
        f"| {relevance_label} | {_format_ratio(metrics['overall_relevance_precision'])} |",
        f"| {accession_precision_label} | {_format_ratio(metrics['accession_candidate_precision'])} |",
        f"| {accession_recall_label} | {_format_ratio(metrics['accession_recall'])} |",
        *_ai_spotcheck_metric_rows(ai_spotcheck),
        *_spotcheck_metric_rows(spotcheck),
        "",
        "Blank labels and `unclear` rows are excluded from metric denominators.",
        "Accession-negative labels mean no accession was visible in cached PubMed evidence; they do not rule out accessions in full text or supplements.",
        *_ai_spotcheck_disagreement_lines(ai_spotcheck),
    ]


def _ai_spotcheck_design_lines(spotcheck: dict[str, Any] | None) -> list[str]:
    if not spotcheck:
        return []
    return [
        "AI-assisted consensus was used as a metadata-level sensitivity and consistency check, not as independent human review."
    ]


def _ai_spotcheck_metric_rows(spotcheck: dict[str, Any] | None) -> list[str]:
    if not spotcheck:
        return ["| AI-assisted consensus spot-check summary | not generated |"]
    return [
        f"| AI-assisted consensus spot-check completed | {spotcheck['completed_records']}/{spotcheck['total_records']} |",
        f"| AI-assisted consensus row disagreements | {spotcheck['disagreed_records']} |",
        f"| AI-assisted consensus field disagreements | {spotcheck['field_disagreements']} |",
    ]


def _ai_spotcheck_disagreement_lines(spotcheck: dict[str, Any] | None) -> list[str]:
    if not spotcheck or not spotcheck.get("disagreements"):
        return []
    return [
        "",
        "AI-assisted consensus residual disagreement(s):",
        "",
        "| PMID | Field | Validation label | AI consensus label |",
        "| --- | --- | --- | --- |",
        *[
            (
                f"| {item['pmid']} | {item['field']} | "
                f"{_table_cell(item['validation']) or 'blank'} | {_table_cell(item['reviewer']) or 'blank'} |"
            )
            for item in spotcheck["disagreements"]
        ],
    ]


def _spotcheck_metric_rows(spotcheck: dict[str, Any] | None) -> list[str]:
    if not spotcheck:
        return ["| Human spot-check summary | not generated |"]
    if spotcheck["completed_records"] == 0:
        return [
            f"| Human spot-check completed | 0/{spotcheck['total_records']} |",
            "| Human spot-check disagreement status | not available until reviewer rows are completed |",
        ]
    return [
        f"| Human spot-check completed | {spotcheck['completed_records']}/{spotcheck['total_records']} |",
        f"| Human spot-check row disagreements | {spotcheck['disagreed_records']} |",
        f"| Human spot-check field disagreements | {spotcheck['field_disagreements']} |",
    ]


def _top10_coverage(rows: list[dict[str, str]]) -> dict[str, int]:
    top10 = [
        row
        for row in rows
        if _int_or_none(row.get("rank_position")) is not None and int(row["rank_position"]) <= 10
    ]
    return {
        "total": len(top10),
        "judged": sum(1 for row in top10 if _clean(row.get("manual_relevant")) in {"yes", "no"}),
        "blank": sum(1 for row in top10 if not _clean(row.get("manual_relevant"))),
        "unclear": sum(1 for row in top10 if _clean(row.get("manual_relevant")) == "unclear"),
    }


def _audit_issue_lines(issues: list[dict[str, str]]) -> list[str]:
    if not issues:
        return ["- No validation audit issues detected."]
    return [
        f"- PMID {issue.get('pmid', '')}: {issue.get('field', '')} - {issue.get('message', '')}"
        for issue in issues[:20]
    ]


def _table_cell(value: str) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _publication_year(pub_date: str) -> str:
    text = str(pub_date)
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ""


def _has_relevance_label(row: dict[str, str]) -> bool:
    return _clean(row.get("manual_relevant")) in {"yes", "no", "unclear"}


def _has_accession_label(row: dict[str, str]) -> bool:
    return _clean(row.get("accession_eval_label")).upper() in {"TP", "FP", "TN", "FN", "UNCLEAR"}


def _yes_ratio(rows: list[dict[str, str]], column: str) -> dict[str, int | float | None]:
    return _ratio(sum(1 for row in rows if _clean(row.get(column)) == "yes"), len(rows))


def _ratio(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": (numerator / denominator) if denominator else None,
    }


def _format_ratio(ratio: dict[str, int | float | None]) -> str:
    if ratio["value"] is None:
        return f"not available ({ratio['numerator']}/{ratio['denominator']})"
    return f"{ratio['value']:.3f} ({ratio['numerator']}/{ratio['denominator']})"


def _clean(value: str | None) -> str:
    return (value or "").strip().lower()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha256(path: str | Path | None) -> str | None:
    if path is None:
        return None
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _pmid_sort_key(value: str) -> tuple[int, str]:
    text = str(value)
    return (0, text.zfill(12)) if text.isdigit() else (1, text)


def _run_lines(runs: list[dict[str, Any]]) -> list[str]:
    if not runs:
        return ["No queued runs recorded."]
    return [
        (
            f"- Run {run['id']}: {run['status']} start={run.get('start_date') or '-'} "
            f"end={run.get('end_date') or '-'} fetched={run.get('fetched_count', 0)} "
            f"new={run.get('new_count', 0)} total={run.get('total_count', 0)}"
        )
        for run in runs
    ]


def _accession_row_lines(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No accession candidates found."]
    return [
        f"- {row['accession']} ({row['source']}): {row.get('paper_count', 0)} paper(s)"
        for row in rows
    ]


def _format_accessions(paper: dict[str, Any]) -> str:
    accessions = paper.get("accessions") or []
    metadata = paper.get("accession_metadata") or {}
    return ", ".join(_format_accession(accession, metadata.get(accession) or {}) for accession in accessions)


def _format_accession(accession: str, metadata: dict[str, Any]) -> str:
    source = metadata.get("source", "")
    url = metadata.get("url", "")
    label = f"{accession} ({source})" if source else accession
    return f"[{label}]({url})" if url else label


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_text(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
