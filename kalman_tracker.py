# kalman_tracker.py
import numpy as np
from filterpy.kalman import KalmanFilter

class ShipKalmanFilter:
    """
    Kalman filter per ship.
    State: [lat, lon, lat_vel, lon_vel]
    Smooths noisy GPS track from pixel-to-GPS conversion.
    """

    def __init__(self, init_lat, init_lon):
        self.kf = KalmanFilter(dim_x=4, dim_z=2)

        # State transition — constant velocity model
        self.kf.F = np.array([
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ], dtype=float)

        # Measurement function — we observe lat, lon only
        self.kf.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ], dtype=float)

        # Measurement noise — how much we trust the GPS observation
        self.kf.R = np.eye(2) * 0.0001

        # Process noise — how much the ship can accelerate unexpectedly
        self.kf.Q = np.eye(4) * 0.000001

        # Initial covariance
        self.kf.P = np.eye(4) * 0.01

        # Initial state
        self.kf.x = np.array([init_lat, init_lon, 0.0, 0.0])

        self.initialized = True

    def update(self, lat, lon):
        """ Feed a new GPS observation, get smoothed position back. """
        self.kf.predict()
        self.kf.update(np.array([lat, lon]))

        smoothed_lat = float(self.kf.x[0])
        smoothed_lon = float(self.kf.x[1])
        vel_lat      = float(self.kf.x[2])
        vel_lon      = float(self.kf.x[3])

        return smoothed_lat, smoothed_lon, vel_lat, vel_lon

    def predict_only(self):
        """ Just predict without a new observation (e.g. ship occluded). """
        self.kf.predict()
        return float(self.kf.x[0]), float(self.kf.x[1])