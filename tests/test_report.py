import csv
import json

from autobiosci_sentinel.report import (
    VALIDATION_COLUMNS,
    write_report,
    write_review_citation_verification,
    write_review_update_diff,
    write_review_package,
    write_review_search_coverage_inventory,
    write_spotcheck_summary,
    write_submission_draft,
    write_validation_metrics,
    write_validation_template,
)

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
    "reviewer_notes",
    "reviewer_id",
    "review_date",
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


def test_report_links_accession_metadata(tmp_path):
    report = tmp_path / "daily_report.md"
    paper = {
        "pmid": "1",
        "title": "Paper",
        "accessions": ["GSE123"],
        "accession_metadata": {
            "GSE123": {
                "source": "GEO",
                "url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123",
            }
        },
    }

    write_report(
        report,
        topics_count=1,
        fetched_count=1,
        new_count=1,
        total_count=1,
        top_papers=[paper],
        accession_papers=[paper],
        generated_at="2026-07-04T00:00:00Z",
    )

    assert "[GSE123 (GEO)](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123)" in report.read_text(
        encoding="utf-8"
    )


def test_report_writes_json_sidecars(tmp_path):
    report = tmp_path / "daily_report.md"
    paper = {
        "pmid": "1",
        "title": "Paper",
        "score_reasons": ["reason"],
        "accessions": ["GSE123"],
        "accession_metadata": {"GSE123": {"source": "GEO", "url": "https://example.test/GSE123"}},
    }

    write_report(
        report,
        topics_count=1,
        fetched_count=1,
        new_count=1,
        total_count=1,
        top_papers=[paper],
        accession_papers=[paper],
        generated_at="2026-07-04T00:00:00Z",
    )

    assert json.loads((tmp_path / "daily_report.top_papers.json").read_text(encoding="utf-8")) == [paper]
    assert json.loads((tmp_path / "daily_report.accession_candidates.json").read_text(encoding="utf-8")) == [paper]


def test_submission_draft_is_legacy_redirect(tmp_path):
    draft = tmp_path / "manuscript_draft.md"

    write_submission_draft(
        draft,
        topics_count=1,
        total_count=3,
        top_papers=[{"pmid": "1", "title": "Paper", "accessions": ["GSE123"]}],
        accession_papers=[{"pmid": "1", "title": "Paper", "accessions": ["GSE123"]}],
        generated_at="2026-07-05T00:00:00Z",
    )

    text = draft.read_text(encoding="utf-8")
    assert "# Legacy Manuscript Draft Redirect" in text
    assert "legacy compatibility output only" in text
    assert "python -m autobiosci_sentinel.cli review" in text
    assert "reports/review_draft.md" in text
    assert "reports/submission_manifest.md" in text
    assert "completed full-text eligibility screening" in text
    assert "## Abstract" not in text
    assert "PRISMA-like" not in text
    assert "manual eligibility screening has been completed" not in text


def test_submission_draft_does_not_embed_legacy_validation_claims(tmp_path):
    draft = tmp_path / "manuscript_draft.md"
    metrics = {
        "status": "AI-assisted validation-label coverage is complete; interpret metrics using judged-row denominators. Independent human review is tracked separately.",
        "fully_annotated_records": 2,
        "pending_records": 0,
        "total_records": 2,
        "top10_coverage": {"total": 10, "judged": 2, "blank": 8, "unclear": 0},
        "precision_at_10": {"numerator": 1, "denominator": 2, "value": 0.5},
        "overall_relevance_precision": {"numerator": 1, "denominator": 2, "value": 0.5},
        "accession_candidate_precision": {"numerator": 1, "denominator": 1, "value": 1.0},
        "accession_recall": {"numerator": 1, "denominator": 2, "value": 0.5},
    }

    write_submission_draft(
        draft,
        topics_count=1,
        total_count=2,
        top_papers=[],
        accession_papers=[],
        validation=metrics,
        ai_spotcheck={
            "completed_records": 14,
            "total_records": 14,
            "disagreed_records": 1,
            "field_disagreements": 1,
            "disagreements": [
                {
                    "pmid": "123",
                    "field": "manual_topic_match",
                    "validation": "no",
                    "reviewer": "unclear",
                }
            ],
        },
        spotcheck={
            "completed_records": 1,
            "total_records": 2,
            "disagreed_records": 1,
            "field_disagreements": 3,
        },
        generated_at="2026-07-05T00:00:00Z",
    )

    text = draft.read_text(encoding="utf-8")
    assert "reports/review_submission_checklist.md" in text
    assert "study-quality or risk-of-bias assessment" in text
    assert "Precision@10" not in text
    assert "AI-assisted consensus spot-check completed" not in text
    assert "Human spot-check field disagreements" not in text
    assert "manual eligibility screening has been completed" not in text


