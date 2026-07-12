# Public Release Checklist — 0.3.0rc1

Status: **PUBLIC RELEASE CANDIDATE**. Human gates are approved. The repository is published from clean allowlist history at `https://github.com/luziyi123448-gif/autobiosci-sentinel-lite`; a GitHub Release, Zenodo record, DOI reservation, and ORCID changes remain separate actions.

HUMAN_GATE: `approved`. The signed local control record is excluded from the public bundle under the approved privacy scope.

## Four required human confirmations

| Gate | Current value | Release condition |
|---|---|---|
| Author | Approved | 陆梓溢; 苏州大学; ORCID `0009-0008-4743-6983`; responsibility accepted. |
| License | Approved | MIT; authority to license confirmed. |
| Privacy/data | Approved | Public allowlist approved; workspace history and generated research artifacts excluded. |
| AI disclosure | Approved | The disclosure in `README.md` was approved verbatim. |

The project is licensed under the MIT License.

## Clean public allowlist

Create the public repository or source archive from only:

- `.github/workflows/ci.yml`, `.github/workflows/daily.yml`
- `.gitattributes`, `.gitignore`, `Makefile`
- `README.md`, `CITATION.cff`, `LICENSE`, `RELEASE_NOTES.md`, `PUBLIC_RELEASE_CHECKLIST.md`, `PORTFOLIO.md`
- `pyproject.toml`
- `configs/topics.yaml`
- `src/autobiosci_sentinel/`
- `tests/`
- The frozen single-dataset benchmark files enumerated in `experiments/synergy_benchmark/PUBLIC_RELEASE_RECORD.md`; no other `experiments/` content.

Exclude `AGENTS.md`, `PROJECT_STATE.md`, the root `HUMAN_GATE.yaml`, `.codex/`, `.codex_tmp/`, `data/`, `outputs/`, `reports/`, `logs/`, `tmp/`, `to_gpt/`, `prototype/ai247/`, every unlisted `experiments/` file, caches, secrets, and all local review transcripts. Within the approved benchmark, exclude its cached CSV, `.venv/`, raw `.asreview` archives, logs, temporary directories, multi-dataset additions, paper package, and internal GPTweb transport record. The manual collector workflow is included only after removal of its artifact-upload step, so generated research files remain on its ephemeral runner. The current research-workspace history remains excluded; public changes continue from the clean allowlist history.

## GitHub prerelease

1. Verify the version in `pyproject.toml`, `src/autobiosci_sentinel/__init__.py`, `CITATION.cff`, and `RELEASE_NOTES.md`.
2. Run the reproduction command in a clean environment.
3. Build the wheel from the clean public checkout and record SHA-256 checksums.
4. Create tag `v0.3.0rc1` from the verified commit.
5. Create a **prerelease** using `RELEASE_NOTES.md`; attach only the wheel and checksum file. GitHub automatically adds tag-based source archives.

Repository target: `https://github.com/luziyi123448-gif/autobiosci-sentinel-lite`.

## Citation, Zenodo, DOI, and ORCID

- `CITATION.cff` records the confirmed author, affiliation, and author-verified ORCID iD.
- Zenodo can ingest `CITATION.cff` for GitHub software releases. Do not also add `.zenodo.json` unless Zenodo-specific metadata is needed, because `.zenodo.json` takes precedence over `CITATION.cff`.
- After a tagged GitHub prerelease, a human may connect the repository to Zenodo. A DOI may be reserved in a draft, but it is registered only when the record is published. Do not infer a DOI until that separate action succeeds.
- ORCID records are controlled and created by the researchers themselves. Collect only authenticated, author-approved ORCID iDs.

## Final machine checks

- [x] `python -m pytest -q` passes from the current source tree (61 passed).
- [x] A wheel builds from the clean allowlist checkout.
- [x] The wheel installs in a fresh environment and both module `--help` commands run.
- [x] `CITATION.cff` parses and passes a CFF 1.2 validator after author replacement.
- [x] SHA-256 checksums match the final assets.
- [x] A forbidden-claim scan finds no positive claim of clinical use, completed systematic review, independent human review, or submission readiness.

## Official references checked 2026-07-11

- GitHub releases: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- GitHub repository licensing: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository
- Citation File Format 1.2 schema guide: https://github.com/citation-file-format/citation-file-format/blob/main/schema-guide.md
- Zenodo GitHub integration: https://help.zenodo.org/docs/github/
- Zenodo DOI reservation: https://help.zenodo.org/docs/deposit/describe-records/reserve-doi/
- Zenodo creators: https://help.zenodo.org/docs/deposit/describe-records/creators/
- ORCID researcher control: https://info.orcid.org/what-is-orcid/services/orcid-registry/
