from datetime import date

from autobiosci_sentinel.scoring import score_paper


def test_score_paper_expected_reasons():
    score, reasons = score_paper(
        title="Checkpoint inhibitor response study",
        abstract="RNA-seq biomarker analysis with GSE123.",
        keywords=["checkpoint inhibitor"],
        accessions=["GSE123"],
        pub_date="2026-07-01",
        days_back=30,
        now=date(2026, 7, 4),
    )

    assert score == 9
    assert "title keyword: checkpoint inhibitor" in reasons
    assert "method keyword: RNA-seq/transcriptomics/single-cell" in reasons
    assert "biomarker keyword" in reasons
    assert "public dataset accession candidate" in reasons
    assert "publication date within 30 days" in reasons
