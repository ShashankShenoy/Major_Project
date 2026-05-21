# direction.py
import numpy as np

def compute_direction(history):
    pts = list(history)

    if len(pts) < 3:
        return 0.0, 0.0

    # Use last 15 points, weighted toward recent
    recent = pts[-15:]

    # Smooth positions first using moving average
    # This removes jitter from drone wobble
    smoothed = []
    window = 3
    for i in range(len(recent)):
        start = max(0, i - window)
        chunk = recent[start:i+1]
        avg_x = np.mean([p[0] for p in chunk])
        avg_y = np.mean([p[1] for p in chunk])
        smoothed.append((avg_x, avg_y))

    # Overall displacement from smoothed start to end
    dx = smoothed[-1][0] - smoothed[0][0]
    dy = smoothed[-1][1] - smoothed[0][1]

    speed = np.sqrt(dx**2 + dy**2) / len(smoothed)

    if speed < 0.3:
        return 0.0, 0.0

    heading = np.degrees(np.arctan2(dy, dx)) % 360
    return round(heading, 1), round(speed, 2)


def heading_to_cardinal(heading):
    if heading == 0.0:
        return "stationary"
    dirs = ['E', 'NE', 'N', 'NW', 'W', 'SW', 'S', 'SE']
    return dirs[round(heading / 45) % 8]