def test_submission_draft_does_not_report_zero_disagreements_before_spotcheck(tmp_path):
    draft = tmp_path / "manuscript_draft.md"
    metrics = {
        "status": "AI-assisted validation-label coverage is complete; interpret metrics using judged-row denominators. Independent human review is tracked separately.",
        "fully_annotated_records": 2,
        "pending_records": 0,
        "total_records": 2,
        "top10_coverage": {"total": 10, "judged": 2, "blank": 8, "unclear": 0},
        "precision_at_10": {"numerator": 1, "denominator": 2, "value": 0.5},
        "overall_relevance_precision": {"numerator": 1, "denominator": 2, "value": 0.5},
        "accession_candidate_precision": {"numerator": 1, "denominator": 1, "value": 1.0},
        "accession_recall": {"numerator": 1, "denominator": 2, "value": 0.5},
    }

    write_submission_draft(
        draft,
        topics_count=1,
        total_count=2,
        top_papers=[],
        accession_papers=[],
        validation=metrics,
        spotcheck={
            "completed_records": 0,
            "total_records": 2,
            "disagreed_records": 0,
            "field_disagreements": 0,
        },
        generated_at="2026-07-05T00:00:00Z",
    )

    text = draft.read_text(encoding="utf-8")
    assert "Legacy Manuscript Draft Redirect" in text
    assert "reports/review_fulltext_queue.csv" in text
    assert "Human spot-check row disagreements" not in text
    assert "not available until reviewer rows are completed" not in text


def test_write_review_search_coverage_inventory(tmp_path):
    summary = write_review_search_coverage_inventory(
        tmp_path / "reports" / "review_search_coverage.md",
        tmp_path / "reports" / "review_search_coverage.json",
        tmp_path / "reports" / "review_search_coverage.csv",
        [
            {
                "topic_id": "topic",
                "query": '"cancer"',
                "retmax": 2,
                "days_back": 30,
                "raw_pubmed_hit_count": 3,
                "pmids": ["1", "2", "3"],
            }
        ],
        {"1", "4"},
        generated_at="2026-07-06T00:00:00Z",
    )

    assert summary["unique_esearch_pmid_count"] == 3
    assert summary["overlap_count"] == 1
    assert summary["missing_from_frozen_pmids"] == ["2", "3"]
    assert summary["frozen_not_in_current_query_pmids"] == ["4"]
    assert "Review Search Coverage Inventory" in (tmp_path / "reports" / "review_search_coverage.md").read_text(
        encoding="utf-8"
    )
    assert "topic,1,1,yes" in (tmp_path / "reports" / "review_search_coverage.csv").read_text(encoding="utf-8")


