# config.py

CONFIG = {
    "model_path":    "yolov8n.pt",
    "confidence":    0.4,
    "device":        "cuda",

    "track_history": 90,
    "reid_threshold": 0.5,
    "smooth_frames": 5,
    "predict_steps": 20,

    # Camera GPS — change these to your actual camera location
    # These are set to Singapore strait (SMD dataset location)
    "camera_lat":  1.2800,
    "camera_lon": 103.8500,

    # Map settings
    "map_path": r"data\maps\NE2_50M_SR_W\NE2_50M_SR_W.tif",  # update to your filename
    "fov_km":   2.0,    # how many km the camera sees — adjust to your footage

    "input_video":  "data/videos/input.mp4",
    "output_video": "outputs/result.mp4",
    "output_json":  "outputs/results.json",

    "classes": [
        "boat", "cargo ship", "ferry",
        "fishing vessel", "motorboat",
        "sailboat", "tanker"
    ]
}