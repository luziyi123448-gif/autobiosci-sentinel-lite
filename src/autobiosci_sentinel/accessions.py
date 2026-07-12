from __future__ import annotations

import re


ACCESSION_RE = re.compile(
    r"\b(?:GSE\d+|GSM\d+|SRP\d+|SRR\d+|SRS\d+|PRJNA\d+|ERP\d+|ERR\d+|E-MTAB-\d+)\b",
    re.IGNORECASE,
)


def extract_accessions(text: str) -> list[str]:
    return sorted({match.group(0).upper() for match in ACCESSION_RE.finditer(text or "")})


def describe_accession(accession: str) -> dict[str, str]:
    value = accession.upper()
    if value.startswith(("GSE", "GSM")):
        return _metadata(value, "GEO", f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={value}")
    if value.startswith(("SRP", "SRR", "SRS")):
        return _metadata(value, "SRA", f"https://www.ncbi.nlm.nih.gov/sra/?term={value}")
    if value.startswith("PRJNA"):
        return _metadata(value, "BioProject", f"https://www.ncbi.nlm.nih.gov/bioproject/{value}")
    if value.startswith(("ERP", "ERR")):
        return _metadata(value, "ENA", f"https://www.ebi.ac.uk/ena/browser/view/{value}")
    if value.startswith("E-MTAB-"):
        return _metadata(value, "ArrayExpress", f"https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{value}")
    return _metadata(value, "Unknown", "")


def describe_accessions(accessions: list[str]) -> list[dict[str, str]]:
    return [describe_accession(accession) for accession in sorted({item.upper() for item in accessions if item})]


def _metadata(accession: str, source: str, url: str) -> dict[str, str]:
    return {"accession": accession, "source": source, "url": url}
