This repo implements an evidence-driven remediation engine for the lab.

Setup:
`python -m venv .venv`
`.\.venv\Scripts\Activate.ps1`
`python -m pip install PyYAML drain3`

Run one incident:
`python engine.py decide --incident eval/E01.json --history incidents_history.json --actions actions.yaml`

Run grade:
`python grade.py --audit audit.jsonl --expected eval/expected.json`

Expected result:
`Correct: 8/8`
`Forbidden: 0/8`
`Missing: 0/8`
