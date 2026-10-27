# risk_engine.py
import sqlite3
from datetime import datetime

class RiskEngine:
    def __init__(self, db_path='violations.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS violations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                plate      TEXT,
                risk_score INTEGER,
                response   TEXT,
                fine_amt   INTEGER,
                timestamp  TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def compute_score(self, speed_kmh, has_helmet, near_miss):
        score = 0
        if speed_kmh > 80:
            score += 50
        elif speed_kmh > 60:
            score += 30
        elif speed_kmh > 40:
            score += 10
        if not has_helmet:
            score += 40
        if near_miss:
            score += 30
        return min(score, 120)

    def get_prior_count(self, plate):
        conn = sqlite3.connect(self.db_path)
        count = conn.execute(
            'SELECT COUNT(*) FROM violations WHERE plate=?', (plate,)
        ).fetchone()[0]
        conn.close()
        return count

    def get_response(self, score, plate):
        prior = self.get_prior_count(plate)
        if score < 30 and prior == 0:
            return 'WARNING', 0
        elif score < 60:
            return 'FINE', 500
        elif score < 90:
            return 'FINE', 1500
        elif score < 120:
            return 'HEAVY_FINE', 3000
        else:
            return 'HEAVY_FINE+FLAG', 5000

    def log(self, plate, score, response, fine):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            'INSERT INTO violations VALUES (NULL,?,?,?,?,?)',
            (plate, score, response, fine,
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        conn.close()

    def process(self, plate, speed, has_helmet, near_miss):
        score = self.compute_score(speed, has_helmet, near_miss)
        response, fine = self.get_response(score, plate)
        self.log(plate, score, response, fine)
        return {'score': score, 'response': response, 'fine': fine}