"""T-107 / M-584:从 CoinGecko Pro 拉 24 名 + BTC 的 prices + market_caps 全历史。

数据来自 CG Pro /coins/{id}/market_chart?vs_currency=usd&days=max&interval=daily。
输出到 /Volumes/CometCloudAI/cometcloud-local/research/t107_cg_cache/ 每币一文件;
缺失 / 失败的币记入 _missing.json。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

env = dotenv_values('/Volumes/CometCloudAI/cometcloud-local/.env')
for k, v in env.items():
    os.environ[k] = v

KEY = os.environ['CG_PRO_API_KEY']

PANEL = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK",
         "DOT", "LTC", "TRX", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI",
         "UNI", "AAVE", "INJ", "FIL", "ETC", "BCH"]

ID_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "XRP": "ripple", "DOGE": "dogecoin",
    "ADA": "cardano", "AVAX": "avalanche-2", "LINK": "chainlink",
    "DOT": "polkadot", "LTC": "litecoin", "TRX": "tron",
    "ATOM": "cosmos", "NEAR": "near", "APT": "aptos",
    "ARB": "arbitrum", "OP": "optimism", "SUI": "sui",
    "UNI": "uniswap", "AAVE": "aave", "INJ": "injective-protocol",
    "FIL": "filecoin", "ETC": "ethereum-classic", "BCH": "bitcoin-cash",
}

OUT = Path('/Volumes/CometCloudAI/cometcloud-local/research/t107_cg_cache')
OUT.mkdir(parents=True, exist_ok=True)


def fetch_one(symbol: str, cg_id: str) -> dict | None:
    url = (f'https://pro-api.coingecko.com/api/v3/coins/{cg_id}/market_chart'
           f'?vs_currency=usd&days=max&interval=daily&x_cg_pro_api_key={KEY}')
    try:
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url), timeout=60).read())
    except urllib.error.HTTPError as e:
        return {'symbol': symbol, 'cg_id': cg_id, 'error': f'{e.code}', 'body': e.read()[:200].decode(errors='replace')}
    except Exception as e:
        return {'symbol': symbol, 'cg_id': cg_id, 'error': repr(e)[:200]}
    if 'prices' not in r or 'market_caps' not in r:
        return {'symbol': symbol, 'cg_id': cg_id, 'error': 'no prices/market_caps'}
    return {
        'symbol': symbol,
        'cg_id': cg_id,
        'prices': r['prices'],
        'market_caps': r['market_caps'],
        'total_volumes': r.get('total_volumes', []),
    }


def main() -> None:
    missing = []
    for s in PANEL:
        out = OUT / f'{s}.json'
        if out.exists() and out.stat().st_size > 1000:
            data = json.loads(out.read_text())
            if 'prices' in data and len(data['prices']) > 1000:
                print(f'[skip] {s} cached ({len(data["prices"])} pts)')
                continue
        cg_id = ID_MAP.get(s)
        if not cg_id:
            missing.append({'symbol': s, 'error': 'no id mapping'})
            continue
        t0 = time.time()
        d = fetch_one(s, cg_id)
        elapsed = time.time() - t0
        if d is None or 'prices' not in d:
            missing.append(d or {'symbol': s, 'error': 'None'})
            print(f'[fail] {s} {elapsed:.1f}s: {d.get("error","None") if d else "None"}')
            continue
        out.write_text(json.dumps(d, ensure_ascii=False))
        first_d = d['prices'][0][0]
        last_d = d['prices'][-1][0]
        print(f'[ok] {s} {len(d["prices"])} pts  '
              f'{time.strftime("%Y-%m-%d", time.gmtime(first_d/1000))} → '
              f'{time.strftime("%Y-%m-%d", time.gmtime(last_d/1000))}  {elapsed:.1f}s')
        time.sleep(2.0)  # 礼貌 sleep,免 rate limit
    (OUT / '_missing.json').write_text(json.dumps(missing, ensure_ascii=False, indent=1))
    print(f'[done] missing={len(missing)}/{len(PANEL)}')


if __name__ == '__main__':
    main()