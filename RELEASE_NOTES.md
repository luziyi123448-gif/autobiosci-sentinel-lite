# AutoBioSci Sentinel Lite 0.3.0rc1

**Status: public release candidate.** Human gates are approved. These notes remain prepared for a future tagged GitHub prerelease; no Zenodo record or DOI is claimed here.

## Included

- Deterministic PubMed collection, PMID deduplication, keyword ranking, and accession candidate extraction.
- SQLite-backed bounded run queue.
- Metadata-level review drafting and audit helpers with explicit human gates.
- Experimental AI247 state machine with bounded snapshots, atomic writes, SHA-256 integrity checks, idempotent ticks, immutable released state, and explicit author responsibility acceptance.
- Local, network-free tests and a read-only GitHub Actions test workflow.

## Public boundaries

This software is not a clinical tool, systematic review, full-text evidence synthesis, independent human review, or submission-ready manuscript generator. Generated records and briefs are research aids that require human verification.

## Verification

```bash
python -c "import subprocess,sys; subprocess.check_call([sys.executable,'-m','pip','install','-e','.[dev]']); subprocess.check_call([sys.executable,'-m','pytest','-q'])"
```

Release assets should be limited to the wheel/source bundle produced from the clean public allowlist plus a SHA-256 checksum file. Working databases, cached abstracts, reports, logs, labels, transcripts, and prototype run artifacts are excluded.

## Remaining external actions

- Publish only the clean allowlist repository; never publish the research-workspace history.
- Re-run the recorded checks against the final commit before creating tag `v0.3.0rc1`.
- Create the GitHub prerelease and attach its checksums only when explicitly requested.
- Enable Zenodo and publish a DOI only as a separate, explicit action.