def test_review_package_writes_protocol_evidence_references_and_draft(tmp_path):
    validation_csv = tmp_path / "validation.csv"
    _write_validation_csv(
        validation_csv,
        [
            {
                "pmid": "1",
                "rank_position": "1",
                "manual_relevant": "yes",
                "manual_topic_match": "yes",
                "manual_transcriptomics": "yes",
                "manual_accession_present": "yes",
                "manual_accessions": "GSE123",
                "accession_eval_label": "TP",
            }
        ],
    )
    topic = type(
        "Topic",
        (),
        {
            "name": "topic",
            "query": '"cancer" AND "RNA-seq"',
            "core_keywords": ["cancer", "RNA-seq"],
        },
    )()
    paper = {
        "pmid": "1",
        "doi": "10.1/example",
        "title": "Paper",
        "journal": "Journal",
        "pub_date": "2026-07-04",
        "authors": "A. Author",
        "score": 5,
        "accessions": ["GSE123"],
    }

    outputs = write_review_package(
        tmp_path / "reports",
        topics=[topic],
        total_count=1,
        papers=[paper],
        validation_path=validation_csv,
        validation={
            "fully_annotated_records": 1,
            "total_records": 1,
            "precision_at_10": {"numerator": 1, "denominator": 1, "value": 1.0},
            "overall_relevance_precision": {"numerator": 1, "denominator": 1, "value": 1.0},
            "accession_candidate_precision": {"numerator": 1, "denominator": 1, "value": 1.0},
            "accession_recall": {"numerator": 1, "denominator": 1, "value": 1.0},
            "audit": {"issue_count": 0},
        },
        ai_spotcheck={"completed_records": 1, "total_records": 1, "field_disagreements": 0},
        generated_at="2026-07-06T00:00:00Z",
    )

    assert set(outputs) == {
        "protocol",
        "records",
        "evidence",
        "references",
        "search_strategy",
        "search_strategy_json",
        "citation_audit",
        "fulltext_queue",
        "fulltext_instructions",
        "quality_guidance",
        "human_checkpoints",
        "submission_audit",
        "forbidden_terms",
        "claim_audit",
        "claim_audit_json",
        "prisma_flow",
        "prisma_flow_json",
        "display_items",
        "display_items_json",
        "figure1_flow_source",
        "figure2_theme_distribution_csv",
        "figure2_theme_distribution_md",
        "draft",
        "manifest",
        "manifest_json",
        "submission_manifest",
        "submission_declarations",
        "submission_templates",
        "submission_checklist",
        "prisma_checklist",
    }
    assert "Minimum Inclusion Criteria" in (tmp_path / "reports" / "review_protocol.md").read_text(encoding="utf-8")
    assert "pmid1_2026_paper" in (tmp_path / "reports" / "review_evidence_table.csv").read_text(encoding="utf-8")
    assert "@article{pmid1_2026_paper" in (tmp_path / "reports" / "review_references.bib").read_text(encoding="utf-8")
    search_strategy = (tmp_path / "reports" / "review_search_strategy.md").read_text(encoding="utf-8")
    assert "Review Search Strategy" in search_strategy
    assert "PubMed-only" in search_strategy
    assert "not a multi-database systematic-review strategy" in search_strategy
    search_strategy_json = json.loads((tmp_path / "reports" / "review_search_strategy.json").read_text(encoding="utf-8"))[0]
    assert search_strategy_json["database"] == "PubMed"
    assert search_strategy_json["exact_pubmed_query"] == '"cancer" AND "RNA-seq"'
    assert search_strategy_json["records_in_frozen_snapshot"] == 1
    assert search_strategy_json["raw_count_available"] is False
    assert "needs_metadata_verification" in (tmp_path / "reports" / "review_citation_audit.csv").read_text(encoding="utf-8")
    fulltext_csv = (tmp_path / "reports" / "review_fulltext_queue.csv").read_text(encoding="utf-8")
    assert "snapshot_id,rank,rank_position" in fulltext_csv
    assert "full_text_status" in fulltext_csv
    assert "assay_type_verified" in fulltext_csv
    assert "accession_fulltext_verified" in fulltext_csv
    fulltext_instructions = (tmp_path / "reports" / "review_fulltext_instructions.md").read_text(encoding="utf-8")
    assert "Full-text Review Instructions" in fulltext_instructions
    assert "final_include" in fulltext_instructions
    assert "venue_dependent" in fulltext_instructions
    quality_guidance = (tmp_path / "reports" / "review_quality_assessment_guidance.md").read_text(
        encoding="utf-8"
    )
    assert "Quality and Risk-of-bias Assessment Guidance" in quality_guidance
    assert "No risk-of-bias or study-quality assessment has been completed by the software" in quality_guidance
    assert "does not score any study automatically" in quality_guidance
    human_checkpoints = (tmp_path / "reports" / "review_human_checkpoints.md").read_text(encoding="utf-8")
    assert "Human Review Checkpoints" in human_checkpoints
    assert "final_include" in human_checkpoints
    assert "manual_include" not in human_checkpoints
    assert "Review Submission Audit" in (tmp_path / "reports" / "review_submission_audit.md").read_text(encoding="utf-8")
    assert "Search strategy documentation" in (tmp_path / "reports" / "review_submission_audit.md").read_text(encoding="utf-8")
    assert "Review Claim Audit" in (tmp_path / "reports" / "review_claim_audit.md").read_text(encoding="utf-8")
    prisma_flow = (tmp_path / "reports" / "review_prisma_flow.md").read_text(encoding="utf-8")
    assert "PRISMA-oriented Metadata Flow" in prisma_flow
    assert "not a claim of PRISMA compliance" in prisma_flow
    prisma_flow_json = json.loads((tmp_path / "reports" / "review_prisma_flow.json").read_text(encoding="utf-8"))[0]
    assert prisma_flow_json["deduplicated_records"] == 1
    assert prisma_flow_json["metadata_relevant_records"] == 1
    assert prisma_flow_json["fulltext_queue_records"] == 1
    assert prisma_flow_json["final_include_pending"] == 1
    assert prisma_flow_json["claim_boundary"] == "formal PubMed-only metadata-level PRISMA-oriented flow with human full-text counts pending"
    display_items = (tmp_path / "reports" / "review_display_items.md").read_text(encoding="utf-8")
    assert "Review Display Items Plan" in display_items
    assert "proposed, venue-neutral display items" in display_items
    assert "not final journal artwork" in display_items
    assert "not PRISMA-compliant" in display_items
    display_items_json = json.loads((tmp_path / "reports" / "review_display_items.json").read_text(encoding="utf-8"))
    assert [item["item_id"] for item in display_items_json] == [
        "Figure 1",
        "Figure 2",
        "Table 1",
        "Table 2",
        "Supplementary Table 1",
    ]
    assert display_items_json[0]["source_counts"]["metadata_relevant_records"] == 1
    assert display_items_json[1]["source_counts"]["theme_counts"] == {"Other transcriptomics surveillance records": 1}
    figure1 = (tmp_path / "reports" / "review_figure1_flow.mmd").read_text(encoding="utf-8")
    assert "accTitle: Metadata Selection Flow" in figure1
    assert "Full-text queue: 1" in figure1
    figure2_csv = (tmp_path / "reports" / "review_figure2_theme_distribution.csv").read_text(encoding="utf-8")
    assert "Other transcriptomics surveillance records,1,1.000" in figure2_csv
    figure2_md = (tmp_path / "reports" / "review_figure2_theme_distribution.md").read_text(encoding="utf-8")
    assert "Figure 2 Source: Metadata-level Thematic Distribution" in figure2_md
    assert "not final journal artwork" in figure2_md
    assert "pie showData" in figure2_md
    assert "Submission Packet Manifest" in (tmp_path / "reports" / "submission_manifest.md").read_text(encoding="utf-8")
    assert "AI Assistance Disclosure" in (tmp_path / "reports" / "review_submission_declarations.md").read_text(encoding="utf-8")
    templates = (tmp_path / "reports" / "review_submission_templates.md").read_text(encoding="utf-8")
    assert "Submission Administrative Templates" in templates
    assert "Draft template only" in templates
    assert "[TO BE COMPLETED BY AUTHORS]" in templates
    checklist = (tmp_path / "reports" / "review_submission_checklist.md").read_text(encoding="utf-8")
    assert "Review Submission Checklist" in checklist
    assert "Full-text eligibility and final inclusion" in checklist
    assert "Search strategy documentation" in checklist
    assert "guidance available; human completion pending" in checklist
    assert "template generated; human completion required" in checklist
    assert "| Cover letter and title page | not generated |" not in checklist
    assert "Venue-neutral display-item sources" in checklist
    assert "review_figure1_flow.mmd" in checklist
    assert "AI consensus may support mechanical metadata checks" in checklist
    prisma = (tmp_path / "reports" / "review_prisma_checklist.md").read_text(encoding="utf-8")
    assert "PRISMA-Oriented Reporting Checklist" in prisma
    assert "not a claim of PRISMA compliance" in prisma
    assert "review_search_strategy.md" in prisma
    assert "Risk of bias or study quality" in prisma
    assert "Guidance and queue fields exist" in prisma
    assert "review_display_items.md" in prisma
    assert "Formal PubMed-only metadata-level flow is generated" in prisma
    assert "systematic review" in (tmp_path / "reports" / "review_forbidden_terms.yaml").read_text(encoding="utf-8")
    assert "pmid1_2026_paper" in (tmp_path / "reports" / "review_records_frozen.jsonl").read_text(encoding="utf-8")
    draft = (tmp_path / "reports" / "review_draft.md").read_text(encoding="utf-8")
    assert "# Metadata-level scoping review draft for topic surveillance" in draft
    assert "Background:" not in draft
    assert "- Metadata validation coverage:" not in draft
    assert "review_search_strategy.md" in draft
    assert "## PRISMA-like Flow" not in draft
    assert "## Metadata-Level Selection Flow" in draft
    assert "review_prisma_flow.json" in draft
    assert "not a claim of PRISMA compliance" in draft
    assert "| Metadata-validated records | 1 |" in draft
    assert "| Records routed to full-text queue | 1 |" in draft
    assert "| Final include decisions | 0 yes; 0 no; 0 unclear; 1 pending |" in draft
    assert "Recurring update status:" in draft
    assert "### Thematic Metadata Map" in draft
    assert "## Metadata-Level Thematic Synthesis" in draft
    assert "The denominator is 1 metadata-relevant record(s) routed to the full-text queue" in draft
    assert "Current human gate status is 0/1 full-text checked; 0/1 human-verified; 1 final-include pending" in draft
    assert "Other transcriptomics surveillance records accounted for 1/1 metadata-relevant record(s)" in draft
    assert "pmid1_2026_paper (PMID 1)" in draft
    assert "Metadata-visible accession candidates were recorded for 1 record(s)" in draft
    assert "not final biological conclusions" in draft
    assert "review_display_items.md" in draft
    assert "review_display_items.json" in draft
    assert "review_figure1_flow.mmd" in draft
    assert "## Reference Metadata: PubMed-derived records included at metadata level" in draft
    assert "| pmid1_2026_paper | 1 | 10.1/example | Journal | 2026 | not_run | Paper |" in draft
    assert "Target-journal reference styling and final citation selection require human or venue review" in draft
    assert "Precision@10: 1.000 (1/1)" in draft
    assert "Full-text/quality queue status" in draft


