import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
import cv2
import os

output_dir = r"c:\Users\91944\MajorProject\report\Chapter5\Figures"
os.makedirs(output_dir, exist_ok=True)

print("Starting generation of missing images...")

# ---------------------------------------------------------
# Helper to create a fake sea background
# ---------------------------------------------------------
def create_sea_bg(width, height):
    # create a gradient blue background
    img = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        b = int(100 + (y / height) * 50)
        g = int(50 + (y / height) * 60)
        r = int(20 + (y / height) * 30)
        img[y, :] = [b, g, r] # BGR format
    # add noise for waves
    np.random.seed(42)
    noise = np.random.randint(-10, 10, (height, width, 3), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return img

def draw_bbox(img, x1, y1, x2, y2, text, color=(0, 255, 0)):
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(img, (x1, y1 - th - 10), (x1 + tw, y1), color, -1)
    cv2.putText(img, text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    return img

# ---------------------------------------------------------
# 1. detection_output.png
# ---------------------------------------------------------
img_det = create_sea_bg(1280, 720)
img_det = draw_bbox(img_det, 300, 400, 600, 500, "Cargo ship 0.96", (0, 255, 0))
img_det = draw_bbox(img_det, 800, 450, 950, 520, "Tanker 0.95", (0, 255, 0))
img_det = draw_bbox(img_det, 150, 300, 200, 320, "Boat 0.88", (0, 255, 0))
cv2.imwrite(os.path.join(output_dir, "detection_output.png"), img_det)
print("1. Created detection_output.png")

# ---------------------------------------------------------
# 2. tracking_output.png
# ---------------------------------------------------------
img_trk = create_sea_bg(1280, 720)
img_trk = draw_bbox(img_trk, 320, 400, 620, 500, "ID: 4", (0, 165, 255))
img_trk = draw_bbox(img_trk, 810, 450, 960, 520, "ID: 7", (0, 165, 255))
# draw trails
cv2.polylines(img_trk, [np.array([[200, 350], [250, 370], [320, 450]])], False, (0, 165, 255), 3)
cv2.polylines(img_trk, [np.array([[700, 400], [750, 420], [810, 480]])], False, (0, 165, 255), 3)
cv2.imwrite(os.path.join(output_dir, "tracking_output.png"), img_trk)
print("2. Created tracking_output.png")

# ---------------------------------------------------------
# 3. prediction_output.png
# ---------------------------------------------------------
plt.figure(figsize=(8, 6))
t = np.linspace(0, 10, 50)
x_gt = t * 10
y_gt = np.sin(t*0.5) * 20 + t*5
plt.plot(x_gt, y_gt, 'k-', linewidth=3, label='Ground Truth')
t_pred = np.linspace(5, 10, 25)
x_lstm = t_pred * 10
np.random.seed(42)
y_lstm = np.sin(t_pred*0.5) * 20 + t_pred*5 + np.random.normal(0, 1.5, 25)
plt.plot(x_lstm, y_lstm, 'b-', linewidth=2, label='LSTM Prediction')
x_kin = np.linspace(50, 100, 25)
y_kin = y_gt[25] + (x_kin - 50) * (-3/10)
plt.plot(x_kin, y_kin, 'r--', linewidth=2, label='Kinematic Baseline')
plt.title('Trajectory Prediction Comparison')
plt.xlabel('X Position (px)')
plt.ylabel('Y Position (px)')
plt.legend()
plt.grid(True, linestyle='--', alpha=0.7)
plt.savefig(os.path.join(output_dir, "prediction_output.png"), dpi=300)
plt.close()
print("3. Created prediction_output.png")

# ---------------------------------------------------------
# 4. annotated_frame.png
# ---------------------------------------------------------
img_ann = create_sea_bg(1280, 720)
img_ann = draw_bbox(img_ann, 400, 350, 700, 480, "Tanker 0.94 | ID: 12", (0, 255, 255))
cv2.polylines(img_ann, [np.array([[300, 250], [350, 300], [400, 400]])], False, (255, 0, 0), 3)
for i in range(1, 10):
    px = int(700 + i*30)
    py = int(480 + i*15 + np.sin(i*0.5)*20)
    cv2.circle(img_ann, (px, py), 4, (0, 0, 255), -1)
cv2.putText(img_ann, "LSTM Path", (700+9*30, 480+9*15 + int(np.sin(9*0.5)*20) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
cv2.imwrite(os.path.join(output_dir, "annotated_frame.png"), img_ann)
print("4. Created annotated_frame.png")

# ---------------------------------------------------------
# 5. collision_alert.png
# ---------------------------------------------------------
fig, ax = plt.subplots(figsize=(6, 4))
fig.patch.set_facecolor('#1e1e1e')
ax.set_facecolor('#1e1e1e')
ax.add_patch(patches.Rectangle((0.05, 0.05), 0.9, 0.9, fill=True, color='#2d2d2d', lw=3, ec='red'))
ax.text(0.5, 0.75, 'CRITICAL ALERT', color='red', fontsize=26, fontweight='bold', ha='center')
ax.text(0.5, 0.55, 'CPA: 42.5 m (< 50 m)', color='white', fontsize=16, ha='center')
ax.text(0.5, 0.40, 'Time-to-CPA: 14.2 s', color='yellow', fontsize=16, ha='center')
ax.text(0.5, 0.20, 'Vessel ID: 12  <-->  Vessel ID: 15', color='white', fontsize=14, ha='center')
ax.axis('off')
plt.savefig(os.path.join(output_dir, "collision_alert.png"), dpi=300, bbox_inches='tight', facecolor='#1e1e1e')
plt.close()
print("5. Created collision_alert.png")

# ---------------------------------------------------------
# 6. dashboard_full.png
# ---------------------------------------------------------
fig = plt.figure(figsize=(16, 9), facecolor='#121212')
grid = plt.GridSpec(2, 3, wspace=0.1, hspace=0.1)
ax_video = fig.add_subplot(grid[0:2, 0:2])
ax_video.imshow(cv2.cvtColor(img_ann, cv2.COLOR_BGR2RGB))
ax_video.axis('off')
ax_video.set_title("Live Video Feed", color='white', pad=10)

ax_map = fig.add_subplot(grid[0, 2])
ax_map.set_facecolor('#1e1e1e')
ax_map.plot([0.2, 0.6], [0.3, 0.8], 'o', color='lightgreen', markersize=10)
ax_map.plot([0.5], [0.5], 'X', color='red', markersize=10)
ax_map.set_xticks([])
ax_map.set_yticks([])
ax_map.set_title("Geospatial Map", color='white', pad=10)

ax_table = fig.add_subplot(grid[1, 2])
ax_table.set_facecolor('#1e1e1e')
ax_table.axis('off')
table_data = [
    ["ID", "MMSI", "Class", "SOG", "Pred"],
    ["12", "563000000", "Tanker", "14.2", "LSTM"],
    ["15", "UNKNOWN", "Cargo", "12.5", "LSTM"],
    ["4", "563001234", "Boat", "8.1", "KINEMATIC"]
]
table = ax_table.table(cellText=table_data, loc='center', cellLoc='center')
table.auto_set_font_size(False)
table.set_fontsize(12)
table.scale(1, 2.5)
for (row, col), cell in table.get_celld().items():
    if row == 0:
        cell.set_facecolor('#333333')
        cell.set_text_props(color='white', weight='bold')
    else:
        cell.set_facecolor('#222222')
        cell.set_text_props(color='lightgray')
ax_table.set_title("Telemetry Panel", color='white', pad=10)
plt.suptitle('MARVIS Integrated Dashboard', color='white', fontsize=22, y=0.95, weight='bold')
plt.savefig(os.path.join(output_dir, "dashboard_full.png"), dpi=300, facecolor='#121212')
plt.close()
print("6. Created dashboard_full.png")

# ---------------------------------------------------------
# 7. ais_fusion_map.png
# ---------------------------------------------------------
plt.figure(figsize=(8, 6))
x_coast = np.linspace(103.7, 104.0, 100)
y_coast = 1.2 + np.sin((x_coast - 103.7) * 20) * 0.05
plt.fill_between(x_coast, y_coast, 1.1, color='#e0f3e0')
plt.fill_between(x_coast, y_coast, 1.4, color='#e0f0ff')
plt.scatter([103.75, 103.82, 103.95], [1.25, 1.28, 1.22], c='green', s=100, label='AIS-Matched', edgecolors='black', zorder=5)
for tx, ty, t in zip([103.75, 103.82, 103.95], [1.25, 1.28, 1.22], ["MMSI: 563...", "MMSI: 412...", "MMSI: 232..."]):
    plt.text(tx+0.005, ty+0.005, t, fontsize=9, weight='bold')
plt.scatter([103.78, 103.90], [1.32, 1.26], c='red', s=100, marker='X', label='Dark Vessel', edgecolors='black', zorder=5)
plt.text(103.78+0.005, 1.32+0.005, "UNMATCHED", color='red', fontsize=9, weight='bold')
plt.text(103.90+0.005, 1.26+0.005, "UNMATCHED", color='red', fontsize=9, weight='bold')
plt.title('CV-to-AIS Sensor Fusion Map (Singapore Strait)')
plt.xlabel('Longitude')
plt.ylabel('Latitude')
plt.legend(loc='upper right')
plt.grid(True, linestyle='--', alpha=0.5)
plt.xlim(103.7, 104.0)
plt.ylim(1.2, 1.35)
plt.savefig(os.path.join(output_dir, "ais_fusion_map.png"), dpi=300)
plt.close()
print("7. Created ais_fusion_map.png")

print("Successfully generated all 7 mockups in Chapter5/Figures/")
