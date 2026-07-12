from pathlib import Path


def test_daily_workflow_refreshes_citation_verification_before_final_review():
    text = Path(".github/workflows/daily.yml").read_text(encoding="utf-8")

    collector = text.index("name: Run bounded collector")
    coverage = text.index("name: Refresh search coverage inventory")
    first_review = text.index("name: Refresh review package")
    citation_verify = text.index("name: Refresh citation verification")
    update_diff = text.index("name: Write review update diff")
    final_review = text.index("name: Refresh review package gates")

    assert collector < coverage < first_review < citation_verify < update_diff < final_review
    assert "review-search-coverage" in text
    assert "review-citation-verify" in text
    assert "--input reports/review_citation_audit.csv" in text
    assert "--output reports/review_citation_verification.md" in text
