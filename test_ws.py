import asyncio
import websockets
import json

async def test():
    uri = 'ws://localhost:9000/ws'
    try:
        async with websockets.connect(uri) as ws:
            print('Connected to WebSocket')
            for i in range(10):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    data = json.loads(msg)
                    ships_count = len(data.get('ships', []))
                    print(f'Received message {i+1}: type={data.get("type")}, ships={ships_count}')
                except asyncio.TimeoutError:
                    print(f'Timeout {i+1} - no message received')
                    break
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(test())
