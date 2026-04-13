# CometCloud Compliance PR Check
# Triggers on every pull request
# Scans diff for prohibited buy/sell language (BUY, SELL, ACCUMULATE, AVOID, REDUCE, STRONG BUY)

name: Compliance PR Check

on:
  pull_request:

jobs:
  compliance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Run compliance scan
        env:
          COMPLIANCE_BLOCK: '1'
        run: |
          python3 ~/.claude/hooks/git_commit_check.py --staged --block
        shell: bash

      - name: Report violations
        if: failure()
        run: |
          echo "## ⚠️ Compliance Violations Detected"
          echo "The following prohibited terms were found in the PR:"
          echo '```'
          git diff --staged --name-only
          echo '```'
          echo "Please remove or replace prohibited buy/sell language before merging."
          echo ""
          echo "Allowed signal vocabulary (HK SFC compliance):"
          echo "  STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT"
          echo ""
          echo "Prohibited terms: BUY, SELL, STRONG BUY, ACCUMULATE, AVOID, REDUCE"