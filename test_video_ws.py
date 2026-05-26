import asyncio
import websockets
import json

async def test():
    uri = 'ws://localhost:9000/ws'
    try:
        async with websockets.connect(uri) as ws:
            print('Connected to WebSocket')
            for i in range(5):
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(msg)
                ships_count = len(data.get('ships', []))
                has_video = bool(data.get('video_frame'))
                camera_available = data.get('camera_status', {}).get('available')
                print(f'Message {i+1}: ships={ships_count}, video_frame={has_video}, camera_available={camera_available}')
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(test())
