import asyncio
import os
import time

import httpx

base, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
hdr = {"apikey": key, "Authorization": "Bearer " + key}
T = ("ohlcv_daily?select=symbol,trade_date,open,high,low,close,volume"
     "&source=eq.binance_hist&trade_date=gte.2024-05-16&trade_date=lte.2026-11-22"
     "&order=symbol.asc,trade_date.asc")


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as c:
        for off in (0, 50000, 100000, 180000):
            t0 = time.time()
            r = await c.get(base + "/rest/v1/" + T + "&limit=1000&offset=" + str(off), headers=hdr)
            n = len(r.json()) if r.status_code == 200 else -1
            print("offset", off, r.status_code, n, "行", round(time.time() - t0, 2), "s")
        t0 = time.time()
        await asyncio.gather(*[c.get(base + "/rest/v1/" + T + "&limit=1000&offset=" + str(o), headers=hdr)
                               for o in range(0, 8000, 1000)])
        print("并发 8 页(0-7000):", round(time.time() - t0, 2), "s")
        t0 = time.time()
        await asyncio.gather(*[c.get(base + "/rest/v1/" + T + "&limit=1000&offset=" + str(o), headers=hdr)
                               for o in range(170000, 178000, 1000)])
        print("并发 8 页(170000+):", round(time.time() - t0, 2), "s")
        t0 = time.time()
        r = await c.get(base + "/rest/v1/ohlcv_daily?select=symbol&source=eq.binance_hist"
                        "&trade_date=gte.2026-11-20&order=symbol.asc&limit=1000", headers=hdr)
        print("近 3 天符号:", len(r.json()), "行", round(time.time() - t0, 2), "s")


asyncio.run(main())
