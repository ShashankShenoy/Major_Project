# predictor.py
import numpy as np

def predict_path(history, steps=20):
    """
    Simple kinematic prediction using linear regression on recent positions.
    No ML needed for short-term prediction — works well for ships
    because they move smoothly and change direction slowly.
    
    Args:
        history: deque of (cx, cy, frame_num) tuples
        steps:   how many future positions to predict
    
    Returns:
        list of (x, y) predicted positions
    """
    if len(history) < 5:
        return []

    recent = list(history)[-10:]
    xs = [p[0] for p in recent]
    ys = [p[1] for p in recent]
    frames = list(range(len(recent)))

    # Fit linear trend to x and y separately
    vx = np.polyfit(frames, xs, 1)[0]  # pixels/frame in x direction
    vy = np.polyfit(frames, ys, 1)[0]  # pixels/frame in y direction

    # Project forward from last known position
    last_x, last_y = recent[-1][0], recent[-1][1]
    predicted = []
    for i in range(1, steps + 1):
        px = int(last_x + vx * i)
        py = int(last_y + vy * i)
        predicted.append((px, py))

    return predicted


def predict_path_curved(history, steps=20):
    """
    Slightly smarter prediction using quadratic fit —
    handles gradual turns better than linear.
    Use this if ships appear to be curving in your footage.
    """
    if len(history) < 8:
        return predict_path(history, steps)

    recent = list(history)[-15:]
    xs = [p[0] for p in recent]
    ys = [p[1] for p in recent]
    frames = list(range(len(recent)))

    # Quadratic fit captures gentle curves
    px_coeffs = np.polyfit(frames, xs, 2)
    py_coeffs = np.polyfit(frames, ys, 2)

    predicted = []
    n = len(recent)
    for i in range(1, steps + 1):
        t = n + i
        px = int(np.polyval(px_coeffs, t))
        py = int(np.polyval(py_coeffs, t))
        predicted.append((px, py))

    return predicted