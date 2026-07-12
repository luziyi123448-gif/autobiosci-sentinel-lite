from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from autobiosci_sentinel.database import init_db, top_papers


ARTIFACTS = ("snapshot.jsonl", "evidence.csv", "draft.md", "review.jsonl")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def load_state(root: str | Path) -> dict:
    return json.loads((Path(root) / "run_state.json").read_text(encoding="utf-8"))


def _append_event(root: Path, event: dict) -> None:
    path = root / "review.jsonl"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_write(path, existing + json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _artifact_hashes(root: Path) -> dict[str, str]:
    return {name: sha256_bytes((root / name).read_bytes()) for name in ARTIFACTS}


def _write_state(root: Path, state: dict) -> None:
    state["updated_at"] = utc_now()
    atomic_write(root / "run_state.json", json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def init_campaign(root: str | Path, db: str | Path, author: str, title: str) -> dict:
    root_path = Path(root)
    state_path = root_path / "run_state.json"
    author = author.strip()
    title = title.strip()
    if not author or not title:
        raise ValueError("author and title are required")
    if state_path.exists():
        raise FileExistsError(f"campaign already exists: {state_path}")

    init_db(db)
    root_path.mkdir(parents=True, exist_ok=True)
    atomic_write(root_path / "snapshot.jsonl", "")
    atomic_write(
        root_path / "evidence.csv",
        "evidence_id,pmid,doi,title,evidence_level,support_status,requires_author_review\n",
    )
    atomic_write(
        root_path / "draft.md",
        f"# {title}\n\nStatus: frozen; no evidence snapshot has been generated.\n",
    )
    _append_event(root_path, {"at": utc_now(), "event": "campaign_initialized", "author": author})
    state = {
        "schema_version": "ai247-prototype.v1",
        "campaign_id": root_path.name,
        "title": title,
        "author": author,
        "source_db": str(db),
        "state": "FROZEN",
        "record_count": 0,
        "source_snapshot_sha256": "",
        "artifacts": _artifact_hashes(root_path),
        "submission_eligible": False,
        "release": None,
        "created_at": utc_now(),
    }
    _write_state(root_path, state)
    return state


def tick_campaign(root: str | Path, db: str | Path, limit: int = 20) -> dict:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    root_path = Path(root)
    state = load_state(root_path)
    if state["state"] == "RELEASED":
        raise ValueError("released campaigns are immutable")

    papers = top_papers(db, limit=limit)
    snapshot_rows = [
        {
            "pmid": str(paper.get("pmid") or ""),
            "doi": str(paper.get("doi") or ""),
            "title": str(paper.get("title") or ""),
            "abstract": str(paper.get("abstract") or ""),
            "journal": str(paper.get("journal") or ""),
            "pub_date": str(paper.get("pub_date") or ""),
            "topic": str(paper.get("topic") or ""),
        }
        for paper in papers
    ]
    snapshot = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in snapshot_rows)
    snapshot_hash = sha256_bytes(snapshot.encode("utf-8"))
    if snapshot_hash == state.get("source_snapshot_sha256"):
        return {**state, "changed": False}

    evidence_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        evidence_buffer,
        fieldnames=(
            "evidence_id",
            "pmid",
            "doi",
            "title",
            "evidence_level",
            "support_status",
            "requires_author_review",
        ),
        lineterminator="\n",
    )
    writer.writeheader()
    for index, row in enumerate(snapshot_rows, start=1):
        writer.writerow(
            {
                "evidence_id": f"E{index:04d}",
                "pmid": row["pmid"],
                "doi": row["doi"],
                "title": row["title"],
                "evidence_level": "abstract_only" if row["abstract"] else "metadata_only",
                "support_status": "unassessed",
                "requires_author_review": "yes",
            }
        )

    records = "\n".join(
        f"- PMID {row['pmid'] or 'unknown'}: {row['title'] or '[untitled]'}"
        + (f" (DOI: {row['doi']})" if row["doi"] else "")
        for row in snapshot_rows
    )
    draft = (
        f"# {state['title']}\n\n"
        "Status: AI-assisted metadata evidence brief; not domain-reviewed, not a systematic review, "
        "not clinical guidance, and not submission-ready.\n\n"
        f"Responsible author: {state['author']} (release not yet signed).\n\n"
        f"Records in frozen snapshot: {len(snapshot_rows)}.\n\n"
        "## Records\n\n"
        f"{records or '- No records.'}\n"
    )

    atomic_write(root_path / "snapshot.jsonl", snapshot)
    atomic_write(root_path / "evidence.csv", evidence_buffer.getvalue())
    atomic_write(root_path / "draft.md", draft)
    _append_event(
        root_path,
        {"at": utc_now(), "event": "snapshot_generated", "records": len(snapshot_rows), "sha256": snapshot_hash},
    )
    state.update(
        {
            "state": "RELEASE_HOLD",
            "record_count": len(snapshot_rows),
            "source_db": str(db),
            "source_snapshot_sha256": snapshot_hash,
            "submission_eligible": False,
            "artifacts": _artifact_hashes(root_path),
        }
    )
    _write_state(root_path, state)
    return {**state, "changed": True}


def release_campaign(root: str | Path, author: str, accept_responsibility: bool) -> dict:
    root_path = Path(root)
    state = load_state(root_path)
    if state["state"] != "RELEASE_HOLD":
        raise ValueError("campaign must be in RELEASE_HOLD")
    if author.strip() != state["author"]:
        raise ValueError("author does not match the campaign")
    if not accept_responsibility:
        raise ValueError("explicit author responsibility acceptance is required")
    current_hashes = _artifact_hashes(root_path)
    if current_hashes != state["artifacts"]:
        raise ValueError("campaign artifacts changed after the last tick")

    statement = (
        "I accept responsibility for releasing this clearly labeled AI-assisted metadata evidence brief. "
        "I understand that scientific validity remains unassessed."
    )
    _append_event(root_path, {"at": utc_now(), "event": "author_release", "author": author, "statement": statement})
    state.update(
        {
            "state": "RELEASED",
            "artifacts": _artifact_hashes(root_path),
            "release": {"at": utc_now(), "author": author, "class": "PUBLIC_MACHINE_NOTE", "statement": statement},
        }
    )
    _write_state(root_path, state)
    return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m autobiosci_sentinel.prototype")
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init")
    init_parser.add_argument("--root", default="prototype/ai247")
    init_parser.add_argument("--db", default="data/papers.sqlite")
    init_parser.add_argument("--author", required=True)
    init_parser.add_argument("--title", default="AI 24/7 Academic Prototype")

    tick_parser = commands.add_parser("tick")
    tick_parser.add_argument("--root", default="prototype/ai247")
    tick_parser.add_argument("--db", default="data/papers.sqlite")
    tick_parser.add_argument("--limit", type=int, default=20)

    status_parser = commands.add_parser("status")
    status_parser.add_argument("--root", default="prototype/ai247")

    release_parser = commands.add_parser("release")
    release_parser.add_argument("--root", default="prototype/ai247")
    release_parser.add_argument("--author", required=True)
    release_parser.add_argument("--accept-responsibility", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        state = init_campaign(args.root, args.db, args.author, args.title)
    elif args.command == "tick":
        state = tick_campaign(args.root, args.db, args.limit)
    elif args.command == "release":
        state = release_campaign(args.root, args.author, args.accept_responsibility)
    else:
        state = load_state(args.root)
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
