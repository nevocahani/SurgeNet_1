import os, json, hashlib
from datetime import datetime

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_conn():
    if DATABASE_URL:
        import psycopg2
        url = DATABASE_URL
        if 'sslmode' not in url:
            sep = '&' if '?' in url else '?'
            url += sep + 'sslmode=require'
        for attempt in range(3):
            try:
                conn = psycopg2.connect(url, connect_timeout=10)
                conn.autocommit = False
                return conn
            except Exception as e:
                if attempt == 2:
                    raise
                import time; time.sleep(0.5)
    else:
        import sqlite3
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'surgenet.db')
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

def is_pg():
    return bool(DATABASE_URL)

def ph():
    return '%s' if is_pg() else '?'

def phn(n):
    s = '%s' if is_pg() else '?'
    return ','.join([s]*n)

def fetchall(cur):
    rows = cur.fetchall()
    if is_pg():
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]

def fetchone(cur):
    row = cur.fetchone()
    if row is None:
        return None
    if is_pg():
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    return dict(row)

def fix(r):
    if r is None:
        return None
    d = dict(r)
    if 'patient' in d and isinstance(d['patient'], str):
        try: d['patient'] = json.loads(d['patient'])
        except: pass
    for f in ('can_travel','available','first_login','is_shared'):
        if f in d: d[f] = bool(d[f])
    return d

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id            {serial} PRIMARY KEY,
        username      TEXT UNIQUE NOT NULL,
        name          TEXT NOT NULL,
        role          TEXT NOT NULL,
        hospital      TEXT,
        dept          TEXT,
        password_hash TEXT,
        first_login   INTEGER DEFAULT 1,
        color         TEXT DEFAULT '#4cc9f0',
        emoji         TEXT DEFAULT '👤',
        specialty     TEXT,
        can_travel    INTEGER DEFAULT 0,
        transport     TEXT,
        available     INTEGER DEFAULT 0,
        lat           REAL,
        lng           REAL,
        is_shared     INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS requests (
        id            {serial} PRIMARY KEY,
        hospital      TEXT NOT NULL,
        dept          TEXT NOT NULL DEFAULT '',
        requested_by  TEXT NOT NULL,
        specialty     TEXT NOT NULL,
        urgency       TEXT NOT NULL,
        status        TEXT DEFAULT 'searching',
        patient       TEXT,
        surgeon_id    INTEGER,
        eta_minutes   INTEGER,
        dist_km       REAL,
        traffic_label TEXT,
        matched_at    TEXT,
        completed_at  TEXT
    )""",
]

class Database:
    def init(self):
        serial = 'SERIAL' if is_pg() else 'INTEGER'
        conn = get_conn()
        try:
            cur = conn.cursor()
            for stmt in SCHEMA:
                cur.execute(stmt.format(serial=serial))
            conn.commit()
            p = ph()
            cur.execute(f'SELECT COUNT(*) FROM users WHERE username={p}', ('admin',))
            r = cur.fetchone()
            count = r[0] if isinstance(r, (list,tuple)) else list(dict(r).values())[0]
            if count == 0:
                pw = hashlib.sha256('admin123'.encode()).hexdigest()
                if is_pg():
                    cur.execute(
                        'INSERT INTO users (username,name,role,color,emoji,first_login,password_hash) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                        ('admin','מנהל מערכת','admin','#E63946','👑',0,pw)
                    )
                else:
                    cur.execute(
                        'INSERT INTO users (username,name,role,color,emoji,first_login,password_hash) VALUES (?,?,?,?,?,?,?)',
                        ('admin','מנהל מערכת','admin','#E63946','👑',0,pw)
                    )
                conn.commit()
                print('admin created')
        finally:
            conn.close()

    def get_user(self, uid):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM users WHERE id={ph()}', (uid,))
            return fix(fetchone(cur))
        finally:
            conn.close()

    def get_user_by_username(self, username):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM users WHERE username={ph()}', (username,))
            return fix(fetchone(cur))
        finally:
            conn.close()

    def get_all_users(self):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT * FROM users ORDER BY id')
            return [fix(r) for r in fetchall(cur)]
        finally:
            conn.close()

    def get_users_by_hospital(self, hospital):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM users WHERE hospital={ph()} ORDER BY id', (hospital,))
            return [fix(r) for r in fetchall(cur)]
        finally:
            conn.close()

    def get_users_by_dept(self, hospital, dept):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM users WHERE hospital={ph()} AND dept={ph()} ORDER BY id', (hospital,dept))
            return [fix(r) for r in fetchall(cur)]
        finally:
            conn.close()

    def get_available_surgeons(self, specialty):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM users WHERE role={ph()} AND specialty={ph()} AND can_travel=1 AND available=1',('surgeon',specialty))
            return [fix(r) for r in fetchall(cur)]
        finally:
            conn.close()

    def create_user(self, username, name, role, hospital, dept, **kw):
        colors = {'admin':'#E63946','hospital_ceo':'#ffd166','dept_head':'#4cc9f0','surgeon':'#06d6a0','dept_staff':'#c77dff'}
        emojis = {'admin':'👑','hospital_ceo':'🏛️','dept_head':'🏥','surgeon':'🩺','dept_staff':'🏨'}
        color = colors.get(role,'#888')
        emoji = emojis.get(role,'👤')
        vals = (username,name,role,hospital,dept,color,emoji,
                kw.get('specialty'),int(kw.get('can_travel',False)),
                kw.get('transport'),int(kw.get('can_travel',False)),
                kw.get('lat'),kw.get('lng'),int(kw.get('is_shared',False)))
        sql = 'INSERT INTO users (username,name,role,hospital,dept,color,emoji,specialty,can_travel,transport,available,lat,lng,is_shared,first_login) VALUES ({p},1)'.format(p=phn(14))
        conn = get_conn()
        try:
            cur = conn.cursor()
            if is_pg():
                cur.execute(sql + ' RETURNING id', vals)
                uid = cur.fetchone()[0]
            else:
                cur.execute(sql, vals)
                uid = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get_user(uid)

    def set_password(self, username, password_hash):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'UPDATE users SET password_hash={ph()}, first_login=0 WHERE username={ph()}', (password_hash,username))
            conn.commit()
        finally:
            conn.close()
        return self.get_user_by_username(username)

    def update_user(self, uid, data):
        allowed = ['name','hospital','dept','specialty','can_travel','transport','available','lat','lng','color','emoji']
        fields = {k:v for k,v in data.items() if k in allowed}
        if not fields:
            return self.get_user(uid)
        p = ph()
        sets = ', '.join(f'{k}={p}' for k in fields)
        vals = list(fields.values()) + [uid]
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'UPDATE users SET {sets} WHERE id={p}', vals)
            conn.commit()
        finally:
            conn.close()
        return self.get_user(uid)

    def delete_user(self, uid):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'DELETE FROM users WHERE id={ph()}', (uid,))
            conn.commit()
        finally:
            conn.close()

    def get_request(self, rid):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM requests WHERE id={ph()}', (rid,))
            return fix(fetchone(cur))
        finally:
            conn.close()

    def get_all_requests(self):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT * FROM requests ORDER BY id DESC')
            return [fix(r) for r in fetchall(cur)]
        finally:
            conn.close()

    def get_requests_by_hospital(self, hospital):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM requests WHERE hospital={ph()} ORDER BY id DESC',(hospital,))
            return [fix(r) for r in fetchall(cur)]
        finally:
            conn.close()

    def get_requests_by_dept(self, hospital, dept):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM requests WHERE hospital={ph()} AND dept={ph()} ORDER BY id DESC',(hospital,dept))
            return [fix(r) for r in fetchall(cur)]
        finally:
            conn.close()

    def get_open_requests(self, specialty):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM requests WHERE status={ph()} AND specialty={ph()} ORDER BY id DESC',('searching',specialty))
            return [fix(r) for r in fetchall(cur)]
        finally:
            conn.close()

    def get_all_open_requests(self):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM requests WHERE status={ph()} ORDER BY id DESC',('searching',))
            return [fix(r) for r in fetchall(cur)]
        finally:
            conn.close()

    def create_request(self, hospital, dept, requested_by, specialty, urgency, patient):
        pj = json.dumps(patient, ensure_ascii=False)
        sql = 'INSERT INTO requests (hospital,dept,requested_by,specialty,urgency,patient,status) VALUES ({p})'.format(p=phn(7))
        conn = get_conn()
        try:
            cur = conn.cursor()
            vals = (hospital,dept,requested_by,specialty,urgency,pj,'searching')
            if is_pg():
                cur.execute(sql + ' RETURNING id', vals)
                rid = cur.fetchone()[0]
            else:
                cur.execute(sql, vals)
                rid = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get_request(rid)

    def match_request(self, rid, surgeon_id, eta_minutes, dist_km):
        p = ph()
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                f'UPDATE requests SET status={p},surgeon_id={p},eta_minutes={p},dist_km={p},traffic_label={p},matched_at={p} WHERE id={p}',
                ('matched',surgeon_id,eta_minutes,dist_km,self._traffic(),datetime.now().isoformat(),rid)
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_request(rid)

    def complete_request(self, rid):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'UPDATE requests SET status={ph()},completed_at={ph()} WHERE id={ph()}',
                        ('completed',datetime.now().isoformat(),rid))
            conn.commit()
        finally:
            conn.close()

    def delete_request(self, rid):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(f'DELETE FROM requests WHERE id={ph()}', (rid,))
            conn.commit()
        finally:
            conn.close()

    def _traffic(self):
        h = datetime.now().hour
        if (7<=h<=9) or (16<=h<=19): return '🔴 פקק כבד'
        if (10<=h<=15) or (20<=h<=22): return '🟡 תנועה בינונית'
        return '🟢 כביש פנוי'

    # ── login security ────────────────────────────────────────────
    def record_failed_login(self, username):
        from datetime import datetime, timedelta
        conn = get_conn()
        try:
            cur = conn.cursor()
            p = ph()
            cur.execute(f'SELECT failed_attempts FROM users WHERE username={p}', (username,))
            row = cur.fetchone()
            if not row:
                return 0
            attempts = (row[0] if isinstance(row, (list,tuple)) else list(dict(row).values())[0] or 0) + 1
            locked_until = None
            if attempts >= 5:
                locked_until = (datetime.utcnow() + timedelta(minutes=15)).isoformat()
            cur.execute(
                f'UPDATE users SET failed_attempts={p}, locked_until={p} WHERE username={p}',
                (attempts, locked_until, username)
            )
            conn.commit()
            return attempts
        finally:
            conn.close()

    def reset_failed_login(self, username):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                f'UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username={ph()}',
                (username,)
            )
            conn.commit()
        finally:
            conn.close()

    def is_locked(self, username):
        from datetime import datetime
        user = self.get_user_by_username(username)
        if not user or not user.get('locked_until'):
            return False, 0
        locked_until = datetime.fromisoformat(user['locked_until'])
        now = datetime.utcnow()
        if now < locked_until:
            mins = int((locked_until - now).total_seconds() / 60) + 1
            return True, mins
        self.reset_failed_login(username)
        return False, 0

    def log_action(self, user_id, username, action, details='', ip=''):
        from datetime import datetime
        conn = get_conn()
        try:
            cur = conn.cursor()
            if is_pg():
                cur.execute(
                    'INSERT INTO audit_log (user_id, username, action, details, ip, created_at) VALUES (%s,%s,%s,%s,%s,%s)',
                    (user_id, username, action, details, ip, datetime.utcnow().isoformat())
                )
            else:
                cur.execute(
                    'INSERT INTO audit_log (user_id, username, action, details, ip, created_at) VALUES (?,?,?,?,?,?)',
                    (user_id, username, action, details, ip, datetime.utcnow().isoformat())
                )
            conn.commit()
        except:
            pass
        finally:
            conn.close()

    def get_audit_log(self, limit=100):
        conn = get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(f'SELECT * FROM audit_log ORDER BY id DESC LIMIT {limit}')
                return fetchall(cur)
            except Exception as e:
                # fallback if columns missing
                cur2 = conn.cursor()
                cur2.execute(f'SELECT id, user_id, action, details FROM audit_log ORDER BY id DESC LIMIT {limit}')
                rows = fetchall(cur2)
                for r in rows:
                    r.setdefault('username', '—')
                    r.setdefault('ip', '—')
                    r.setdefault('created_at', '')
                return rows
        finally:
            conn.close()

    def migrate(self):
        conn = get_conn()
        try:
            cur = conn.cursor()
            migrations = [
                ('users', 'failed_attempts', 'INTEGER DEFAULT 0'),
                ('users', 'locked_until', 'TEXT'),
                ('audit_log', 'username', 'TEXT DEFAULT '''),
                ('audit_log', 'ip', 'TEXT DEFAULT '''),
                ('audit_log', 'created_at', 'TEXT DEFAULT '''),
            ]
            for table, col, coldef in migrations:
                try:
                    cur.execute(f'ALTER TABLE {table} ADD COLUMN {col} {coldef}')
                    conn.commit()
                    print(f'migrated: {table}.{col}')
                except:
                    pass
        finally:
            conn.close()

db = Database()
