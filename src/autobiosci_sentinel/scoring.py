from __future__ import annotations

from datetime import date, datetime, timezone


METHOD_TERMS = ("rna-seq", "transcriptomics", "single-cell")


def score_paper(
    title: str,
    abstract: str,
    keywords: list[str],
    accessions: list[str] | None = None,
    pub_date: str | None = None,
    days_back: int | None = None,
    now: date | None = None,
) -> tuple[int, list[str]]:
    title_l = (title or "").lower()
    abstract_l = (abstract or "").lower()
    joined = f"{title_l} {abstract_l}"
    score = 0
    reasons: list[str] = []

    for keyword in keywords:
        needle = keyword.lower()
        if needle in title_l:
            score += 3
            reasons.append(f"title keyword: {keyword}")
        if needle in abstract_l:
            score += 1
            reasons.append(f"abstract keyword: {keyword}")

    if any(term in joined for term in METHOD_TERMS):
        score += 2
        reasons.append("method keyword: RNA-seq/transcriptomics/single-cell")

    if "biomarker" in joined:
        score += 1
        reasons.append("biomarker keyword")

    if accessions:
        score += 2
        reasons.append("public dataset accession candidate")

    if days_back and _is_recent(pub_date, days_back, now):
        score += 1
        reasons.append(f"publication date within {days_back} days")

    return score, reasons


def _is_recent(pub_date: str | None, days_back: int, now: date | None = None) -> bool:
    parsed = _parse_date(pub_date)
    if parsed is None:
        return False
    today = now or datetime.now(timezone.utc).date()
    delta = (today - parsed).days
    return 0 <= delta <= days_back


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for length, fmt in ((10, "%Y-%m-%d"), (7, "%Y-%m"), (4, "%Y")):
        try:
            dt = datetime.strptime(value[:length], fmt)
            return dt.date()
        except ValueError:
            continue
    return None
