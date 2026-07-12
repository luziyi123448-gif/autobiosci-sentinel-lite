#!/usr/bin/env python3
import csv
import hashlib
import json
import math
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from contextlib import contextmanager
from importlib.metadata import version
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "benchmark_config.json"
DATA_DIR = ROOT / "data"
ARTIFACTS_DIR = ROOT / "artifacts"
STAGING_DIR = ROOT / ".benchmark_staging"
BACKUP_DIR = ROOT / ".benchmark_previous"
RUNS_DIR = STAGING_DIR / "runs"
RESULTS_DIR = STAGING_DIR / "results"
TMP_DIR = ROOT / ".tmp"
LAST_ATTEMPT_PATH = ROOT / "last_attempt.json"
LOCK_PATH = ROOT / ".benchmark.lock"
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MAX_ZIP_MEMBERS = 20
MAX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_MEMBER_BYTES = 10 * 1024 * 1024
THREAD_ENV = {
    "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
NORMALIZED_FIELDS = (
    "record_id",
    "label",
    "classifier",
    "querier",
    "balancer",
    "feature_extractor",
    "training_set",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def ensure_inside_root(path, allow_root=False):
    resolved = path.resolve()
    root_resolved = ROOT.resolve()
    if resolved == root_resolved:
        if allow_root:
            return resolved
        raise RuntimeError(f"Refusing to target benchmark root directly: {resolved}")
    if root_resolved not in resolved.parents:
        raise RuntimeError(f"Path escapes benchmark root: {resolved}")
    return resolved


def write_json(path, value):
    ensure_inside_root(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    ensure_inside_root(temporary)
    try:
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reset_owned(path, parent):
    resolved = ensure_inside_root(path)
    parent_resolved = ensure_inside_root(parent, allow_root=True)
    if resolved == parent_resolved or parent_resolved not in resolved.parents:
        raise RuntimeError(f"Refusing cleanup outside {parent_resolved}: {resolved}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


class BenchmarkLockedError(RuntimeError):
    pass


@contextmanager
def benchmark_lock():
    ensure_inside_root(LOCK_PATH)
    stream = LOCK_PATH.open("a+b")
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        stream.close()
        raise BenchmarkLockedError("Another benchmark run holds the lock") from error
    try:
        yield
    finally:
        stream.seek(0)
        if os.name == "nt":
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def prepare_staging():
    for path in (
        DATA_DIR,
        ARTIFACTS_DIR,
        STAGING_DIR,
        BACKUP_DIR,
        TMP_DIR,
        Path(sys.executable),
    ):
        ensure_inside_root(path)
    if BACKUP_DIR.exists():
        if ARTIFACTS_DIR.exists():
            reset_owned(BACKUP_DIR, ROOT)
        else:
            BACKUP_DIR.rename(ARTIFACTS_DIR)
    reset_owned(STAGING_DIR, ROOT)
    RUNS_DIR.mkdir(parents=True)
    RESULTS_DIR.mkdir(parents=True)


def publish_artifacts():
    if not STAGING_DIR.is_dir():
        raise RuntimeError("Benchmark staging directory is missing")
    if BACKUP_DIR.exists():
        raise RuntimeError("Benchmark backup directory was not recovered")
    if ARTIFACTS_DIR.exists():
        ARTIFACTS_DIR.rename(BACKUP_DIR)
    try:
        STAGING_DIR.rename(ARTIFACTS_DIR)
    except Exception:
        if BACKUP_DIR.exists() and not ARTIFACTS_DIR.exists():
            BACKUP_DIR.rename(ARTIFACTS_DIR)
        raise
    if BACKUP_DIR.exists():
        reset_owned(BACKUP_DIR, ROOT)


def validate_versions(config):
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError(f"Python 3.13 is required, got {sys.version.split()[0]}")
    actual = {name: version(name) for name in config["required_versions"]}
    if actual != config["required_versions"]:
        raise RuntimeError(
            f"Package versions do not match benchmark_config.json: {actual}"
        )
    locked = sorted(
        line.strip()
        for line in (ROOT / "requirements.lock.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    )
    frozen = sorted(
        subprocess.run(
            [sys.executable, "-m", "pip", "freeze", "--all"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        ).stdout.splitlines()
    )
    if locked != frozen:
        raise RuntimeError("Installed packages differ from requirements.lock.txt")
    return actual, frozen


def read_response_limited(response, limit):
    declared = response.headers.get("Content-Length")
    if declared and int(declared) > limit:
        raise RuntimeError(f"Download exceeds {limit} bytes")
    chunks = []
    size = 0
    for chunk in response.iter_content(64 * 1024):
        size += len(chunk)
        if size > limit:
            raise RuntimeError(f"Download exceeds {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def download_synergy_subset(config, data_path):
    import requests
    from synergy_dataset import Dataset

    version_id = config["synergy_version"]
    metadata_url = (
        "https://dataverse.nl/api/datasets/:persistentId/versions/"
        f"{version_id}?persistentId=doi:10.34894/HE6NAQ"
    )
    with requests.get(metadata_url, timeout=30, stream=True) as response:
        response.raise_for_status()
        metadata_payload = read_response_limited(response, 5 * 1024 * 1024)
    files = json.loads(metadata_payload)["data"]["files"]
    directory_label = f"synergy-dataset-v{version_id}/{config['dataset_id']}"
    file_ids = sorted(
        item["dataFile"]["id"]
        for item in files
        if item.get("directoryLabel") == directory_label
    )
    if not file_ids:
        raise RuntimeError(f"No Dataverse files found for {directory_label}")

    subset_url = "https://dataverse.nl/api/access/datafiles/" + ",".join(
        str(file_id) for file_id in file_ids
    )
    with requests.get(subset_url, timeout=30, stream=True) as response:
        response.raise_for_status()
        subset_payload = read_response_limited(response, MAX_DOWNLOAD_BYTES)

    reset_owned(TMP_DIR, ROOT)
    TMP_DIR.mkdir()
    try:
        with zipfile.ZipFile(BytesIO(subset_payload)) as source:
            temp_root = TMP_DIR.resolve()
            members = source.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise RuntimeError("Downloaded ZIP contains too many members")
            if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
                raise RuntimeError("Downloaded ZIP expands beyond the size limit")
            for member in members:
                if member.file_size > MAX_MEMBER_BYTES:
                    raise RuntimeError(f"Oversized ZIP member: {member.filename}")
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RuntimeError(f"ZIP symlink is not allowed: {member.filename}")
                destination = (TMP_DIR / member.filename).resolve()
                if destination != temp_root and temp_root not in destination.parents:
                    raise RuntimeError(f"Unsafe ZIP member: {member.filename}")
            source.extractall(TMP_DIR)

        dataset_dir = TMP_DIR / directory_label
        required = {"labels.csv", "metadata.json", "metadata_publication.json"}
        if not dataset_dir.is_dir() or not required.issubset(
            {path.name for path in dataset_dir.iterdir()}
        ):
            raise RuntimeError("Downloaded SYNERGY subset is incomplete")
        Dataset(config["dataset_id"], path=dataset_dir).to_frame().to_csv(data_path)
    finally:
        reset_owned(TMP_DIR, ROOT)
    return {
        "metadata_url": metadata_url,
        "subset_download_url": subset_url,
        "subset_file_count": len(file_ids),
    }


def load_and_validate_dataset(config):
    DATA_DIR.mkdir(exist_ok=True)
    data_path = DATA_DIR / f'{config["dataset_id"]}.csv'
    ensure_inside_root(data_path)
    downloaded = False
    retrieval_details = {"source": "verified local cached copy"}
    previous_manifest = {}
    previous_manifest_path = ARTIFACTS_DIR / "results" / "source_manifest.json"
    if previous_manifest_path.is_file():
        previous_manifest = json.loads(
            previous_manifest_path.read_text(encoding="utf-8")
        )

    if not data_path.exists():
        try:
            retrieval_details = download_synergy_subset(config, data_path)
            downloaded = True
        except Exception:
            if data_path.exists():
                data_path.unlink()
            raise

    digest = file_sha256(data_path)
    if digest != config["expected_sha256"]:
        raise RuntimeError(
            f"Dataset SHA-256 mismatch: expected {config['expected_sha256']}, got {digest}"
        )
    if not downloaded and previous_manifest.get("sha256") == digest:
        retrieval_details = previous_manifest.get(
            "retrieval_details", retrieval_details
        )

    with data_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = reader.fieldnames or []

    label_column = config["label_column"]
    if label_column not in fields:
        raise RuntimeError(f"Missing label column: {label_column}")
    if any(row[label_column] not in {"0", "1"} for row in rows):
        raise RuntimeError("Dataset is not fully labeled with binary 0/1 values")

    relevant = sum(row[label_column] == "1" for row in rows)
    missing_titles = sum(not (row.get("title") or "").strip() for row in rows)
    missing_abstracts = sum(not (row.get("abstract") or "").strip() for row in rows)
    observed = {
        "bytes": data_path.stat().st_size,
        "records": len(rows),
        "relevant": relevant,
    }
    expected = {
        "bytes": config["expected_bytes"],
        "records": config["expected_records"],
        "relevant": config["expected_relevant"],
    }
    if observed != expected:
        raise RuntimeError(f"Dataset shape mismatch: expected {expected}, got {observed}")

    manifest = {
        "schema_version": 1,
        "checked_at_utc": utc_now(),
        "downloaded_this_run": downloaded,
        "local_file_mtime_utc": datetime.fromtimestamp(
            data_path.stat().st_mtime, timezone.utc
        ).isoformat(),
        "first_retrieved_at_utc": previous_manifest.get(
            "first_retrieved_at_utc",
            datetime.fromtimestamp(data_path.stat().st_mtime, timezone.utc).isoformat(),
        ),
        "dataset_id": config["dataset_id"],
        "asreview_dataset_id": config["asreview_dataset_id"],
        "dataset_release": config["dataset_release"],
        "retrieval_method": "official Dataverse metadata plus selected subset files",
        "retrieval_details": retrieval_details,
        "source_package": f"synergy-dataset=={version('synergy-dataset')}",
        "local_path": str(data_path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": digest,
        "bytes": observed["bytes"],
        "records": observed["records"],
        "label_counts": {
            "included_1": relevant,
            "excluded_0": len(rows) - relevant,
            "missing": 0,
        },
        "missing_text_counts": {
            "title": missing_titles,
            "abstract": missing_abstracts,
        },
        "columns": fields,
        "label_semantics": (
            "label_included=1 means included by the source systematic review "
            "after full-text screening; 0 means excluded. These are source-review "
            "decisions, not an infallible human gold standard."
        ),
        "license": "CC0-1.0",
        "official_sources": [
            "https://github.com/asreview/synergy-dataset",
            "https://doi.org/10.34894/HE6NAQ",
        ],
        "raw_data_publication_policy": (
            "Local benchmark input only; do not publish or redistribute this cached CSV."
        ),
    }
    return data_path, rows, manifest


def cli_metric(text, name):
    match = re.search(rf"(?m)^{re.escape(name)}:\s*([0-9.]+)\s*$", text)
    return float(match.group(1)) if match else None


def run_simulation(config, data_path, repeat):
    RUNS_DIR.mkdir(exist_ok=True)
    archive = RUNS_DIR / f"run_{repeat}.asreview"
    stdout_log = RUNS_DIR / f"run_{repeat}.stdout.log"
    stderr_log = RUNS_DIR / f"run_{repeat}.stderr.log"
    for path in (
        archive,
        Path(f"{archive}.tmp"),
        archive.with_suffix(".tmp"),
        stdout_log,
        stderr_log,
    ):
        reset_owned(path, RUNS_DIR)

    cli = Path(sys.executable).with_name(
        "asreview.exe" if os.name == "nt" else "asreview"
    )
    ensure_inside_root(cli)
    if not cli.is_file():
        raise RuntimeError(f"ASReview CLI not found next to Python: {cli}")

    command = [
        str(cli),
        "simulate",
        str(data_path),
        "-o",
        str(archive),
        "--ai",
        config["ai"],
        "--seed",
        str(config["seed"]),
        "--prior-seed",
        str(config["prior_seed"]),
        "--n-prior-included",
        str(config["n_prior_included"]),
        "--n-prior-excluded",
        str(config["n_prior_excluded"]),
        "--n-query",
        str(config["n_query"]),
        "--n-stop",
        str(config["n_stop"]),
    ]
    if config["group_similar_records"]:
        command.append("--group-similar-records")
    environment = os.environ.copy()
    environment.update(THREAD_ENV)
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    runtime = time.perf_counter() - started
    stdout_log.write_text(completed.stdout, encoding="utf-8", newline="")
    stderr_log.write_text(completed.stderr, encoding="utf-8", newline="")
    if completed.returncode != 0:
        raise RuntimeError(
            f"ASReview repeat {repeat} failed with exit code {completed.returncode}; "
            f"see {stderr_log}"
        )
    if not archive.is_file():
        raise RuntimeError(f"ASReview did not create {archive}")

    replay = (
        f"asreview simulate data/{config['dataset_id']}.csv "
        f"-o artifacts/runs/run_{repeat}.asreview --ai {config['ai']} "
        f"--seed {config['seed']} --prior-seed {config['prior_seed']} "
        f"--n-prior-included {config['n_prior_included']} "
        f"--n-prior-excluded {config['n_prior_excluded']} "
        f"--n-query {config['n_query']} --n-stop {config['n_stop']}"
    )
    if config["group_similar_records"]:
        replay += " --group-similar-records"
    stable_archive = ARTIFACTS_DIR / "runs" / archive.name
    stable_stdout = ARTIFACTS_DIR / "runs" / stdout_log.name
    stable_stderr = ARTIFACTS_DIR / "runs" / stderr_log.name
    return {
        "repeat": repeat,
        "runtime_seconds": runtime,
        "return_code": completed.returncode,
        "archive_path": str(stable_archive.relative_to(ROOT)).replace("\\", "/"),
        "archive_sha256": file_sha256(archive),
        "stdout_log": str(stable_stdout.relative_to(ROOT)).replace("\\", "/"),
        "stderr_log": str(stable_stderr.relative_to(ROOT)).replace("\\", "/"),
        "replay_command": replay,
        "asreview_loss": cli_metric(completed.stdout, "Loss"),
        "asreview_ndcg": cli_metric(completed.stdout, "NDCG"),
    }, archive


def read_archive(archive):
    TMP_DIR.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as source, tempfile.TemporaryDirectory(
        dir=TMP_DIR
    ) as tmp:
        project = json.loads(source.read("project.json"))
        db_path = Path(tmp, "results.db")
        db_path.write_bytes(source.read("results.db"))
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        try:
            sequence = [
                dict(row)
                for row in connection.execute(
                    "SELECT record_id, label, classifier, querier, balancer, "
                    "feature_extractor, training_set, time FROM results ORDER BY rowid"
                )
            ]
            records = {
                row["record_id"]: dict(row)
                for row in connection.execute(
                    "SELECT record_id, dataset_row, included, duplicate_of "
                    "FROM record ORDER BY record_id"
                )
            }
        finally:
            connection.close()
    return project, sequence, records


def metrics_at_recall(sequence, recall_target):
    labels = [int(row["label"]) for row in sequence]
    total = len(labels)
    relevant = sum(labels)
    target_relevant = math.ceil(recall_target * relevant - 1e-12)
    found = 0
    cutoff = None
    for rank, label in enumerate(labels, start=1):
        found += label
        if found >= target_relevant:
            cutoff = rank
            break
    if cutoff is None:
        raise RuntimeError("Recall target is not attainable from the result sequence")

    tp = found
    fp = cutoff - tp
    fn = relevant - tp
    tn = (total - relevant) - fp
    screened_fraction = cutoff / total
    work_saved_fraction = (tn + fn) / total
    return {
        "recall_target": recall_target,
        "target_relevant_records": target_relevant,
        "cutoff_rule": "smallest full-ranking prefix with recall >= target",
        "cutoff_includes_prior_records": True,
        "screened_records": cutoff,
        "screened_fraction": screened_fraction,
        "precision_screened_set": tp / cutoff,
        "recall": tp / relevant,
        "missed_relevant_records": fn,
        "work_saved_fraction": work_saved_fraction,
        "wss_at_target_recall": work_saved_fraction - (1 - recall_target),
        "confusion_counts": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def normalized_sequence_hash(sequence):
    normalized = [
        {field: row[field] for field in NORMALIZED_FIELDS} for row in sequence
    ]
    payload = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def self_check():
    synthetic = [{"label": label} for label in (1, 0, 1, 0, 0)]
    metrics = metrics_at_recall(synthetic, 0.5)
    assert metrics["screened_records"] == 1
    assert metrics["confusion_counts"] == {"tp": 1, "fp": 0, "fn": 1, "tn": 3}
    assert math.isclose(metrics["precision_screened_set"], 1.0)
    assert math.isclose(metrics["recall"], 0.5)
    assert math.isclose(metrics["work_saved_fraction"], 0.8)
    assert math.isclose(metrics["wss_at_target_recall"], 0.3)
    return True


def write_failure_cases(path, cases):
    fields = [
        "record_id",
        "dataset_row",
        "openalex_id",
        "doi",
        "title",
        "discovery_rank",
        "cutoff_rank",
        "failure_type",
        "label_source",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(cases)


def environment_record(package_versions, freeze):
    return {
        "recorded_at_utc": utc_now(),
        "python": sys.version,
        "python_executable_relative": ".venv/Scripts/python.exe"
        if os.name == "nt"
        else ".venv/bin/python",
        "platform": platform.platform(),
        "required_package_versions": package_versions,
        "thread_environment": {name: os.environ.get(name) for name in THREAD_ENV},
        "pip_freeze_all": freeze,
    }


def main():
    benchmark_started = time.perf_counter()
    prepare_staging()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    package_versions, freeze = validate_versions(config)
    synthetic_metric_check = self_check()
    data_path, dataset_rows, source_manifest = load_and_validate_dataset(config)

    write_json(RESULTS_DIR / "source_manifest.json", source_manifest)
    write_json(
        RESULTS_DIR / "environment.json",
        environment_record(package_versions, freeze),
    )

    run_records = []
    parsed_runs = []
    for repeat in range(1, config["repeats"] + 1):
        run_record, archive = run_simulation(config, data_path, repeat)
        project, sequence, records = read_archive(archive)
        if len(sequence) != config["expected_records"]:
            raise RuntimeError(f"Repeat {repeat} did not produce a full ranking")
        if len(records) != config["expected_records"]:
            raise RuntimeError(f"Repeat {repeat} record table size mismatch")
        if any(int(row["label"]) != int(records[row["record_id"]]["included"]) for row in sequence):
            raise RuntimeError(f"Repeat {repeat} result labels do not match record labels")

        priors = [row for row in sequence if row["classifier"] is None]
        if len(priors) != 2 or sorted(int(row["label"]) for row in priors) != [0, 1]:
            raise RuntimeError(f"Repeat {repeat} prior labels differ from the design")

        metric = metrics_at_recall(sequence, config["recall_target"])
        sequence_hash = normalized_sequence_hash(sequence)
        if sequence_hash != config["expected_normalized_sequence_sha256"]:
            raise RuntimeError(
                f"Repeat {repeat} normalized sequence differs from the expected hash"
            )
        components = sorted(
            {
                (
                    row["classifier"],
                    row["querier"],
                    row["balancer"],
                    row["feature_extractor"],
                )
                for row in sequence
                if row["classifier"] is not None
            }
        )
        run_record.update(
            {
                "project_file_version": project["project_file_version"],
                "result_rows": len(sequence),
                "duplicate_of_count": sum(
                    record["duplicate_of"] is not None for record in records.values()
                ),
                "observed_model_components": [
                    {
                        "classifier": item[0],
                        "querier": item[1],
                        "balancer": item[2],
                        "feature_extractor": item[3],
                    }
                    for item in components
                ],
                "normalized_sequence_fields": list(NORMALIZED_FIELDS),
                "normalized_sequence_sha256": sequence_hash,
                "metrics": metric,
            }
        )
        run_records.append(run_record)
        parsed_runs.append((sequence, records, metric, sequence_hash))

    sequence_identical = len({item[3] for item in parsed_runs}) == 1
    metrics_identical = all(item[2] == parsed_runs[0][2] for item in parsed_runs[1:])
    repeat_consistency = {
        "same_input_sha256": True,
        "same_seed_and_prior_seed": True,
        "normalized_sequence_identical": sequence_identical,
        "cutoff_metrics_identical": metrics_identical,
        "matches_expected_normalized_sequence_sha256": all(
            item[3] == config["expected_normalized_sequence_sha256"]
            for item in parsed_runs
        ),
        "archive_bytes_expected_identical": False,
        "passed": sequence_identical
        and metrics_identical
        and all(
            item[3] == config["expected_normalized_sequence_sha256"]
            for item in parsed_runs
        ),
        "note": (
            "Archive hashes and timestamps are not compared for determinism; the "
            "timestamp-free ordered labeling sequence is authoritative."
        ),
    }

    sequence, records, primary_metrics, _ = parsed_runs[0]
    rank_by_record = {
        row["record_id"]: rank for rank, row in enumerate(sequence, start=1)
    }
    cutoff = primary_metrics["screened_records"]
    failure_cases = []
    for record_id, record in records.items():
        rank = rank_by_record[record_id]
        if int(record["included"]) == 1 and rank > cutoff:
            source_row = dataset_rows[int(record["dataset_row"])]
            failure_cases.append(
                {
                    "record_id": record_id,
                    "dataset_row": record["dataset_row"],
                    "openalex_id": source_row.get("openalex_id", ""),
                    "doi": source_row.get("doi", ""),
                    "title": source_row.get("title", ""),
                    "discovery_rank": rank,
                    "cutoff_rank": cutoff,
                    "failure_type": "relevant record beyond retrospective 95% recall cutoff",
                    "label_source": "SYNERGY label_included from source review",
                }
            )
    failure_cases.sort(key=lambda row: row["discovery_rank"])
    write_failure_cases(RESULTS_DIR / "failure_cases.csv", failure_cases)

    checks = {
        "synthetic_metric_self_check": synthetic_metric_check,
        "dataset_sha256_matches": source_manifest["sha256"] == config["expected_sha256"],
        "all_dataset_rows_labeled": source_manifest["label_counts"]["missing"] == 0,
        "both_runs_cover_all_records": all(
            run["result_rows"] == config["expected_records"] for run in run_records
        ),
        "repeat_consistency": repeat_consistency["passed"],
        "expected_sequence_hash_matches": all(
            run["normalized_sequence_sha256"]
            == config["expected_normalized_sequence_sha256"]
            for run in run_records
        ),
        "failure_case_count_matches_fn": len(failure_cases)
        == primary_metrics["missed_relevant_records"],
    }
    checks_record = {"checks": checks, "passed": all(checks.values())}
    write_json(RESULTS_DIR / "checks.json", checks_record)
    write_json(RESULTS_DIR / "repeat_consistency.json", repeat_consistency)

    metrics_record = {
        "schema_version": 1,
        "benchmark_id": config["benchmark_id"],
        "generated_at_utc": utc_now(),
        "overall_runtime_seconds": time.perf_counter() - benchmark_started,
        "dataset": {
            "id": config["dataset_id"],
            "release": config["dataset_release"],
            "sha256": source_manifest["sha256"],
            "records": config["expected_records"],
            "relevant": config["expected_relevant"],
            "fully_labeled": True,
            "missing_text_counts": source_manifest["missing_text_counts"],
        },
        "method": {
            "asreview_version": package_versions["asreview"],
            "synergy_dataset_package_version": package_versions["synergy-dataset"],
            "ai": config["ai"],
            "seed": config["seed"],
            "prior_seed": config["prior_seed"],
            "n_prior_included": config["n_prior_included"],
            "n_prior_excluded": config["n_prior_excluded"],
            "n_query": config["n_query"],
            "n_stop": config["n_stop"],
            "group_similar_records": config["group_similar_records"],
            "repeats": config["repeats"],
            "evaluation": "retrospective cutoff reconstructed from full rankings",
        },
        "metric_definitions": {
            "precision_screened_set": "relevant screened / all screened at cutoff",
            "recall": "relevant screened / all SYNERGY relevant records",
            "missed_relevant_records": "SYNERGY relevant records after cutoff",
            "work_saved_fraction": "unscreened records / all records",
            "wss_at_target_recall": (
                "work_saved_fraction - (1 - recall_target), equivalent to "
                "recall_target - screened_fraction"
            ),
        },
        "runs": run_records,
        "repeat_consistency": repeat_consistency,
        "failure_cases_path": "artifacts/results/failure_cases.csv",
        "failure_case_count": len(failure_cases),
        "automatic_checks_passed": checks_record["passed"],
        "interpretation_limits": [
            "One small retrospective dataset cannot establish general performance.",
            "The 95% cutoff uses complete labels and is not a deployable prospective stopping rule.",
            "Source-review inclusion decisions may contain errors and are not an infallible gold standard.",
            "Precision here is screening yield, not classifier precision on unseen predictions.",
            "Runtime is hardware and environment specific.",
            f"{source_manifest['missing_text_counts']['abstract']} record has no abstract.",
            "Pinned package versions are checked, but wheel hashes are not locked.",
            "No clinical or biological conclusions are supported.",
        ],
    }
    write_json(RESULTS_DIR / "metrics.json", metrics_record)
    if not checks_record["passed"]:
        raise RuntimeError("One or more automatic checks failed")
    publish_artifacts()
    return {
        "metrics": "artifacts/results/metrics.json",
        "failure_cases": "artifacts/results/failure_cases.csv",
        "repeat_consistency_passed": repeat_consistency["passed"],
        "automatic_checks_passed": checks_record["passed"],
    }


if __name__ == "__main__":
    try:
        with benchmark_lock():
            try:
                summary = main()
                write_json(
                    LAST_ATTEMPT_PATH,
                    {"timestamp_utc": utc_now(), "status": "success", **summary},
                )
                print(json.dumps(summary))
            except Exception as error:
                write_json(
                    LAST_ATTEMPT_PATH,
                    {
                        "timestamp_utc": utc_now(),
                        "status": "failed",
                        "error_type": type(error).__name__,
                        "message": str(error),
                    },
                )
                raise
            finally:
                reset_owned(TMP_DIR, ROOT)
                reset_owned(STAGING_DIR, ROOT)
    except BenchmarkLockedError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(3)
