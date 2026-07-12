from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape

import requests

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
LOGGER = logging.getLogger(__name__)


class PubMedSearchResult(list[str]):
    def __init__(self, pmids: list[str], raw_count: int | None = None) -> None:
        super().__init__(pmids)
        self.raw_count = raw_count


def search_pubmed(
    query: str,
    retmax: int,
    days_back: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    retstart: int = 0,
) -> list[str]:
    params: dict[str, str | int] = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "sort": "pub+date",
        "retmax": retmax,
    }
    if retstart:
        params["retstart"] = retstart
    if start_date or end_date:
        params["datetype"] = "pdat"
        if start_date:
            params["mindate"] = start_date
        if end_date:
            params["maxdate"] = end_date
    elif days_back:
        params["datetype"] = "pdat"
        params["reldate"] = days_back

    try:
        data = _get_json(ESEARCH_URL, params)
    except (requests.RequestException, ValueError) as exc:
        LOGGER.error("PubMed ESearch failed: %s", exc)
        return PubMedSearchResult([])

    result = data.get("esearchresult", {})
    raw_count = _int_or_none(result.get("count"))
    ids = result.get("idlist", [])
    return PubMedSearchResult([str(pmid) for pmid in ids], raw_count)


def search_pubmed_all_pmids(
    query: str,
    batch_size: int = 200,
    days_back: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    max_records: int | None = None,
) -> PubMedSearchResult:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    seen: set[str] = set()
    pmids: list[str] = []
    raw_count: int | None = None
    retstart = 0
    while True:
        remaining = None if max_records is None else max(max_records - len(pmids), 0)
        if remaining == 0:
            break
        retmax = min(batch_size, remaining) if remaining is not None else batch_size
        batch = search_pubmed(
            query,
            retmax,
            days_back=days_back,
            start_date=start_date,
            end_date=end_date,
            retstart=retstart,
        )
        if raw_count is None:
            raw_count = batch.raw_count
        new_pmids = [pmid for pmid in batch if pmid not in seen]
        pmids.extend(new_pmids)
        seen.update(new_pmids)
        if not batch or len(batch) < retmax:
            break
        if raw_count is not None and retstart + len(batch) >= raw_count:
            break
        retstart += len(batch)
    return PubMedSearchResult(pmids, raw_count)


def fetch_pubmed_xml(pmids: list[str]) -> str:
    if not pmids:
        return ""
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    try:
        return _get_text(EFETCH_URL, params)
    except requests.RequestException as exc:
        LOGGER.error("PubMed EFetch failed: %s", exc)
        return ""


def parse_pubmed_xml(xml_text: str, topic: str, fetched_at: str | None = None) -> list[dict[str, str]]:
    if not xml_text.strip():
        return []
    fetched = fetched_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        LOGGER.error("Failed to parse PubMed XML: %s", exc)
        return []
    papers: list[dict[str, str]] = []

    for article in root.findall(".//PubmedArticle"):
        citation = article.find("MedlineCitation")
        article_node = citation.find("Article") if citation is not None else None
        if citation is None or article_node is None:
            continue

        pmid = _text(citation.find("PMID"))
        if not pmid:
            continue

        papers.append(
            {
                "pmid": pmid,
                "title": _text(article_node.find("ArticleTitle")),
                "abstract": _abstract(article_node),
                "journal": _journal(article_node),
                "pub_date": _pub_date(article_node),
                "authors": _authors(article_node),
                "doi": _doi(article),
                "topic": topic,
                "fetched_at": fetched,
            }
        )
    return papers


def _get_json(url: str, params: dict[str, str | int]) -> dict:
    return _request(url, params).json()


def _get_text(url: str, params: dict[str, str | int]) -> str:
    return _request(url, params).text


def _request(url: str, params: dict[str, str | int], timeout: int = 20, retries: int = 3) -> requests.Response:
    params = {**params, "tool": "autobiosci-sentinel-lite"}
    if os.getenv("NCBI_EMAIL"):
        params["email"] = os.environ["NCBI_EMAIL"]
    if os.getenv("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]

    last_error: requests.RequestException | None = None
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise last_error or requests.RequestException("PubMed request failed")


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join(unescape("".join(node.itertext())).split())


def _abstract(article_node: ET.Element) -> str:
    chunks = [_text(node) for node in article_node.findall(".//AbstractText")]
    return " ".join(chunk for chunk in chunks if chunk)


def _journal(article_node: ET.Element) -> str:
    return _text(article_node.find("./Journal/Title")) or _text(article_node.find("./Journal/ISOAbbreviation"))


def _pub_date(article_node: ET.Element) -> str:
    pub_date = article_node.find("./Journal/JournalIssue/PubDate")
    if pub_date is None:
        return ""
    year = _text(pub_date.find("Year"))
    month = _text(pub_date.find("Month"))
    day = _text(pub_date.find("Day"))
    if not year:
        return _text(pub_date.find("MedlineDate"))
    month_num = _month_number(month)
    parts = [year]
    if month_num:
        parts.append(month_num)
    if day:
        parts.append(day.zfill(2))
    return "-".join(parts)


def _month_number(month: str) -> str:
    if not month:
        return ""
    if month.isdigit():
        return month.zfill(2)
    names = {
        "jan": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "may": "05",
        "jun": "06",
        "jul": "07",
        "aug": "08",
        "sep": "09",
        "oct": "10",
        "nov": "11",
        "dec": "12",
    }
    return names.get(month[:3].lower(), "")


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _authors(article_node: ET.Element) -> str:
    names: list[str] = []
    for author in article_node.findall("./AuthorList/Author"):
        collective = _text(author.find("CollectiveName"))
        if collective:
            names.append(collective)
            continue
        last = _text(author.find("LastName"))
        fore = _text(author.find("ForeName"))
        initials = _text(author.find("Initials"))
        name = " ".join(part for part in (fore or initials, last) if part)
        if name:
            names.append(name)
    return "; ".join(names)


def _doi(article: ET.Element) -> str:
    for node in article.findall(".//ArticleId"):
        if node.attrib.get("IdType", "").lower() == "doi":
            return _text(node)
    for node in article.findall(".//ELocationID"):
        if node.attrib.get("EIdType", "").lower() == "doi":
            return _text(node)
    return ""
