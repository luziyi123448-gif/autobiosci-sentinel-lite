import csv

import pytest

from autobiosci_sentinel.database import upsert_papers
from autobiosci_sentinel.prototype import init_campaign, load_state, release_campaign, tick_campaign


def test_prototype_campaign_is_bounded_idempotent_and_author_gated(tmp_path):
    db = tmp_path / "papers.sqlite"
    root = tmp_path / "prototype"
    upsert_papers(
        db,
        [{"pmid": "1", "doi": "10.1/example", "title": "Example", "abstract": "Abstract", "score": 1}],
    )

    init_campaign(root, db, "Ada Author", "Prototype")
    first = tick_campaign(root, db)
    second = tick_campaign(root, db)

    assert first["state"] == "RELEASE_HOLD"
    assert first["changed"] is True
    assert second["changed"] is False
    assert {path.name for path in root.iterdir()} == {
        "run_state.json",
        "snapshot.jsonl",
        "evidence.csv",
        "draft.md",
        "review.jsonl",
    }
    with (root / "evidence.csv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle))[0]["support_status"] == "unassessed"
    with pytest.raises(ValueError, match="responsibility"):
        release_campaign(root, "Ada Author", False)

    draft = (root / "draft.md").read_text(encoding="utf-8")
    (root / "draft.md").write_text(draft + "tampered\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="artifacts changed"):
        release_campaign(root, "Ada Author", True)
    (root / "draft.md").write_text(draft, encoding="utf-8", newline="\n")

    released = release_campaign(root, "Ada Author", True)
    assert released["state"] == "RELEASED"
    assert released["submission_eligible"] is False
    assert released["release"]["class"] == "PUBLIC_MACHINE_NOTE"
    assert load_state(root)["release"]["author"] == "Ada Author"
