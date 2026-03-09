import sqlite3, json, os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'surgenet.db')

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def row(r):
    if r is None:
        return None
    d = dict(r)
    # parse JSON fields
    for f in ('patient',):
        if f in d and isinstance(d[f], str):
            try: d[f] = json.loads(d[f])
            except: pass
    # booleans
    for f in ('can_travel', 'available', 'first_login', 'is_shared'):
        if f in d:
            d[f] = bool(d[f])
    return d

class Database:
    def init(self):
        with get_conn() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT UNIQUE NOT NULL,
                    name          TEXT NOT NULL,
                    role          TEXT NOT NULL,
                    hospital      TEXT,
                    dept          TEXT,
                    password_hash TEXT,
                    first_login   INTEGER DEFAULT 1,
                    color         TEXT DEFAULT "#4cc9f0",
                    emoji         TEXT DEFAULT "👤",
                    specialty     TEXT,
                    can_travel    INTEGER DEFAULT 0,
                    transport     TEXT,
                    available     INTEGER DEFAULT 0,
                    lat           REAL,
                    lng           REAL,
                    is_shared     INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS requests (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    hospital     TEXT NOT NULL,
                    dept         TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    specialty    TEXT NOT NULL,
                    urgency      TEXT NOT NULL,
                    status       TEXT DEFAULT "searching",
                    patient      TEXT,
                    surgeon_id   INTEGER,
                    eta_minutes  INTEGER,
                    dist_km      REAL,
                    traffic_label TEXT,
                    matched_at   TEXT,
                    completed_at TEXT,
                    elapsed      INTEGER DEFAULT 0,
                    FOREIGN KEY (surgeon_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    action     TEXT,
                    details    TEXT
                );
            ''')
            # Create default admin if no users exist
            cur = c.execute('SELECT COUNT(*) FROM users')
            if cur.fetchone()[0] == 0:
                import hashlib
                c.execute('''INSERT INTO users (username, name, role, color, emoji, first_login, password_hash)
                             VALUES (?, ?, ?, ?, ?, ?, ?)''',
                          ('admin', 'מנהל מערכת', 'admin', '#E63946', '👑', 0,
                           hashlib.sha256('admin123'.encode()).hexdigest()))
                print('✅ נוצר משתמש admin ראשוני (סיסמה: admin123)')

    # ── users ──────────────────────────────────────────────────
    def get_user(self, uid):
        with get_conn() as c:
            return row(c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())

    def get_user_by_username(self, username):
        with get_conn() as c:
            return row(c.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone())

    def get_all_users(self):
        with get_conn() as c:
            return [row(r) for r in c.execute('SELECT * FROM users ORDER BY role, name').fetchall()]

    def get_users_by_hospital(self, hospital):
        with get_conn() as c:
            return [row(r) for r in c.execute(
                'SELECT * FROM users WHERE hospital=? ORDER BY role, name', (hospital,)).fetchall()]

    def get_users_by_dept(self, hospital, dept):
        with get_conn() as c:
            return [row(r) for r in c.execute(
                'SELECT * FROM users WHERE hospital=? AND dept=? ORDER BY role, name',
                (hospital, dept)).fetchall()]

    def get_available_surgeons(self, specialty):
        with get_conn() as c:
            return [row(r) for r in c.execute(
                'SELECT * FROM users WHERE role="surgeon" AND specialty=? AND can_travel=1 AND available=1',
                (specialty,)).fetchall()]

    def create_user(self, username, name, role, hospital, dept, **kwargs):
        role_config = {
            'admin':       ('#E63946', '👑'),
            'hospital_ceo':('#ffd166', '🏛️'),
            'dept_head':   ('#4cc9f0', '🏥'),
            'surgeon':     ('#06d6a0', '🩺'),
            'dept_staff':  ('#c77dff', '🏨'),
        }
        color, emoji = role_config.get(role, ('#888', '👤'))
        with get_conn() as c:
            c.execute('''INSERT INTO users
                (username, name, role, hospital, dept, color, emoji,
                 specialty, can_travel, transport, available, lat, lng, is_shared, first_login)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)''',
                (username, name, role, hospital, dept, color, emoji,
                 kwargs.get('specialty'), int(kwargs.get('can_travel', False)),
                 kwargs.get('transport'), int(kwargs.get('can_travel', False)),
                 kwargs.get('lat'), kwargs.get('lng'), int(kwargs.get('is_shared', False))))
            uid = c.lastrowid
        return self.get_user(uid)

    def set_password(self, username, password_hash):
        with get_conn() as c:
            c.execute('UPDATE users SET password_hash=?, first_login=0 WHERE username=?',
                      (password_hash, username))
        return self.get_user_by_username(username)

    def update_user(self, uid, data):
        allowed = ['name', 'hospital', 'dept', 'specialty', 'can_travel',
                   'transport', 'available', 'lat', 'lng', 'color', 'emoji']
        fields = {k: v for k, v in data.items() if k in allowed}
        if not fields:
            return self.get_user(uid)
        sets = ', '.join(f'{k}=?' for k in fields)
        vals = list(fields.values()) + [uid]
        with get_conn() as c:
            c.execute(f'UPDATE users SET {sets} WHERE id=?', vals)
        return self.get_user(uid)

    def delete_user(self, uid):
        with get_conn() as c:
            c.execute('DELETE FROM users WHERE id=?', (uid,))

    # ── requests ───────────────────────────────────────────────
    def get_request(self, rid):
        with get_conn() as c:
            return row(c.execute('SELECT * FROM requests WHERE id=?', (rid,)).fetchone())

    def get_all_requests(self):
        with get_conn() as c:
            return [row(r) for r in c.execute(
                'SELECT * FROM requests ORDER BY created_at DESC').fetchall()]

    def get_requests_by_hospital(self, hospital):
        with get_conn() as c:
            return [row(r) for r in c.execute(
                'SELECT * FROM requests WHERE hospital=? ORDER BY created_at DESC',
                (hospital,)).fetchall()]

    def get_requests_by_dept(self, hospital, dept):
        with get_conn() as c:
            return [row(r) for r in c.execute(
                'SELECT * FROM requests WHERE hospital=? AND dept=? ORDER BY created_at DESC',
                (hospital, dept)).fetchall()]

    def get_open_requests(self, specialty):
        with get_conn() as c:
            return [row(r) for r in c.execute(
                'SELECT * FROM requests WHERE status="searching" AND specialty=? ORDER BY created_at DESC',
                (specialty,)).fetchall()]

    def create_request(self, hospital, dept, requested_by, specialty, urgency, patient):
        with get_conn() as c:
            c.execute('''INSERT INTO requests
                (hospital, dept, requested_by, specialty, urgency, patient, status)
                VALUES (?,?,?,?,?,?,?)''',
                (hospital, dept, requested_by, specialty, urgency,
                 json.dumps(patient, ensure_ascii=False), 'searching'))
            rid = c.lastrowid
        return self.get_request(rid)

    def match_request(self, rid, surgeon_id, eta_minutes, dist_km):
        from datetime import datetime
        surgeon = self.get_user(surgeon_id)
        traffic = self._traffic_label()
        with get_conn() as c:
            c.execute('''UPDATE requests SET
                status="matched", surgeon_id=?, eta_minutes=?, dist_km=?,
                traffic_label=?, matched_at=?
                WHERE id=?''',
                (surgeon_id, eta_minutes, dist_km, traffic,
                 datetime.now().isoformat(), rid))
        return self.get_request(rid)

    def complete_request(self, rid):
        with get_conn() as c:
            c.execute('UPDATE requests SET status="completed", completed_at=? WHERE id=?',
                      (datetime.now().isoformat(), rid))

    def delete_request(self, rid):
        with get_conn() as c:
            c.execute('DELETE FROM requests WHERE id=?', (rid,))

    def _traffic_label(self):
        h = datetime.now().hour
        if (7<=h<=9) or (16<=h<=19): return '🔴 פקק כבד'
        if (10<=h<=15) or (20<=h<=22): return '🟡 תנועה בינונית'
        return '🟢 כביש פנוי'

db = Database()
