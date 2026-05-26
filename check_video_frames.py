import asyncio
import websockets
import json
import sys

async def test():
    uri = 'ws://localhost:9000/ws'
    try:
        async with websockets.connect(uri) as ws:
            print('✅ Connected to WebSocket')
            for i in range(5):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    data = json.loads(msg)
                    ships_count = len(data.get('ships', []))
                    has_video = 'video_frame' in data and data['video_frame'] is not None
                    camera_available = data.get('camera_status', {}).get('available', False)
                    
                    print(f'Message {i+1}:')
                    print(f'  Type: {data.get("type")}')
                    print(f'  Ships: {ships_count}')
                    print(f'  Has video frame: {has_video}')
                    print(f'  Camera available: {camera_available}')
                    
                except asyncio.TimeoutError:
                    print(f'Timeout {i+1} - no message received')
                    break
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(test())
