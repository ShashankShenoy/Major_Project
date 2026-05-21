# stabilizer.py
import cv2
import numpy as np

class DroneStabilizer:
    def __init__(self):
        self.prev_gray = None
        self.transform = None

    def stabilize(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self.prev_gray is None:
            self.prev_gray = gray
            return frame, np.eye(2, 3, dtype=np.float32)

        # Detect feature points in previous frame
        prev_pts = cv2.goodFeaturesToTrack(
            self.prev_gray,
            maxCorners=200,
            qualityLevel=0.01,
            minDistance=30,
            blockSize=3
        )

        if prev_pts is None:
            self.prev_gray = gray
            return frame, np.eye(2, 3, dtype=np.float32)

        # Track those points into current frame
        curr_pts, status, _ = cv2.calcOpticalFlowPyrLK(
            self.prev_gray, gray, prev_pts, None
        )

        # Keep only good matches
        good_prev = prev_pts[status == 1]
        good_curr = curr_pts[status == 1]

        # Estimate camera motion (affine transform)
        transform, _ = cv2.estimateAffinePartial2D(
            good_prev, good_curr
        )

        if transform is None:
            self.prev_gray = gray
            return frame, np.eye(2, 3, dtype=np.float32)

        # Warp frame to cancel camera motion
        h, w = frame.shape[:2]
        stabilized = cv2.warpAffine(frame, transform, (w, h))

        self.prev_gray = gray
        self.transform = transform

        return stabilized, transform