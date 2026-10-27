# plate_reader.py
import easyocr
import cv2
import re

class PlateReader:
    def __init__(self):
        self.reader = easyocr.Reader(['en'], gpu=False)
        print('[PlateReader] EasyOCR ready.')

    def preprocess_plate(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    def read_plate(self, frame, box):
        x1, y1, x2, y2 = box
        pad = 5
        x1 = max(0, x1 - pad)
        y1 = max(0, y1 - pad)
        x2 = min(frame.shape[1], x2 + pad)
        y2 = min(frame.shape[0], y2 + pad)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return 'UNKNOWN'
        processed = self.preprocess_plate(crop)
        results = self.reader.readtext(processed)
        if not results:
            return 'UNKNOWN'
        text = ' '.join([r[1] for r in results])
        text = re.sub(r'[^A-Z0-9]', '', text.upper())
        return text if len(text) >= 4 else 'UNKNOWN'

    def find_plate_region(self, frame, vehicle_box):
        x1, y1, x2, y2 = vehicle_box
        h = y2 - y1
        return [x1, y1 + int(h * 0.65), x2, y2]