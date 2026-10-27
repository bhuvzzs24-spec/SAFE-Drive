# detector.py
from ultralytics import YOLO

VEHICLE_CLASSES = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}

class Detector:
    def __init__(self, model_path='yolov8n.pt', helmet_model_path=None, conf=0.4):
        self.model = YOLO(model_path)
        self.conf = conf
        self.helmet_model = YOLO(helmet_model_path) if helmet_model_path else None
        print(f'[Detector] Model loaded: {model_path}')

    def detect(self, frame):
        results = self.model(frame, verbose=False)[0]
        vehicles = []
        helmets = []
        plates = []
        for box in results.boxes:
            cls = int(box.cls[0])
            conf = float(box.conf[0])
            coords = box.xyxy[0].cpu().numpy().astype(int)
            if conf < self.conf:
                continue
            if cls in VEHICLE_CLASSES:
                vehicles.append({
                    'box': coords,
                    'class': VEHICLE_CLASSES[cls],
                    'conf': round(conf, 2)
                })
        if self.helmet_model:
            h_results = self.helmet_model(frame, verbose=False)[0]
            for box in h_results.boxes:
                conf = float(box.conf[0])
                coords = box.xyxy[0].cpu().numpy().astype(int)
                label = self.helmet_model.names[int(box.cls[0])]
                if conf >= self.conf:
                    helmets.append({'box': coords, 'label': label, 'conf': round(conf, 2)})
        return vehicles, helmets, plates

    def get_center(self, box):
        x1, y1, x2, y2 = box
        return int((x1 + x2) / 2), int((y1 + y2) / 2)

    def get_area(self, box):
        x1, y1, x2, y2 = box
        return (x2 - x1) * (y2 - y1)

    def check_helmet_for_rider(self, rider_box, helmets):
        rx1, ry1, rx2, ry2 = rider_box
        for h in helmets:
            hx1, hy1, hx2, hy2 = h['box']
            ox = max(0, min(rx2, hx2) - max(rx1, hx1))
            oy = max(0, min(ry2, hy2) - max(ry1, hy1))
            if ox > 0 and oy > 0 and h['label'] == 'helmet':
                return True
        return False