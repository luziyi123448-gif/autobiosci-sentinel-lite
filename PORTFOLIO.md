# AutoBioSci Sentinel Lite / AI247 Prototype

**Author:** 陆梓溢, Soochow University (苏州大学), ORCID `0009-0008-4743-6983`

**Artifact:** research-software release candidate, version `0.3.0rc1`

**Stack:** Python, SQLite, PubMed E-utilities, GitHub Actions

## The problem

Biomedical literature monitoring is easy to automate badly: search results change, duplicates accumulate, ranking logic becomes opaque, and generated prose can appear more authoritative than its evidence. AutoBioSci Sentinel Lite explores a smaller, auditable alternative for researchers who need a repeatable PubMed watchlist without an agent framework or cloud platform.

## What was built

The software reads versioned topic definitions, retrieves PubMed metadata, deduplicates by PMID, applies deterministic keyword scoring, extracts possible dataset accession identifiers, stores bounded run state in SQLite, and produces inspectable Markdown and CSV artifacts. Local tests replace network calls with fixtures and mocks.

The AI247 prototype adds a narrow release-state machine for metadata evidence briefs. It freezes a bounded record set, writes artifacts atomically, records SHA-256 hashes, treats repeated unchanged runs as idempotent, refuses release after artifact tampering, makes released state immutable, and requires an exact author identity plus explicit responsibility acceptance.

## Engineering choices

- Deterministic rules before model-generated judgment.
- SQLite and the Python standard library before extra infrastructure.
- Explicit state, hashes, and human gates instead of hidden automation.
- A clean public allowlist that excludes databases, abstracts, reports, logs, labels, transcripts, and local run artifacts.
- Network-free tests for the reproducible software core.

## Honest boundary

This is a literature-radar and metadata-brief prototype, not a clinical tool, systematic review, full-text synthesis, evidence-grading system, or submission-ready manuscript generator. Keyword scores are prioritization heuristics. Accession extraction is regex-based. Remote PubMed results may change. Scientific interpretation, authorship, licensing, privacy decisions, and any public release remain human responsibilities.

## Reproduce

```bash
python -c "import subprocess,sys; subprocess.check_call([sys.executable,'-m','pip','install','-e','.[dev]']); subprocess.check_call([sys.executable,'-m','pytest','-q'])"
```

## Release status

The four human gates—author/ORCID, MIT license, privacy and redistribution scope, and AI-use disclosure—are approved. Repository publication uses a clean allowlist history; a tagged GitHub Release and Zenodo DOI remain separate actions.
