import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from okx_strategy22_live_pilot import OkxCredentials, OkxPrivateClient

OUT = Path('data/okx_trailing_stop_0_5pct_placed.jsonl')
CALLBACK_RATIO = '0.005'  # 0.5%


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


async def main():
    creds = OkxCredentials.from_env()
    async with httpx.AsyncClient(timeout=30) as client:
        okx = OkxPrivateClient(client, creds)
        pos_data = await okx.positions()
        positions = []
        for row in pos_data.get('data', []):
            pos = abs(float(row.get('pos') or 0))
            if pos <= 0:
                continue
            inst_id = row.get('instId')
            td_mode = row.get('mgnMode') or 'isolated'
            pos_side = row.get('posSide') or 'net'
            mark_px = row.get('markPx')
            avg_px = row.get('avgPx')
            # Current pilot only opens long net positions. In net mode positive pos = long.
            side = 'sell' if float(row.get('pos') or 0) > 0 else 'buy'
            payload = {
                'instId': inst_id,
                'tdMode': td_mode,
                'side': side,
                'ordType': 'move_order_stop',
                'sz': str(row.get('pos')).lstrip('-'),
                'callbackRatio': CALLBACK_RATIO,
                'reduceOnly': 'true',
            }
            # OKX net mode usually does not require posSide; include only if not net.
            if pos_side and pos_side != 'net':
                payload['posSide'] = pos_side
            result = await okx.request('POST', '/api/v5/trade/order-algo', payload)
            algo_id = (result.get('data') or [{}])[0].get('algoId')
            record = {
                'ts': utc_now_iso(),
                'event': 'PLACE_TRAILING_STOP_0_5PCT',
                'instId': inst_id,
                'pos': row.get('pos'),
                'side': side,
                'tdMode': td_mode,
                'posSide': pos_side,
                'avgPx': avg_px,
                'markPx': mark_px,
                'callbackRatio': CALLBACK_RATIO,
                'algoId': algo_id,
                'payload': payload,
                'result': result,
            }
            positions.append(record)
            OUT.parent.mkdir(parents=True, exist_ok=True)
            with OUT.open('a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        print(json.dumps({'ok': True, 'count': len(positions), 'positions': positions}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
