# map_view.py
import base64
import json
import cv2
import numpy as np
from collections import defaultdict, deque
import time
from geo_mapper import GeoMapper
from kalman_tracker import ShipKalmanFilter
from lstm_predictor import LSTMPredictor
from config import CONFIG
from visualization.ws_stream import WebSocketServer

BG_DARK      = (12,  14,  18)
BG_PANEL     = (18,  22,  28)
BG_CARD      = (22,  28,  36)
ACCENT       = (0,  200, 150)
ACCENT_DIM   = (0,   90,  68)
GRID_COLOR   = (26,  34,  44)
BORDER       = (40,  52,  64)
TEXT_HI      = (215, 225, 232)
TEXT_MID     = ( 90, 112, 128)
TEXT_LO      = ( 46,  60,  72)

TRACK_COLORS = [
    (  0, 220, 170),
    (255, 140,   0),
    (160,  80, 255),
    ( 80, 200, 255),
    (255,  70, 120),
    (180, 255,  60),
    (255, 210,  40),
    ( 40, 160, 255),
    (255, 120, 180),
    ( 60, 220, 120),
]

def ship_color(sid):
    return TRACK_COLORS[sid % len(TRACK_COLORS)]

def fill_rect(f, x1, y1, x2, y2, col, a=0.3):
    ov = f.copy()
    cv2.rectangle(ov,(x1,y1),(x2,y2),col,-1)
    cv2.addWeighted(ov,a,f,1-a,0,f)

def put(f, txt, x, y, col=TEXT_HI, sc=0.40, th=1):
    cv2.putText(f, txt,(x,y),
                cv2.FONT_HERSHEY_SIMPLEX,sc,col,th,cv2.LINE_AA)

def measure(txt, sc=0.40, th=1):
    (w,h),_ = cv2.getTextSize(
        txt,cv2.FONT_HERSHEY_SIMPLEX,sc,th)
    return w,h