def test_review_package_uses_search_run_metadata_when_present(tmp_path):
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    (output_dir / "search_run_metadata.json").write_text(
        json.dumps(
            {
                "schema_version": "search_run_metadata.v1",
                "generated_at_utc": "2026-07-06T00:00:00Z",
                "source": "PubMed ESearch",
                "topics_count": 1,
                "total_retrieved_pmids": 1,
                "total_parsed_records": 1,
                "topics": [
                    {
                        "topic_id": "topic",
                        "query": '"cancer" AND "RNA-seq"',
                        "retmax": 10,
                        "days_back": 30,
                        "source": "PubMed ESearch",
                        "searched_at_utc": "2026-07-06T00:00:00Z",
                        "raw_pubmed_hit_count": 123,
                        "retrieved_pmids_count": 1,
                        "parsed_records_count": 1,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "review_ai_consensus_update.md").write_text("# AI-assisted Consensus Validation Update\n", encoding="utf-8")
    (output_dir / "review_ai_consensus_update.json").write_text("[]\n", encoding="utf-8")
    write_review_search_coverage_inventory(
        output_dir / "review_search_coverage.md",
        output_dir / "review_search_coverage.json",
        output_dir / "review_search_coverage.csv",
        [
            {
                "topic_id": "topic",
                "query": '"cancer" AND "RNA-seq"',
                "retmax": 10,
                "days_back": 30,
                "raw_pubmed_hit_count": 123,
                "pmids": ["1", "2", "3"],
            }
        ],
        {"1"},
        generated_at="2026-07-06T00:00:00Z",
    )
    topic = type(
        "Topic",
        (),
        {
            "name": "topic",
            "query": '"cancer" AND "RNA-seq"',
            "core_keywords": ["cancer", "RNA-seq"],
            "retmax": 10,
            "days_back": 30,
        },
    )()
    paper = {
        "pmid": "1",
        "doi": "10.1/example",
        "title": "Paper",
        "journal": "Journal",
        "pub_date": "2026-07-04",
        "authors": "A. Author",
        "score": 5,
        "accessions": [],
    }

    outputs = write_review_package(output_dir, topics=[topic], total_count=1, papers=[paper])

    assert "search_run_metadata" in outputs
    assert "search_coverage_inventory" in outputs
    assert "search_coverage_inventory_json" in outputs
    assert "search_coverage_inventory_csv" in outputs
    assert "ai_consensus_update" in outputs
    assert "ai_consensus_update_json" in outputs
    search_strategy_json = json.loads((output_dir / "review_search_strategy.json").read_text(encoding="utf-8"))[0]
    assert search_strategy_json["raw_count_available"] is True
    assert search_strategy_json["raw_pubmed_hit_count"] == 123
    assert search_strategy_json["records_retrieved_raw"] == 1
    assert search_strategy_json["search_coverage_gate"]["retrieval_truncated_or_partial"] is True
    assert search_strategy_json["search_coverage_gate"]["latest_retrieved_pmids"] == 1
    assert search_strategy_json["search_coverage_gate"]["raw_pubmed_hit_count"] == 123
    assert search_strategy_json["topic_queries"][0]["raw_pubmed_hit_count"] == 123
    search_strategy_md = (output_dir / "review_search_strategy.md").read_text(encoding="utf-8")
    assert "| Raw PubMed hit count | 123 |" in search_strategy_md
    assert "| Retrieval truncated or partial | true |" in search_strategy_md
    assert "retained surveillance corpus under the configured retrieval limit" in search_strategy_md
    assert "Raw ESearch hit count is not stored" not in search_strategy_md
    prisma_flow_json = json.loads((output_dir / "review_prisma_flow.json").read_text(encoding="utf-8"))[0]
    assert prisma_flow_json["raw_pubmed_hit_count"] == 123
    assert prisma_flow_json["raw_records_retrieved"] == 1
    prisma_flow_md = (output_dir / "review_prisma_flow.md").read_text(encoding="utf-8")
    assert "Raw PubMed hit count: 123 PubMed ESearch hit(s); 1 PMID(s) retrieved under retmax" in prisma_flow_md
    assert "Raw PubMed hit count and duplicate-removal count are not stored" not in prisma_flow_md
    assert "search_run_metadata.json" in (output_dir / "review_manifest.md").read_text(encoding="utf-8")
    assert "review_search_coverage.md" in (output_dir / "review_manifest.md").read_text(encoding="utf-8")
    assert "review_ai_consensus_update.md" in (output_dir / "review_manifest.md").read_text(encoding="utf-8")
    assert "Search coverage gate: WARN:" in (output_dir / "review_manifest.md").read_text(encoding="utf-8")
    assert "Search coverage inventory: WARN: inventoried 3 unique ESearch PMID(s)" in (
        output_dir / "review_manifest.md"
    ).read_text(encoding="utf-8")
    assert "Search coverage inventory: WARN: inventoried 3 unique ESearch PMID(s)" in (
        output_dir / "submission_manifest.md"
    ).read_text(encoding="utf-8")
    assert "Search coverage gate | WARN:" in (output_dir / "review_submission_checklist.md").read_text(encoding="utf-8")
    assert "review_search_coverage.csv" in (output_dir / "review_submission_checklist.md").read_text(encoding="utf-8")
    assert "Search coverage inventory: WARN: inventoried 3 unique ESearch PMID(s)" in (
        output_dir / "review_draft.md"
    ).read_text(encoding="utf-8")


def test_review_package_reports_validation_gap_against_frozen_snapshot(tmp_path):
    validation_csv = tmp_path / "validation.csv"
    _write_validation_csv(
        validation_csv,
        [
            {
                "pmid": "1",
                "rank_position": "1",
                "manual_relevant": "yes",
                "manual_topic_match": "yes",
                "manual_transcriptomics": "yes",
                "manual_accession_present": "no",
                "accession_eval_label": "TN",
            }
        ],
    )
    topic = type("Topic", (), {"name": "topic", "query": "query", "core_keywords": []})()
    papers = [
        {"pmid": "1", "title": "Validated", "score": 2, "accessions": []},
        {"pmid": "2", "title": "New unvalidated", "score": 1, "accessions": []},
    ]
    validation = {
        "fully_annotated_records": 1,
        "total_records": 1,
        "precision_at_10": {"numerator": 1, "denominator": 1, "value": 1.0},
        "overall_relevance_precision": {"numerator": 1, "denominator": 1, "value": 1.0},
        "accession_candidate_precision": {"numerator": 0, "denominator": 0, "value": None},
        "accession_recall": {"numerator": 0, "denominator": 0, "value": None},
        "audit": {"issue_count": 0},
    }

    write_review_package(
        tmp_path / "reports",
        topics=[topic],
        total_count=2,
        papers=papers,
        validation_path=validation_csv,
        validation=validation,
        generated_at="2026-07-06T00:00:00Z",
    )

    expected = "1/1; audit issues 0; frozen snapshot records 2; validation rows missing for 1"
    for name in [
        "review_manifest.md",
        "submission_manifest.md",
        "review_submission_checklist.md",
        "review_submission_audit.md",
    ]:
        assert expected in (tmp_path / "reports" / name).read_text(encoding="utf-8")


def test_review_package_surfaces_update_diff_status(tmp_path):
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    (output_dir / "review_update_diff.md").write_text("# Review Update Diff\n", encoding="utf-8")
    (output_dir / "human_update_queue.csv").write_text("pmid,status\n2,added\n", encoding="utf-8")
    (output_dir / "review_update_diff.json").write_text(
        json.dumps(
            [
                {
                    "old_records": 1,
                    "new_records": 2,
                    "added_records": 1,
                    "removed_records": 0,
                    "unchanged_records": 1,
                    "metadata_changed_records": 0,
                    "labels_carried_forward_count": 1,
                    "needs_human_review_count": 1,
                    "changes": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    topic = type("Topic", (), {"name": "topic", "query": "query", "core_keywords": []})()
    paper = {"pmid": "1", "title": "Paper", "score": 1, "accessions": []}

    outputs = write_review_package(output_dir, topics=[topic], total_count=1, papers=[paper])

    assert "update_diff" in outputs
    assert "human_update_queue" in outputs
    manifest = (output_dir / "review_manifest.md").read_text(encoding="utf-8")
    audit = (output_dir / "review_submission_audit.md").read_text(encoding="utf-8")
    draft = (output_dir / "review_draft.md").read_text(encoding="utf-8")
    expected = "Periodic update readiness: WARN: 1 added; 0 metadata-changed; 0 removed; 1 need human update review; queue rows 1"
    assert expected in manifest
    assert expected in audit
    manifest_json = json.loads((output_dir / "review_manifest.json").read_text(encoding="utf-8"))[0]
    assert manifest_json["periodic_update"]["status"] == "warn"
    assert manifest_json["periodic_update"]["human_update_queue_count"] == 1
    assert "## Changes Since Previous Snapshot" in draft
    assert "reports/human_update_queue.csv" in draft


def test_review_package_marks_update_self_diff_as_self_check(tmp_path):
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    record = {
        "pmid": "1",
        "citation_key": "pmid1",
        "title": "Paper",
        "doi": "10.1/example",
        "journal": "Journal",
        "publication_year": "2026",
        "accessions": [],
        "validation": {"manual_relevant": "yes"},
    }
    (output_dir / "review_records_frozen.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")

    summary = write_review_update_diff(
        output_dir,
        output_dir,
        output_dir / "review_update_diff.md",
        output_dir / "review_update_diff.json",
        output_dir / "human_update_queue.csv",
    )

    assert summary["self_comparison"] is True
    assert "Self-comparison: yes" in (output_dir / "review_update_diff.md").read_text(encoding="utf-8")
    topic = type("Topic", (), {"name": "topic", "query": "query", "core_keywords": []})()
    paper = {"pmid": "1", "title": "Paper", "score": 1, "accessions": []}

    write_review_package(output_dir, topics=[topic], total_count=1, papers=[paper])

    manifest = (output_dir / "review_manifest.md").read_text(encoding="utf-8")
    draft = (output_dir / "review_draft.md").read_text(encoding="utf-8")
    manifest_json = json.loads((output_dir / "review_manifest.json").read_text(encoding="utf-8"))[0]
    assert "Periodic update readiness: SELF-CHECK:" in manifest
    assert "not evidence of a completed periodic update comparison" in draft
    assert manifest_json["periodic_update"]["status"] == "self_check"


def test_review_package_draft_uses_completed_citation_verification_status(tmp_path):
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    (output_dir / "review_citation_verification.json").write_text(
        json.dumps(
            [
                {
                    "total_records": 1,
                    "verified_records": 1,
                    "pubmed_verified_unresolved_records": 0,
                    "failed_records": 0,
                    "network_error_records": 0,
                }
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "review_citation_verification.csv").write_text("pmid,status\n1,verified\n", encoding="utf-8")
    topic = type("Topic", (), {"name": "topic", "query": "query", "core_keywords": []})()
    paper = {"pmid": "1", "doi": "10.1/example", "title": "Paper", "score": 1, "accessions": []}

    write_review_package(output_dir, topics=[topic], total_count=1, papers=[paper])

    draft = (output_dir / "review_draft.md").read_text(encoding="utf-8")
    assert "The citation audit status is 1/1 resolver-verified" in draft
    assert "records external DOI resolver and PubMed-confirmation status" in draft
    assert "any unresolved citation-verification cases are handled according to target venue rules" in draft
    assert "Citation verification has been run" in draft
    assert "citation metadata is externally verified" not in draft
    assert "does not verify all DOI metadata against CrossRef" not in draft


def test_review_citation_verification_uses_crossref_metadata(tmp_path):
    citations = tmp_path / "review_citation_audit.csv"
    citations.write_text(
        "pmid,citation_key,doi,title,journal,publication_year\n"
        "1,pmid1,10.1/example,Example Title,Example Journal,2026\n",
        encoding="utf-8",
    )

    def fake_fetcher(doi, timeout_seconds):
        assert doi == "10.1/example"
        assert timeout_seconds == 3
        return {
            "message": {
                "DOI": "10.1/example",
                "title": ["Example Title"],
                "container-title": ["Example Journal"],
                "issued": {"date-parts": [[2026]]},
            }
        }

    summary = write_review_citation_verification(
        citations,
        tmp_path / "verification.md",
        tmp_path / "verification.json",
        tmp_path / "verification.csv",
        timeout_seconds=3,
        fetcher=fake_fetcher,
    )

    assert summary["verified_records"] == 1
    assert summary["failed_records"] == 0
    assert "Verified records: 1" in (tmp_path / "verification.md").read_text(encoding="utf-8")
    assert "verified" in (tmp_path / "verification.csv").read_text(encoding="utf-8")


def test_review_citation_verification_can_mark_pubmed_confirmed_unresolved(tmp_path, monkeypatch):
    citations = tmp_path / "review_citation_audit.csv"
    citations.write_text(
        "pmid,citation_key,doi,title,journal,publication_year\n"
        "1,pmid1,10.1/example,Example Title,Example Journal,2026\n",
        encoding="utf-8",
    )

    def fake_fetcher(doi, timeout_seconds):
        raise __import__("urllib.error").error.HTTPError("", 404, "Not Found", {}, None)

    monkeypatch.setattr("autobiosci_sentinel.report._pubmed_confirms_doi", lambda pmid, doi, timeout: True)

    summary = write_review_citation_verification(
        citations,
        tmp_path / "verification.md",
        tmp_path / "verification.json",
        tmp_path / "verification.csv",
        fetcher=fake_fetcher,
    )

    assert summary["pubmed_verified_unresolved_records"] == 1
    assert summary["failed_records"] == 0
    assert "pubmed_verified_unresolved" in (tmp_path / "verification.csv").read_text(encoding="utf-8")


def test_review_update_diff_writes_human_queue(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    old_records = [
        {
            "pmid": "1",
            "citation_key": "pmid1",
            "title": "Same",
            "doi": "10.1/same",
            "journal": "Journal",
            "publication_year": "2026",
            "accessions": [],
            "validation": {"manual_relevant": "yes", "accession_eval_label": "TN"},
        },
        {
            "pmid": "2",
            "citation_key": "pmid2",
            "title": "Removed",
            "doi": "10.1/removed",
            "journal": "Journal",
            "publication_year": "2026",
            "accessions": [],
            "validation": {"manual_relevant": "yes"},
        },
        {
            "pmid": "3",
            "citation_key": "pmid3",
            "title": "Old Title",
            "doi": "10.1/changed",
            "journal": "Journal",
            "publication_year": "2026",
            "accessions": [],
            "validation": {"manual_relevant": "yes"},
        },
    ]
    new_records = [
        old_records[0],
        {
            "pmid": "3",
            "citation_key": "pmid3",
            "title": "New Title",
            "doi": "10.1/changed",
            "journal": "Journal",
            "publication_year": "2026",
            "accessions": [],
            "validation": {"manual_relevant": "yes"},
        },
        {
            "pmid": "4",
            "citation_key": "pmid4",
            "title": "Added",
            "doi": "10.1/added",
            "journal": "Journal",
            "publication_year": "2026",
            "accessions": [],
            "validation": {},
        },
    ]
    (old_dir / "review_records_frozen.jsonl").write_text(
        "\n".join(json.dumps(record) for record in old_records),
        encoding="utf-8",
    )
    (new_dir / "review_records_frozen.jsonl").write_text(
        "\n".join(json.dumps(record) for record in new_records),
        encoding="utf-8",
    )

    summary = write_review_update_diff(
        old_dir,
        new_dir,
        tmp_path / "update_diff.md",
        tmp_path / "update_diff.json",
        tmp_path / "human_update_queue.csv",
    )

    assert summary["added_records"] == 1
    assert summary["removed_records"] == 1
    assert summary["unchanged_records"] == 1
    assert summary["metadata_changed_records"] == 1
    assert summary["labels_carried_forward_count"] == 1
    assert summary["needs_human_review_count"] == 2
    queue_rows = list(csv.DictReader((tmp_path / "human_update_queue.csv").open(encoding="utf-8", newline="")))
    assert [row["pmid"] for row in queue_rows] == ["3", "4"]
    assert "metadata_changed" in (tmp_path / "update_diff.md").read_text(encoding="utf-8")


def test_validation_template_writes_manual_annotation_columns(tmp_path):
    output = tmp_path / "validation_template.csv"

    write_validation_template(
        output,
        [
            {
                "pmid": "1",
                "doi": "10.1/example",
                "title": "Paper",
                "journal": "Journal",
                "pub_date": "2026-07-04",
                "score": 5,
                "accessions": ["GSE123"],
            }
        ],
        "snapshot-1",
    )

    rows = list(csv.DictReader(output.open(encoding="utf-8", newline="")))
    assert rows[0]["snapshot_id"] == "snapshot-1"
    assert rows[0]["publication_year"] == "2026"
    assert rows[0]["rank_position"] == "1"
    assert rows[0]["tool_accession_candidate_present"] == "yes"
    assert rows[0]["tool_accession_candidates"] == "GSE123"
    assert "manual_relevant" in rows[0]
    assert "accession_eval_label" in rows[0]


def test_validation_metrics_reports_relevance_and_accession_counts(tmp_path):
    csv_path = tmp_path / "validation.csv"
    _write_validation_csv(
        csv_path,
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
                "tool_accession_candidate_present": "yes",
                "manual_accession_present": "no",
                "accession_eval_label": "FP",
            },
            {
                "pmid": "3",
                "rank_position": "11",
                "manual_relevant": "yes",
                "manual_accession_present": "yes",
                "accession_eval_label": "FN",
            },
            {"pmid": "4", "rank_position": "12"},
        ],
    )
    output = tmp_path / "validation_metrics.md"

    metrics = write_validation_metrics(csv_path, output)

    assert metrics["fully_annotated_records"] == 3
    assert metrics["pending_records"] == 1
    assert metrics["precision_at_10"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert metrics["overall_relevance_precision"] == {"numerator": 2, "denominator": 3, "value": 2 / 3}
    assert metrics["accession_counts"] == {"TP": 1, "FP": 1, "TN": 0, "FN": 1, "unclear": 0}
    assert metrics["audit"]["issue_count"] == 0
    text = output.read_text(encoding="utf-8")
    assert "Pilot top-10 judged precision, provisional: 0.500 (1/2)" in text
    assert "AI-assisted validation-label coverage is incomplete" in text
    assert json.loads((tmp_path / "validation_metrics.json").read_text(encoding="utf-8")) == [metrics]


def test_validation_metrics_audits_inconsistent_labels(tmp_path):
    csv_path = tmp_path / "validation.csv"
    _write_validation_csv(
        csv_path,
        [
            {
                "pmid": "1",
                "rank_position": "1",
                "manual_relevant": "maybe",
                "manual_rnaseq_or_scrnaseq": "microarray",
                "tool_accession_candidate_present": "no",
                "manual_accession_present": "yes",
                "accession_eval_label": "FP",
                "error_category": "bad_error",
            },
        ],
    )
    output = tmp_path / "validation_metrics.md"

    metrics = write_validation_metrics(csv_path, output)

    messages = [issue["message"] for issue in metrics["audit"]["issues"]]
    assert metrics["audit"]["issue_count"] == 5
    assert "unexpected value: maybe" in messages
    assert "unexpected value: microarray" in messages
    assert "unexpected value: bad_error" in messages
    assert "FP conflicts with tool_accession_candidate_present=no" in messages
    assert "FP conflicts with manual_accession_present=yes" in messages
    text = output.read_text(encoding="utf-8")
    assert "## Validation Audit" in text
    assert "PMID 1: manual_relevant - unexpected value: maybe" in text


def test_spotcheck_summary_reports_pending_and_disagreements(tmp_path):
    validation_csv = tmp_path / "validation.csv"
    _write_validation_csv(
        validation_csv,
        [
            {
                "pmid": "1",
                "manual_relevant": "yes",
                "manual_topic_match": "yes",
                "manual_transcriptomics": "yes",
                "manual_rnaseq_or_scrnaseq": "both",
                "manual_biomarker_focus": "yes",
                "tool_accession_candidate_present": "yes",
                "manual_accession_present": "yes",
                "manual_accessions": "GSE2;GSE1",
                "accession_match_status": "exact",
                "accession_eval_label": "TP",
            },
            {"pmid": "2"},
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
                "reviewer_rnaseq_or_scrnaseq": "both",
                "reviewer_biomarker_focus": "no",
                "reviewer_accession_present": "yes",
                "reviewer_accessions": "gse1;GSE2",
                "reviewer_accession_match_status": "exact",
                "reviewer_accession_eval_label": "TP",
            },
            {"pmid": "2"},
        ],
    )
    output = tmp_path / "spotcheck_summary.md"

    summary = write_spotcheck_summary(spotcheck_csv, validation_csv, output)

    assert summary["total_records"] == 2
    assert summary["completed_records"] == 1
    assert summary["pending_records"] == 1
    assert summary["agreed_records"] == 0
    assert summary["disagreed_records"] == 1
    assert summary["field_disagreements"] == 1
    assert summary["pending_pmids"] == ["2"]
    assert summary["disagreements"][0] == {
        "pmid": "1",
        "field": "manual_biomarker_focus",
        "validation": "yes",
        "reviewer": "no",
    }
    text = output.read_text(encoding="utf-8")
    assert "| 1 | manual_biomarker_focus | yes | no |" in text


def test_spotcheck_summary_does_not_report_no_disagreements_before_review(tmp_path):
    validation_csv = tmp_path / "validation.csv"
    _write_validation_csv(validation_csv, [{"pmid": "1"}])
    spotcheck_csv = tmp_path / "spotcheck.csv"
    _write_spotcheck_csv(spotcheck_csv, [{"pmid": "1"}])
    output = tmp_path / "spotcheck_summary.md"

    summary = write_spotcheck_summary(spotcheck_csv, validation_csv, output)

    assert summary["completed_records"] == 0
    text = output.read_text(encoding="utf-8")
    assert "Not available until reviewer rows are completed." in text
    assert "No reviewer disagreements recorded." not in text
