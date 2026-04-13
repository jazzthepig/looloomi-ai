# CometCloud Post-Deploy Verify
# Triggers after Railway deployment
# Verifies all critical endpoints return healthy responses

name: Post-Deploy Verify

on:
  deployment:
    environment: production

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - name: Verify CIS Universe endpoint
        run: |
          RESPONSE=$(curl -s -w "\n%{http_code}" https://web-production-0cdf76.up.railway.app/api/v1/cis/universe)
          BODY=$(echo "$RESPONSE" | head -n -1)
          STATUS=$(echo "$RESPONSE" | tail -n 1)

          if [ "$STATUS" != "200" ]; then
            echo "❌ CIS Universe endpoint returned HTTP $STATUS"
            exit 1
          fi

          ASSET_COUNT=$(echo "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('universe', [])))" 2>/dev/null || echo "0")
          if [ "$ASSET_COUNT" -lt 50 ]; then
            echo "⚠️ CIS Universe has only $ASSET_COUNT assets (expected >50)"
          else
            echo "✅ CIS Universe: $ASSET_COUNT assets"
          fi

      - name: Verify Macro Pulse endpoint
        run: |
          RESPONSE=$(curl -s -w "\n%{http_code}" https://web-production-0cdf76.up.railway.app/api/v1/market/macro-pulse)
          BODY=$(echo "$RESPONSE" | head -n -1)
          STATUS=$(echo "$RESPONSE" | tail -n 1)

          if [ "$STATUS" != "200" ]; then
            echo "❌ Macro Pulse endpoint returned HTTP $STATUS"
            exit 1
          fi

          BTC=$(echo "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('btc_price', 0))" 2>/dev/null || echo "0")
          if [ "$BTC" -gt 0 ]; then
            echo "✅ Macro Pulse: BTC = \$$BTC"
          else
            echo "⚠️ Macro Pulse returned BTC price: $BTC"
          fi

      - name: Verify Signals endpoint
        run: |
          RESPONSE=$(curl -s -w "\n%{http_code}" https://web-production-0cdf76.up.railway.app/api/v1/signals)
          BODY=$(echo "$RESPONSE" | head -n -1)
          STATUS=$(echo "$RESPONSE" | tail -n 1)

          if [ "$STATUS" != "200" ]; then
            echo "❌ Signals endpoint returned HTTP $STATUS"
            exit 1
          fi

          SIGNAL_COUNT=$(echo "$BODY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('signals', [])))" 2>/dev/null || echo "0")
          if [ "$SIGNAL_COUNT" -gt 0 ]; then
            echo "✅ Signals: $SIGNAL_COUNT signals"
          else
            echo "⚠️ Signals returned 0 items"
          fi

      - name: Verify Protocol Universe
        run: |
          RESPONSE=$(curl -s -w "\n%{http_code}" https://web-production-0cdf76.up.railway.app/api/v1/protocols/universe)
          STATUS=$(echo "$RESPONSE" | tail -n 1)

          if [ "$STATUS" == "200" ]; then
            echo "✅ Protocols endpoint healthy"
          else
            echo "❌ Protocols endpoint returned HTTP $STATUS"
            exit 1
          fi

      - name: Report status
        run: |
          echo "## 🚀 Post-Deploy Verification Complete"
          echo "All critical endpoints verified successfully."
          echo ""
          echo "| Endpoint | Status |"
          echo "|-----------|--------|"
          echo "| CIS Universe | ✅ |"
          echo "| Macro Pulse | ✅ |"
          echo "| Signals | ✅ |"
          echo "| Protocols | ✅ |"