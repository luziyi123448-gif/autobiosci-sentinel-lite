# AutoBioSci Sentinel Lite

AutoBioSci Sentinel Lite is a small, deterministic PubMed literature radar. It collects configured PubMed records, stores them in SQLite, deduplicates by PMID, ranks them with transparent keyword rules, extracts possible public dataset accessions, and writes Markdown reports.

The package also contains an experimental **AI247 metadata evidence-brief prototype**. That prototype freezes a bounded set of PubMed metadata and abstracts, records SHA-256 integrity hashes, and requires an explicitly named responsible author before its own release transition.

> **Research-use boundary:** this software is not a clinical tool, does not provide medical advice, does not perform a systematic review, does not verify full text, and does not produce submission-ready scholarship. Its scores and generated briefs require human review.

`0.3.0rc1` is a public release candidate. Its authorship, MIT license, privacy scope, and AI-use disclosure were approved through the local human gate; a tagged GitHub Release and Zenodo record remain separate actions.

## Install and test

Use Python 3.11 or newer from a source checkout:

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

One-command reproduction:

```bash
python -c "import subprocess,sys; subprocess.check_call([sys.executable,'-m','pip','install','-e','.[dev]']); subprocess.check_call([sys.executable,'-m','pytest','-q'])"
```

Tests use local fixtures and mocks; they do not require network access.

## Run the literature radar

```bash
python -m autobiosci_sentinel.cli run \
  --config configs/topics.yaml \
  --db data/papers.sqlite \
  --report reports/daily_report.md
```

This command contacts NCBI PubMed and writes the selected database and report paths. `NCBI_EMAIL` and `NCBI_API_KEY` are optional environment variables; never commit API keys.

See available bounded queue and audit commands with:

```bash
python -m autobiosci_sentinel.cli --help
python -m autobiosci_sentinel.prototype --help
```

## What is deterministic

- PMID deduplication and keyword scoring.
- Regex-based accession candidate extraction.
- SQLite-backed bounded queue state.
- AI247 snapshot serialization, evidence-table structure, and SHA-256 integrity checks.
- Local unit tests.

PubMed search results and remote metadata can change over time. A saved query, retrieval date, configuration, and frozen snapshot are therefore required to reproduce a particular literature result.

## Data, privacy, and AI disclosure

The public software RC is limited to source code, tests, and example configuration. It excludes the working SQLite database, cached PubMed abstracts, generated reports, logs, validation labels, AI review transcripts, and local prototype run artifacts.

PubMed metadata and abstracts remain subject to their source terms. Users are responsible for checking redistribution rights before sharing generated datasets or snapshots. The package itself does not send content to an LLM. AI systems were used during development for code and documentation assistance and mechanical review; all public claims, authorship, licensing, and release decisions remain human responsibilities.

## Known limitations

- Keyword scoring is a prioritization heuristic, not scientific evidence grading.
- Accession extraction is regex-based and can produce false positives or miss full-text-only accessions.
- Network errors can produce incomplete retrievals.
- Review-package commands create metadata-level drafting aids only; they do not complete eligibility decisions, risk-of-bias assessment, biological interpretation, or clinical validation.
- The AI247 prototype is experimental and its generated brief is not independently human-reviewed unless a separate review is documented.

## Release materials

- [CITATION.cff](CITATION.cff) — confirmed author and ORCID metadata.
- [RELEASE_NOTES.md](RELEASE_NOTES.md) — draft GitHub Release notes.
- [PUBLIC_RELEASE_CHECKLIST.md](PUBLIC_RELEASE_CHECKLIST.md) — GitHub, Zenodo, ORCID, privacy, licensing, and clean-repository gates.
- [PORTFOLIO.md](PORTFOLIO.md) — one-page professional project summary.

Copyright 2026 陆梓溢. Licensed under the [MIT License](LICENSE).
