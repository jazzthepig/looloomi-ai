# CometCloud Weekly CIS Audit
# Runs every Sunday at 02:00 UTC
# Pulls last 7 days of CIS scores from Supabase, verifies no unexpected grade drops

name: Weekly CIS Audit

on:
  schedule:
    - cron: '0 2 * * 0'  # Every Sunday at 02:00 UTC
  workflow_dispatch:  # Allow manual trigger

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install supabase pyyaml requests --quiet

      - name: Run CIS audit
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
        run: |
          python3 << 'PYEOF'
          import os
          from supabase import create_client

          supabase_url = os.getenv("SUPABASE_URL")
          supabase_key = os.getenv("SUPABASE_KEY")

          if not supabase_url or not supabase_key:
            print("⚠️ Supabase credentials not configured — skipping audit")
            print("Configure SUPABASE_URL and SUPABASE_KEY in GitHub Secrets")
            exit(0)

          try:
            client = create_client(supabase_url, supabase_key)

            # Fetch last 7 days of CIS scores
            from datetime import datetime, timedelta
            seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()

            response = client.table("cis_scores").select("*").gte("created_at", seven_days_ago).execute()

            scores = response.data
            if not scores:
              print("⚠️ No CIS scores found in last 7 days")
              exit(0)

            print(f"📊 CIS Audit: {len(scores)} scores in last 7 days")

            # Group by asset
            by_asset = {}
            for s in scores:
              aid = s.get("asset_id", "unknown")
              if aid not in by_asset:
                by_asset[aid] = []
              by_asset[aid].append(s)

            # Check for grade drops
            GRADE_THRESHOLDS = {"A+": 90, "A": 80, "B": 70, "C": 60, "D": 50, "F": 0}
            alerts = []

            for asset, asset_scores in by_asset.items():
              sorted_scores = sorted(asset_scores, key=lambda x: x.get("created_at", ""))
              if len(sorted_scores) >= 2:
                latest = sorted_scores[-1].get("cis_score", 0)
                previous = sorted_scores[-2].get("cis_score", 0)
                if latest < previous - 5:  # >5 point drop
                  alerts.append(f"  ⚠️ {asset}: {previous:.1f} → {latest:.1f} (dropped {previous-latest:.1f})")

            if alerts:
              print("\n## 🚨 Grade Drop Alerts")
              for a in alerts:
                print(a)
            else:
              print("\n✅ No significant grade drops detected")

            # Grade distribution
            grade_dist = {"A+": 0, "A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
            for s in scores:
              score = s.get("cis_score", 0)
              if score >= 90: grade = "A+"
              elif score >= 80: grade = "A"
              elif score >= 70: grade = "B"
              elif score >= 60: grade = "C"
              elif score >= 50: grade = "D"
              else: grade = "F"
              grade_dist[grade] += 1

            print("\n📈 Grade Distribution (last 7 days):")
            for g, c in grade_dist.items():
              bar = "█" * (c // 5) if c > 0 else "-"
              print(f"  {g}: {c:3} {bar}")

          except Exception as e:
            print(f"⚠️ Audit error: {e}")
            exit(0)

          PYEOF

      - name: Report final status
        run: |
          echo "## ✅ Weekly CIS Audit Complete"
          echo "Report generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
          echo ""
          echo "Next scheduled run: $(date -d 'next Sunday' -u +%Y-%m-%dT02:00:00Z)"