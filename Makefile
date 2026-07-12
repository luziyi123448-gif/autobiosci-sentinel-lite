.PHONY: install test run queue seed-windows auto worker run-next status accessions clean

install:
	python -m pip install -e ".[dev]"

test:
	pytest

run:
	python -m autobiosci_sentinel.cli run --config configs/topics.yaml --db data/papers.sqlite --report reports/daily_report.md

queue:
	python -m autobiosci_sentinel.cli queue --config configs/topics.yaml --db data/papers.sqlite --report reports/daily_report.md

seed-windows:
	python -m autobiosci_sentinel.cli seed-windows --config configs/topics.yaml --db data/papers.sqlite --report reports/daily_report.md --start-date 2024-01-01 --end-date 2024-03-01 --window-days 30 --retmax 20

auto:
	python -m autobiosci_sentinel.cli auto --config configs/topics.yaml --db data/papers.sqlite --report reports/daily_report.md --max-jobs 3

worker:
	python -m autobiosci_sentinel.cli worker --db data/papers.sqlite --max-jobs 3

run-next:
	python -m autobiosci_sentinel.cli run-next --db data/papers.sqlite

status:
	python -m autobiosci_sentinel.cli status --db data/papers.sqlite

accessions:
	python -m autobiosci_sentinel.cli accessions --db data/papers.sqlite

clean:
	python -c "from pathlib import Path; [p.unlink() for p in (Path('data/papers.sqlite'), Path('reports/daily_report.md')) if p.exists()]"