class MapView:
    def __init__(self, camera_lat, camera_lon, map_path,
                 fov_km=5.0,
                 window_name="Ship Detection & Path Prediction System",
                 ws_enabled=False,
                 ws_host="127.0.0.1",
                 ws_port=8765):

        self.wname      = window_name
        self.t0         = time.time()
        self.frame_n    = 0
        self.fps        = 0.0
        self._fps_t     = time.time()
        self._fps_f     = 0

        self.mapper = GeoMapper(
            camera_lat, camera_lon, map_path, fov_km)
        print(f"Region: {self.mapper.get_region_name()}")

        self.kfs      = {}
        try:
            import torch
            lstm_device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            lstm_device = "cpu"
        self.lstm     = LSTMPredictor(
            predict_steps=CONFIG["predict_steps"],
            seq_len=30,
            device=lstm_device
        )
        self.trails   = defaultdict(lambda: deque(maxlen=90))
        self.ship_log = {}

        self.ws_enabled = ws_enabled
        self.ws_server = None
        if self.ws_enabled:
            try:
                self.ws_server = WebSocketServer(ws_host, ws_port)
                self.ws_server.start()
                print(f"Live WebSocket server started at ws://{ws_host}:{ws_port}")
            except Exception as exc:
                print(f"Warning: failed to start WebSocket server: {exc}")
                self.ws_enabled = False

        # Canvas layout
        self.W  = 1560
        self.H  = 860
        self.VX = 10;  self.VY = 54
        self.VW = 748; self.VH = 574
        self.MX = 768; self.MY = 54
        self.MW = 782; self.MH = 574
        self.LY = 638

        # Zoom / pan
        self.zoom  = 1.0
        self.zmin  = 1.0
        self.zmax  = 12.0
        self.zstep = 0.15
        self.px    = 0
        self.py    = 0
        self.drag  = False
        self.ds    = (0,0)
        self.ps    = (0,0)

        cv2.namedWindow(self.wname, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.wname, self.W, self.H)
        cv2.setMouseCallback(self.wname, self._mouse)

    # ─── mouse ────────────────────────────────────────────────────────────────
    def _mouse(self, ev, x, y, flags, _):
        in_map = (self.MX <= x <= self.MX+self.MW and
                  self.MY <= y <= self.MY+self.MH)

        if ev == cv2.EVENT_MOUSEWHEEL and in_map:
            old = self.zoom
            self.zoom = float(np.clip(
                self.zoom + (self.zstep if flags>0 else -self.zstep),
                self.zmin, self.zmax))
            r = self.zoom/old
            lx,ly = x-self.MX, y-self.MY
            self.px = int(lx - r*(lx-self.px))
            self.py = int(ly - r*(ly-self.py))
            self._clamp()

        elif ev == cv2.EVENT_LBUTTONDOWN and in_map:
            self.drag = True
            self.ds   = (x,y)
            self.ps   = (self.px,self.py)

        elif ev == cv2.EVENT_MOUSEMOVE and self.drag:
            self.px = self.ps[0]+(x-self.ds[0])
            self.py = self.ps[1]+(y-self.ds[1])
            self._clamp()

        elif ev in (cv2.EVENT_LBUTTONUP,cv2.EVENT_MBUTTONUP):
            self.drag = False

    def _clamp(self):
        zw = int(self.MW*self.zoom)
        zh = int(self.MH*self.zoom)
        self.px = int(np.clip(self.px, self.MW-zw, 0))
        self.py = int(np.clip(self.py, self.MH-zh, 0))

    # ─── update ───────────────────────────────────────────────────────────────
    def update(self, ships, video_frame, frame_num):
        self.frame_n  = frame_num
        self._fps_f  += 1
        now = time.time()
        if now - self._fps_t >= 1.0:
            self.fps    = self._fps_f/(now-self._fps_t)
            self._fps_f = 0
            self._fps_t = now

        fh, fw = video_frame.shape[:2]

        processed = []
        for ship in ships:
            sid   = ship["id"]
            cx,cy = ship["center"]
            col   = ship_color(sid)
            lat,lon = self.mapper.pixel_to_gps(cx,cy,fw,fh)

            if sid not in self.kfs:
                self.kfs[sid] = ShipKalmanFilter(lat,lon)

            sl,slo,vl,vlo = self.kfs[sid].update(lat,lon)
            self.lstm.update(sid,sl,slo,vl,vlo)

            raw   = self.lstm.predict(sid)
            clean = []
            for pl,plo in raw:
                if self.mapper.is_on_land(pl,plo):
                    pl,plo = self.mapper.snap_to_water(pl,plo)
                clean.append((pl,plo))

            self.trails[sid].append((sl,slo))
            e = dict(ship)
            e.update({"gps_lat":sl,"gps_lon":slo,
                      "pred_path":clean,"color":col})
            self.ship_log[sid] = e
            processed.append(e)

        canvas = np.full((self.H,self.W,3), BG_DARK, dtype=np.uint8)
        self._header(canvas)
        self._video_panel(canvas, video_frame)
        self._map_panel(canvas, processed, fw, fh)
        self._log_panel(canvas, processed)
        self._scanlines(canvas)
        cv2.imshow(self.wname, canvas)
        self._publish_stream(canvas)
        return processed

    # ─── header ───────────────────────────────────────────────────────────────
    def _header(self, c):
        H = 50
        cv2.rectangle(c,(0,0),(self.W,H), BG_PANEL,-1)
        cv2.rectangle(c,(0,H-1),(self.W,H), BORDER,-1)
        cv2.rectangle(c,(0,0),(4,H), ACCENT,-1)

        # Title — single line, compact
        put(c,"SHIP DETECTION & PATH PREDICTION",
            14, 31, ACCENT, sc=0.52, th=1)

        # Thin vertical divider
        div_x = 310
        cv2.line(c,(div_x,8),(div_x,42), BORDER,1)

        region = self.mapper.get_region_name().upper()
        put(c, region, div_x+12, 30, TEXT_MID, sc=0.38)

        # Right stats — build right-to-left, well spaced
        elapsed  = int(time.time()-self.t0)
        mm,ss    = elapsed//60, elapsed%60

        # LIVE badge rightmost
        live = "  LIVE  "
        lw,lh = measure(live, sc=0.38)
        bx = self.W - lw - 16
        cv2.rectangle(c,(bx-2,10),(bx+lw+2,40),(0,45,28),-1)
        cv2.rectangle(c,(bx-2,10),(bx+lw+2,40),ACCENT_DIM,1)
        put(c, live, bx, 30, ACCENT, sc=0.38)

        # Stats left of LIVE badge
        stats = [
            f"CAM {self.mapper.camera_lat:.3f}N {self.mapper.camera_lon:.3f}E",
            f"TIME {mm:02d}:{ss:02d}",
            f"FRAME {self.frame_n:05d}",
            f"FPS {self.fps:.1f}",
        ]
        rx = bx - 20
        for s in stats:
            w,_ = measure(s, sc=0.36)
            put(c, s, rx-w, 30, TEXT_MID, sc=0.36)
            rx -= w + 22

    # ─── video panel ──────────────────────────────────────────────────────────
    def _video_panel(self, canvas, frame):
        x,y,w,h = self.VX,self.VY,self.VW,self.VH
        resized  = cv2.resize(frame,(w,h),interpolation=cv2.INTER_AREA)
        canvas[y:y+h,x:x+w] = resized
        self._brackets(canvas,x,y,w,h)
        self._tab(canvas,x,y,"CAMERA FEED")

        # Vessel count badge
        n     = len(self.ship_log)
        badge = f"  {n} VESSEL{'S' if n!=1 else ''}  "
        bw,bh = measure(badge,sc=0.37)
        bx = x+w-bw-14
        by = y+h-8
        cv2.rectangle(canvas,(bx-3,by-bh-5),(bx+bw+3,by+4),(0,32,20),-1)
        cv2.rectangle(canvas,(bx-3,by-bh-5),(bx+bw+3,by+4),ACCENT_DIM,1)
        put(canvas,badge,bx,by,ACCENT,sc=0.37)

    # ─── map panel ────────────────────────────────────────────────────────────
    def _map_panel(self, canvas, ships, fw, fh):
        x,y,w,h = self.MX,self.MY,self.MW,self.MH

        # Base map
        base = self.mapper.local_map.copy()
        base = cv2.resize(base,(w,h),interpolation=cv2.INTER_AREA)
        base = cv2.addWeighted(base,0.55,
               np.full_like(base,BG_DARK),0.45,0)

        # Grid
        for gx in range(0,w,70):
            cv2.line(base,(gx,0),(gx,h),GRID_COLOR,1)
        for gy in range(0,h,70):
            cv2.line(base,(0,gy),(w,gy),GRID_COLOR,1)

        # Trails + predicted paths drawn on base (scale with zoom)
        for ship in ships:
            sid = ship["id"]
            col = ship["color"]
            sl  = ship["gps_lat"]
            slo = ship["gps_lon"]
            mx,my = self._g2p(sl,slo,w,h)
            self._draw_trail(base,sid,col,w,h)
            self._draw_pred(base,mx,my,ship["pred_path"],col,w,h)

        # Apply zoom/pan
        zoomed = self._zoom(base,w,h)

        # Ship markers drawn AFTER zoom (pixel-fixed size)
        for ship in ships:
            sid = ship["id"]
            col = ship["color"]
            bx,by = self._g2p(ship["gps_lat"],ship["gps_lon"],w,h)
            sx,sy = self._zt(bx,by,w,h)
            if 0<=sx<w and 0<=sy<h:
                self._marker(zoomed,sid,sx,sy,ship,col,w,h)

        canvas[y:y+h, x:x+w] = zoomed
        self._brackets(canvas,x,y,w,h)
        self._tab(canvas,x,y,"PREDICTED PATHS")

        # Zoom badge bottom right inside panel
        zt   = f"ZOOM {self.zoom:.1f}x"
        zw,_ = measure(zt,sc=0.33)
        put(canvas,zt,x+w-zw-8,y+h-8,TEXT_LO,sc=0.33)

    def _g2p(self,lat,lon,pw,ph):
        mn_la,mx_la,mn_lo,mx_lo = self.mapper.crop_bounds
        nx = (lon-mn_lo)/(mx_lo-mn_lo)
        ny = (mx_la-lat)/(mx_la-mn_la)
        return int(nx*pw), int(ny*ph)

    def _zt(self,bx,by,w,h):
        """ Base coords → zoomed screen coords """
        zw = int(w*self.zoom)
        zh = int(h*self.zoom)
        ox = max(0, min(-self.px, zw-w))
        oy = max(0, min(-self.py, zh-h))
        sx = int(bx*self.zoom) - ox
        sy = int(by*self.zoom) - oy
        return sx,sy

    def _zoom(self,img,w,h):
        if self.zoom<=1.0:
            return img
        zw = int(w*self.zoom)
        zh = int(h*self.zoom)
        z  = cv2.resize(img,(zw,zh),interpolation=cv2.INTER_LANCZOS4)
        ox = max(0,min(-self.px,zw-w))
        oy = max(0,min(-self.py,zh-h))
        crop = z[oy:oy+h, ox:ox+w]
        if crop.shape[:2]!=(h,w):
            pad = np.zeros((h,w,3),dtype=np.uint8)
            pad[:crop.shape[0],:crop.shape[1]] = \
                crop[:crop.shape[0],:crop.shape[1]]
            return pad
        return crop

    def _draw_trail(self,img,sid,color,w,h):
        trail = list(self.trails[sid])
        if len(trail)<2: return
        pts = [self._g2p(t[0],t[1],w,h) for t in trail]
        for i in range(1,len(pts)):
            p1,p2 = pts[i-1],pts[i]
            if not(0<=p1[0]<w and 0<=p1[1]<h and
                   0<=p2[0]<w and 0<=p2[1]<h): continue
            a    = 0.15+0.85*(i/len(pts))
            fade = tuple(int(c*a) for c in color)
            cv2.line(img,p1,p2,fade,max(1,int(2*a)),cv2.LINE_AA)

    def _draw_pred(self,img,mx,my,pred,color,w,h):
        if not pred: return
        prev = (mx,my)
        for i,(pl,plo) in enumerate(pred):
            px,py = self._g2p(pl,plo,w,h)
            if not(0<=px<w and 0<=py<h): continue
            a    = 1-(i/len(pred))*0.75
            fade = tuple(int(c*a) for c in color)
            r    = max(2,int(4*a))
            if i%2==0:
                cv2.line(img,prev,(px,py),fade,1,cv2.LINE_AA)
            cv2.circle(img,(px,py),r,fade,-1,cv2.LINE_AA)
            cv2.circle(img,(px,py),r,(200,210,218),1,cv2.LINE_AA)
            prev = (px,py)
        if len(pred)>=2:
            a1 = self._g2p(*pred[-2],w,h)
            a2 = self._g2p(*pred[-1],w,h)
            if(0<=a1[0]<w and 0<=a1[1]<h and
               0<=a2[0]<w and 0<=a2[1]<h):
                cv2.arrowedLine(img,a1,a2,color,2,
                                cv2.LINE_AA,tipLength=0.5)

    def _marker(self,img,sid,mx,my,ship,color,w,h):
        # Clean crosshair-style marker — no glow, no thick ring
        r1,r2 = 6,9

        # Outer circle — thin
        cv2.circle(img,(mx,my),r2,color,1,cv2.LINE_AA)
        # Inner circle
        cv2.circle(img,(mx,my),r1,color,1,cv2.LINE_AA)

        # Cross ticks at N/S/E/W
        tick = 4
        cv2.line(img,(mx,my-r2-1),(mx,my-r2-tick),color,1,cv2.LINE_AA)
        cv2.line(img,(mx,my+r2+1),(mx,my+r2+tick),color,1,cv2.LINE_AA)
        cv2.line(img,(mx-r2-1,my),(mx-r2-tick,my),color,1,cv2.LINE_AA)
        cv2.line(img,(mx+r2+1,my),(mx+r2+tick,my),color,1,cv2.LINE_AA)

        # Center dot — 2px
        cv2.circle(img,(mx,my),2,color,-1,cv2.LINE_AA)

        # Heading line from outer ring
        hdg = ship.get("heading",0)
        ex  = int(mx+20*np.cos(np.radians(hdg)))
        ey  = int(my+20*np.sin(np.radians(hdg)))
        if 0<=ex<w and 0<=ey<h:
            cv2.line(img,(mx,my),(ex,ey),color,1,cv2.LINE_AA)

        # ID label — right of marker, dark bg
        id_txt = str(sid)
        tw,th  = measure(id_txt,sc=0.36)
        lx,ly  = mx+r2+4, my+th//2
        cv2.rectangle(img,(lx-1,ly-th-3),(lx+tw+4,ly+2),
                      (10,13,17),-1)
        cv2.line(img,(lx-1,ly-th-3),(lx-1,ly+2),color,1)
        put(img,id_txt,lx,ly,color,sc=0.36)

    # ─── log panel ────────────────────────────────────────────────────────────
    def _log_panel(self,canvas,ships):
        x1 = self.VX
        x2 = self.MX+self.MW
        y  = self.LY
        h  = self.H-y-4

        cv2.rectangle(canvas,(x1,y),(x2,y+h),BG_PANEL,-1)
        cv2.rectangle(canvas,(x1,y),(x2,y+h),BORDER,1)
        cv2.rectangle(canvas,(x1,y),(x1+3,y+h),ACCENT,-1)

        # Tab
        tw,th = measure("  VESSEL LOG",sc=0.37)
        cv2.rectangle(canvas,(x1+3,y),(x1+3+tw+12,y+20),BG_CARD,-1)
        cv2.rectangle(canvas,(x1+3,y),(x1+3+tw+12,y+20),BORDER,1)
        put(canvas,"  VESSEL LOG",x1+4,y+14,ACCENT,sc=0.37)

        # Column headers
        hy = y+34
        cv2.line(canvas,(x1,hy+3),(x2,hy+3),BORDER,1)

        cols = [
            (x1+14,  "ID"),
            (x1+68,  "CLASS"),
            (x1+200, "GPS POSITION"),
            (x1+400, "HDG"),
            (x1+490, "DIR"),
            (x1+580, "SPEED"),
            (x1+670, "PREDICTIONS"),
            (x1+820, "STATUS"),
        ]
        for cx,label in cols:
            put(canvas,label,cx,hy,TEXT_LO,sc=0.33)

        if not ships:
            put(canvas,"NO VESSELS IN FRAME",
                x1+20,y+65,TEXT_LO,sc=0.42)
            return

        for i,ship in enumerate(ships[:8]):
            ry  = y+54+i*26
            sid = ship["id"]
            col = ship["color"]

            if i%2==0:
                fill_rect(canvas,x1+4,ry-15,x2-1,ry+9,BG_CARD,0.55)

            # ID badge
            ib    = f"{sid:02d}"
            iw,ih = measure(ib,sc=0.38)
            bx1   = x1+14
            cv2.rectangle(canvas,(bx1,ry-ih-1),(bx1+iw+8,ry+3),
                          tuple(c//5 for c in col),-1)
            cv2.rectangle(canvas,(bx1,ry-ih-1),(bx1+iw+8,ry+3),col,1)
            put(canvas,ib,bx1+4,ry,col,sc=0.38)

            cls = ship.get("class","vessel").upper()[:10]
            put(canvas,cls,x1+68,ry,TEXT_HI,sc=0.36)

            gps = (f"{ship.get('gps_lat',0):.5f}N  "
                   f"{ship.get('gps_lon',0):.5f}E")
            put(canvas,gps,x1+200,ry,TEXT_MID,sc=0.34)

            put(canvas,f"{ship.get('heading',0):05.1f}",
                x1+400,ry,TEXT_HI,sc=0.35)

            put(canvas,ship.get("direction","--"),
                x1+490,ry,ACCENT,sc=0.35)

            put(canvas,f"{ship.get('speed',0):.2f}",
                x1+580,ry,TEXT_MID,sc=0.35)

            pn   = len(ship.get("pred_path",[]))
            pcol = ACCENT if pn>5 else TEXT_LO
            put(canvas,f"{pn} steps",x1+670,ry,pcol,sc=0.34)

            sw,sh = measure("TRACKING",sc=0.33)
            sx    = x1+820
            cv2.rectangle(canvas,(sx-3,ry-sh-2),(sx+sw+5,ry+3),
                          (0,32,20),-1)
            put(canvas,"TRACKING",sx,ry,ACCENT,sc=0.33)

    # ─── helpers ──────────────────────────────────────────────────────────────
    def _brackets(self,c,x,y,w,h):
        L,T = 16,2
        for(cx,cy),(dx,dy) in zip(
            [(x,y),(x+w,y),(x,y+h),(x+w,y+h)],
            [(1,1),(-1,1),(1,-1),(-1,-1)]):
            cv2.line(c,(cx,cy),(cx+dx*L,cy),ACCENT,T)
            cv2.line(c,(cx,cy),(cx,cy+dy*L),ACCENT,T)

    def _publish_stream(self, frame):
        if not self.ws_enabled or self.ws_server is None:
            return
        try:
            ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
            if not ok:
                return
            payload = base64.b64encode(encoded.tobytes()).decode('ascii')
            self.ws_server.broadcast({
                'type': 'frame',
                'data': payload,
            })
        except Exception as exc:
            print(f"WebSocket publish error: {exc}")

    def stop(self):
        if self.ws_server is not None:
            try:
                self.ws_server.stop()
            except Exception as exc:
                print(f"Error stopping WebSocket server: {exc}")
            self.ws_server = None
        cv2.destroyAllWindows()


    def _tab(self,c,x,y,text):
        tw,th = measure(text,sc=0.36)
        lx,ly = x, y
        cv2.rectangle(c,(lx,ly-20),(lx+tw+14,ly),BG_PANEL,-1)
        cv2.rectangle(c,(lx,ly-20),(lx+tw+14,ly),BORDER,1)
        cv2.rectangle(c,(lx,ly-20),(lx+3,ly),ACCENT,-1)
        put(c,text,lx+6,ly-6,TEXT_MID,sc=0.36)

    def _scanlines(self,c):
        for sy in range(0,self.H,5):
            c[sy] = (c[sy].astype(np.float32)*0.91).astype(np.uint8)