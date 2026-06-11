import asyncio
import json
import httpx
from okx_strategy22_live_pilot import OkxCredentials, OkxPrivateClient

async def main():
    creds = OkxCredentials.from_env()
    async with httpx.AsyncClient(timeout=30) as client:
        okx = OkxPrivateClient(client, creds)
        pos = await okx.positions()
        pending = await okx.request('GET', '/api/v5/trade/orders-algo-pending?ordType=move_order_stop&instType=SWAP')
        conditional = await okx.request('GET', '/api/v5/trade/orders-algo-pending?ordType=conditional&instType=SWAP')
        print(json.dumps({
            'positions': pos.get('data', []),
            'move_order_stop_pending': pending.get('data', []),
            'conditional_pending': conditional.get('data', []),
        }, ensure_ascii=False, indent=2)[:12000])

if __name__ == '__main__':
    asyncio.run(main())
