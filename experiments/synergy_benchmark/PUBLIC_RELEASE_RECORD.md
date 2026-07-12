# SYNERGY Benchmark Public-Acceptance and Release-Path Record

- Checked at UTC: `2026-07-12T08:42:28Z`
- Machine status: `PASS`
- Benchmark gate status: `HUMAN_ACCEPTANCE_APPROVED`
- Publication status: `PUBLIC_DRAFT_PR`
- Human public-acceptance status: `APPROVED`

This record applies only to `experiments/synergy_benchmark`. It does not approve the repository release, select a software license, confirm authorship, change the root `HUMAN_GATE.yaml`, or authorize upload, tagging, DOI creation, Zenodo publication, or any other external action.

## Reproducible Evidence

Run from the repository root on Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File experiments\synergy_benchmark\run.ps1
```

The latest completed run reports:

- `last_attempt.json`: `status=success`
- `artifacts/results/checks.json`: `passed=true`
- repeat consistency: `passed=true`
- dataset SHA-256: `b28f66230a6dde6e0a32a82fda117e138dca71cebc7efdf71c04fe8b2584e88b`
- timestamp-free ordered sequence SHA-256: `cf57172fbcb6a445aabdc1a03341dfdc0f7f25834befa1cf8db4508451da4d02`
- fixed `seed=535` and `prior_seed=535`

Frozen local evidence hashes:

| Path | SHA-256 |
| --- | --- |
| `README.md` | `2077f4173133cb62d06432c4d0398da21d6e5fb396299bd00ecc8a58fbd40861` |
| `benchmark.py` | `d50daf877bbef1d4379dca50e0a1a0d4331439f0686f4f43e9ac1ed5b398be2b` |
| `benchmark_config.json` | `b8b1c106d8c60878b7d6b3b8b53f73b940dd7ef57154c83b012556247e7bbfbd` |
| `requirements.lock.txt` | `1ded31be2c246496fe7b46dfa5a7ee3f249aaf2782bea509e17020dbabc83d88` |
| `run.ps1` | `a8ed4f3a6324537d4edc34ca9f29accc7b7f65b919d4b5a29c34b7e930c9df6e` |
| `artifacts/results/metrics.json` | `19dddfae914897e8f55449db8640e628028d270885fd41b86d43060cd8931b44` |
| `artifacts/results/failure_cases.csv` | `8301f5391af366c31dcdbab522e6055040be23ecd783178a00a3a5ddc6eb850a` |
| `artifacts/results/repeat_consistency.json` | `a3d65f98fb4cd0c9f2f1e38fc142d33658d9f40150fd4a64e5b9b84bf93e9c14` |
| `artifacts/results/source_manifest.json` | `f96c6d2638cf1f9bb33d30b9dc3034cae5b994a02f3b7e98b6c5d14c62510810` |
| `artifacts/results/checks.json` | `7e8f5ae123820eb52893af2197fa8bfbd53658911f53983bd45e43d9ea889804` |
| `artifacts/results/environment.json` | `0d7e34ee0628cdaed8ce6b8f8740392368cb145be8f544cbacbaf6c24f278f60` |
| `last_attempt.json` | `430e642256698e952a1ccc77dfd78778fb3d344d0826073738e9d5cab3a8ac96` |

Runtime values and archive bytes are expected to vary. Acceptance is based on the pinned input hash, automatic checks, cutoff metrics, and timestamp-free sequence hash.

## Human Public-Acceptance Declaration

The responsible human approved the following declaration in the current task. This records acceptance; it is not evidence that an external publication action occurred:

> I have reviewed the ASReview SYNERGY benchmark package and accept it for public release only as a retrospective methodology artifact. I understand that `label_included` values are inclusion decisions from the source reviews, not AI labels and not an infallible human gold standard. The benchmark does not support clinical or biological conclusions, does not establish prospective stopping performance, and does not demonstrate general performance beyond the recorded dataset, software versions, configuration, and seeds. I approve the stated public file allowlist, exclusions, attribution, privacy scope, software license, and AI-use disclosure, and I accept responsibility for the release decision.

Human confirmation:

- Decision: `approve`
- Name and role: `陆梓溢 — confirmed author and responsible release decision-maker`
- Confirmed at UTC: `2026-07-12T08:43:57Z`
- Root release-gate reference and hash: `HUMAN_GATE.yaml` / `cbe25008d2f4f22271b38d8de62f9d87df126fdc369db9f72d3212d517988683`
- Notes: `Explicit user confirmation: benchmark release approved for the frozen scope in this record.`

## Public File Boundary

Candidate benchmark files to add to a clean public allowlist after the repository-level human gate is approved:

- `.gitignore`
- `README.md`
- `benchmark.py`
- `benchmark_config.json`
- `requirements.txt`
- `requirements.lock.txt`
- `run.ps1`
- `PUBLIC_RELEASE_RECORD.md`
- `last_attempt.json`
- `artifacts/results/checks.json`
- `artifacts/results/environment.json`
- `artifacts/results/failure_cases.csv`
- `artifacts/results/metrics.json`
- `artifacts/results/repeat_consistency.json`
- `artifacts/results/source_manifest.json`

Always exclude:

- `.venv/`
- `data/` and the cached source CSV
- `artifacts/runs/`, `.asreview` archives, and logs
- `.tmp/`, `.pip-tmp/`, `.benchmark_staging/`, `.benchmark_previous/`, lock files, caches, and bytecode
- `gptweb_transport_status.json` and other internal transport/session records
- `HUMAN_GATE.yaml` and other local control/sign-off records; the signed public declaration above is the publishable acceptance record

The SYNERGY source dataset is CC0 1.0. The repository owner has separately approved the MIT License, author identity, privacy scope, and AI-use disclosure in the root `HUMAN_GATE.yaml`; the cached CSV remains excluded. That root approval does not automatically add `experiments/` to the approved public allowlist.

Scope ceiling: this record covers only the frozen files listed above. Later multi-dataset and paper-package additions, including `multi_benchmark.py`, `multi_benchmark_config.json`, `test_multi_benchmark.py`, and `paper_package/`, require a separate scope, hash, and acceptance review before public release.

## Complete Public Release Path

| Step | Current status | Required action |
| --- | --- | --- |
| 1. Local reproducibility and machine checks | `PASS` | Preserve the hashes above; rerun after any material change. |
| 2. Benchmark public-acceptance declaration | `PASS` | Approved by 陆梓溢 at `2026-07-12T08:43:57Z` for the frozen scope in this record. |
| 3. Repository authorship, license, privacy, and AI disclosure | `PASS_ROOT_HUMAN_GATE` | Approved by 陆梓溢 at `2026-07-12T00:19:00Z`: author/ORCID, MIT, privacy boundary, and AI disclosure. |
| 4. Public allowlist | `PROPOSED_IN_DRAFT_PR` | Draft PR #1 adds only the approved frozen files and updates the root clean-history allowlist; merge remains a separate action. |
| 5. Clean build and verification | `PASS_FOR_DRAFT_PR` | Exact source-to-public hashes, benchmark structures, automatic checks, Python/PowerShell syntax, sensitive-content scan, 61 local tests, and GitHub CI passed. |
| 6. GitHub repository and prerelease | `DRAFT_PR_OPEN` | Public Draft PR: `https://github.com/luziyi123448-gif/autobiosci-sentinel-lite/pull/1`; benchmark content commit `43a5ad416b7fc6e7ee0cbb46b3d0a2fe3b384289`. No tag or GitHub Release was created. |
| 7. Zenodo/DOI, if desired | `OPTIONAL_HUMAN_EXTERNAL_ACTION` | After the approved GitHub release, a human may enable archival integration or upload an approved bundle and publish the record. A DOI is not treated as issued until publication. |
| 8. Publication record | `PUBLIC_DRAFT_PR` | PR URL and branch commit are recorded. This is public review state, not a merged release or archived publication. |

Official path references checked on 2026-07-11:

- GitHub releases: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- GitHub licensing: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository
- Zenodo GitHub/software route: https://help.zenodo.org/docs/github/
- Zenodo DOI reservation/publication: https://help.zenodo.org/docs/deposit/describe-records/reserve-doi/
- SYNERGY source and CC0 declaration: https://github.com/asreview/synergy-dataset

## Verdict

The benchmark's deterministic preparation and human public acceptance are complete, and the frozen scope is publicly visible in Draft PR #1 with passing CI. It is not merged, tagged, released, or archived. Remaining actions are PR review/merge and any separately authorized GitHub Release or Zenodo/DOI publication.
