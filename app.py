from flask import Flask, request, jsonify, session, render_template, send_from_directory
from database import db
from functools import wraps
import hashlib, os, time, sys

import database
database.DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'surgenet.db')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(32))
from datetime import timedelta
app.permanent_session_lifetime = timedelta(hours=8)

@app.before_request
def check_session_timeout():
    import time
    if 'user_id' in session:
        now = time.time()
        last = session.get('last_active')
        if last is None:
            # first request after login - set last_active
            session['last_active'] = now
        elif now - last > 8 * 3600:  # 8 hours inactive
            session.clear()
            return
        else:
            session['last_active'] = now

# ── helpers ──────────────────────────────────────────────────────
def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def login_required(roles=None):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'error': 'לא מחובר'}), 401
            user = db.get_user(session['user_id'])
            if not user:
                return jsonify({'error': 'משתמש לא נמצא'}), 401
            if roles and user['role'] not in roles:
                return jsonify({'error': 'אין הרשאה'}), 403
            return f(user, *args, **kwargs)
        return wrapper
    return decorator

# ── auth ─────────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password  = data.get('password', '')
    ip = request.remote_addr or ''

    user = db.get_user_by_username(username)
    if not user:
        return jsonify({'error': 'שם משתמש לא קיים'}), 401

    # check if locked
    locked, mins = db.is_locked(username)
    if locked:
        return jsonify({'error': f'החשבון נעול ל-{mins} דקות נוספות עקב ניסיונות כניסה כושלים'}), 423

    if user['first_login']:
        session['pending_user'] = username
        return jsonify({'first_login': True, 'name': user['name']})

    if user['password_hash'] != hash_password(password):
        attempts = db.record_failed_login(username)
        remaining = max(0, 5 - attempts)
        db.log_action(user['id'], username, 'login_failed', f'ניסיון {attempts}/5', ip)
        if attempts >= 5:
            return jsonify({'error': 'החשבון נעול ל-15 דקות עקב 5 ניסיונות כושלים'}), 423
        return jsonify({'error': f'סיסמה שגויה — נותרו {remaining} ניסיונות'}), 401

    db.reset_failed_login(username)
    session['user_id'] = user['id']
    session['remembered'] = bool(data.get('remember_me', False))
    db.log_action(user['id'], username, 'login', 'כניסה מוצלחת', ip)
    return jsonify({'ok': True, 'user': safe_user(user)})

@app.route('/api/first-login', methods=['POST'])
def first_login():
    username = session.get('pending_user')
    if not username:
        return jsonify({'error': 'אין בקשה ממתינה'}), 400
    data = request.json
    p1, p2 = data.get('password', ''), data.get('confirm', '')
    if len(p1) < 6:
        return jsonify({'error': 'הסיסמה חייבת להכיל לפחות 6 תווים'}), 400
    if p1 != p2:
        return jsonify({'error': 'הסיסמאות אינן תואמות'}), 400
    user = db.set_password(username, hash_password(p1))
    session.pop('pending_user', None)
    session['user_id'] = user['id']
    session['remembered'] = bool(data.get('remember_me', False))
    return jsonify({'ok': True, 'user': safe_user(user)})

@app.route('/api/logout', methods=['POST'])
def logout():
    uid = session.get('user_id')
    if uid:
        user = db.get_user(uid)
        if user:
            db.log_action(uid, user['username'], 'logout', '', request.remote_addr or '')
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/me')
def me():
    if 'user_id' not in session:
        return jsonify({'logged_in': False})
    user = db.get_user(session['user_id'])
    if not user:
        return jsonify({'logged_in': False})
    return jsonify({'logged_in': True, 'user': safe_user(user), 'remembered': session.get('remembered', False)})

@app.route('/api/change-password', methods=['POST'])
@login_required()
def change_password(current_user):
    data = request.json
    old_pw  = data.get('old_password', '')
    new_pw  = data.get('new_password', '')
    if current_user['password_hash'] != hash_password(old_pw):
        return jsonify({'error': 'הסיסמה הנוכחית שגויה'}), 400
    if len(new_pw) < 6:
        return jsonify({'error': 'הסיסמה חייבת להכיל לפחות 6 תווים'}), 400
    db.set_password(current_user['username'], hash_password(new_pw))
    return jsonify({'ok': True})

# ── users management ─────────────────────────────────────────────
@app.route('/api/users', methods=['GET'])
@login_required(roles=['admin', 'hospital_ceo', 'dept_head'])
def get_users(current_user):
    role = current_user['role']
    if role == 'admin':
        users = db.get_all_users()
    elif role == 'hospital_ceo':
        users = db.get_users_by_hospital(current_user['hospital'])
    else:  # dept_head
        users = db.get_users_by_dept(current_user['hospital'], current_user['dept'])
    return jsonify([safe_user(u) for u in users])

@app.route('/api/users', methods=['POST'])
@login_required(roles=['admin', 'hospital_ceo', 'dept_head'])
def create_user(current_user):
    data = request.json
    username = data.get('username', '').strip()
    name     = data.get('name', '').strip()
    role     = data.get('role', '')
    hospital = data.get('hospital', current_user['hospital'])
    dept     = data.get('dept', current_user.get('dept'))

    # validate
    if not username or not name or not role:
        return jsonify({'error': 'יש למלא את כל השדות'}), 400
    if db.get_user_by_username(username):
        return jsonify({'error': 'שם משתמש כבר קיים'}), 400

    # permission checks
    if current_user['role'] == 'hospital_ceo' and role not in ['dept_head', 'dept_staff', 'surgeon']:
        return jsonify({'error': 'אין הרשאה ליצור תפקיד זה'}), 403
    if current_user['role'] == 'dept_head' and role not in ['surgeon', 'dept_staff']:
        return jsonify({'error': 'אין הרשאה ליצור תפקיד זה'}), 403

    extra = {
        'specialty':   data.get('specialty'),
        'can_travel':  data.get('can_travel', False),
        'transport':   data.get('transport'),
        'lat':         data.get('lat'),
        'lng':         data.get('lng'),
        'is_shared':   data.get('is_shared', False),
    }
    user = db.create_user(username, name, role, hospital, dept, **extra)
    return jsonify({'ok': True, 'user': safe_user(user)}), 201

@app.route('/api/users/<int:uid>', methods=['PUT'])
@login_required()
def update_user(current_user, uid):
    # surgeon can only update themselves
    if current_user['role'] == 'surgeon' and current_user['id'] != uid:
        return jsonify({'error': 'אין הרשאה'}), 403
    if current_user['role'] not in ['admin','hospital_ceo','dept_head','surgeon']:
        return jsonify({'error': 'אין הרשאה'}), 403
    # convert booleans to int for PostgreSQL
    data = request.json
    for field in ('can_travel', 'available'):
        if field in data and isinstance(data[field], bool):
            data[field] = int(data[field])
    user = db.update_user(uid, data)
    if not user:
        return jsonify({'error': 'משתמש לא נמצא'}), 404
    return jsonify({'ok': True, 'user': safe_user(user)})

@app.route('/api/users/<int:uid>', methods=['DELETE'])
@login_required(roles=['admin', 'hospital_ceo', 'dept_head'])
def delete_user(current_user, uid):
    db.delete_user(uid)
    return jsonify({'ok': True})

@app.route('/api/surgeon/availability', methods=['POST'])
@login_required(roles=['surgeon'])
def set_availability(current_user):
    data = request.json
    can_travel = int(bool(data.get('can_travel', False)))
    transport  = data.get('transport')
    available  = int(bool(data.get('available', can_travel)))
    db.update_user(current_user['id'], {
        'can_travel': can_travel,
        'transport':  transport,
        'available':  available,
    })
    return jsonify({'ok': True})

# ── requests ─────────────────────────────────────────────────────
@app.route('/api/requests', methods=['GET'])
@login_required()
def get_requests(current_user):
    role = current_user['role']
    if role == 'admin':
        reqs = db.get_all_requests()
    elif role == 'hospital_ceo':
        reqs = db.get_requests_by_hospital(current_user['hospital'])
    elif role in ('dept_head', 'dept_staff'):
        reqs = db.get_requests_by_dept(current_user['hospital'], current_user['dept'])
    elif role == 'surgeon':
        # show all open requests - surgeon can decide to accept or not
        reqs = db.get_all_open_requests()
    else:
        reqs = []
    return jsonify(reqs)

@app.route('/api/requests', methods=['POST'])
@login_required(roles=['dept_head', 'dept_staff'])
def create_request(current_user):
    data = request.json
    required = ['patient_name', 'patient_age', 'patient_gender', 'condition', 'meds', 'specialty', 'urgency']
    for field in required:
        if not data.get(field, '').strip():
            return jsonify({'error': f'שדה חסר: {field}'}), 400

    req = db.create_request(
        hospital     = current_user['hospital'],
        dept         = current_user.get('dept') or '',
        requested_by = data.get('sender_name', current_user['name']),
        specialty    = data['specialty'],
        urgency      = data['urgency'],
        patient      = {
            'name':      data['patient_name'],
            'age':       data['patient_age'],
            'gender':    data['patient_gender'],
            'condition': data['condition'],
            'meds':      data['meds'],
            'record_id': data.get('record_id', ''),
        }
    )
    # auto-match in background
    _auto_match(req['id'])
    # send push notifications to available surgeons
    _notify_surgeons(req)
    return jsonify({'ok': True, 'request': req}), 201

@app.route('/api/requests/<int:rid>/accept', methods=['POST'])
@login_required(roles=['surgeon'])
def accept_request(current_user, rid):
    req = db.get_request(rid)
    if not req or req['status'] != 'searching':
        return jsonify({'error': 'בקשה לא זמינה'}), 400
    travel = _calc_travel(current_user, req)
    db.match_request(rid, current_user['id'], travel['mins'], travel['dist'])
    return jsonify({'ok': True, 'eta_minutes': travel['mins']})

@app.route('/api/requests/<int:rid>/complete', methods=['POST'])
@login_required(roles=['dept_head', 'dept_staff'])
def complete_request(current_user, rid):
    db.complete_request(rid)
    # schedule deletion after 20 seconds (in production: use a task queue)
    return jsonify({'ok': True, 'delete_after_seconds': 20})

@app.route('/api/requests/<int:rid>', methods=['DELETE'])
@login_required(roles=['dept_head', 'dept_staff', 'admin'])
def delete_request(current_user, rid):
    db.delete_request(rid)
    return jsonify({'ok': True})

# ── matching engine ───────────────────────────────────────────────
def _calc_travel(surgeon, req):
    import math, urllib.request, json as _json

    dest = _hospital_coords(req['hospital'])
    if not surgeon.get('lat') or not dest:
        return {'mins': 20, 'dist': 10}

    # ── OpenRouteService API (חינמי, ללא כרטיס אשראי) ───────────
    api_key = os.environ.get('ORS_API_KEY')
    if api_key and surgeon.get('lat') and dest:
        try:
            url = 'https://api.openrouteservice.org/v2/directions/driving-car'
            body = _json.dumps({
                'coordinates': [
                    [surgeon['lng'], surgeon['lat']],
                    [dest['lng'], dest['lat']]
                ]
            }).encode('utf-8')
            req_obj = urllib.request.Request(
                url,
                data=body,
                headers={
                    'Authorization': api_key,
                    'Content-Type': 'application/json'
                }
            )
            with urllib.request.urlopen(req_obj, timeout=5) as r:
                data = _json.loads(r.read())
            summary = data['routes'][0]['summary']
            mins = max(3, round(summary['duration'] / 60))
            dist = round(summary['distance'] / 1000, 1)
            return {'mins': mins, 'dist': dist}
        except Exception as e:
            print(f'ORS API error: {e} — falling back to estimate')

    # ── fallback: חישוב מוערך לפי פקקים ────────────────────────
    lat1, lng1 = surgeon['lat'], surgeon['lng']
    lat2, lng2 = dest['lat'], dest['lng']
    R = 6371
    dlat = (lat2-lat1)*math.pi/180
    dlng = (lng2-lng1)*math.pi/180
    a = math.sin(dlat/2)**2 + math.cos(lat1*math.pi/180)*math.cos(lat2*math.pi/180)*math.sin(dlng/2)**2
    dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    from datetime import datetime
    h = datetime.now().hour
    tf = 4.2 if (7<=h<=9 or 16<=h<=19) else 2.6 if (10<=h<=15 or 20<=h<=22) else 1.7
    mins = max(3, round(dist / (50/60/tf*50)))
    return {'mins': mins, 'dist': round(dist, 1)}

def _hospital_coords(name):
    coords = {
        'איכילוב':           {'lat': 32.0871, 'lng': 34.7918},
        'שיבא':              {'lat': 32.0462, 'lng': 34.8516},
        'הדסה עין כרם':      {'lat': 31.7659, 'lng': 35.1522},
        'הדסה הר הצופים':    {'lat': 31.7943, 'lng': 35.2420},
        'רמב"ם':             {'lat': 32.8324, 'lng': 34.9897},
        'וולפסון':           {'lat': 31.9962, 'lng': 34.8052},
        'סורוקה':            {'lat': 31.2518, 'lng': 34.7913},
        'שערי צדק':          {'lat': 31.7817, 'lng': 35.1878},
    }
    return coords.get(name)


def _notify_surgeons(req):
    try:
        import json as _json
        surgeons = db.get_all_available_surgeons()
        subs = db.get_all_push_subscriptions()
        if not subs:
            return
        payload = _json.dumps({
            'title': f'🚨 בקשת חירום — {req["specialty"]}',
            'body': f'{req["hospital"]} · {req["dept"]} · {req.get("urgency","קריטי")}',
            'url': '/'
        }, ensure_ascii=False)
        vapid_key = os.environ.get('VAPID_PRIVATE_KEY')
        vapid_claims = {'sub': f'mailto:{os.environ.get("MAIL_USER","surgenet@example.com")}'}
        if not vapid_key:
            return
        from pywebpush import webpush, WebPushException
        for sub_info in subs:
            try:
                webpush(
                    subscription_info=sub_info['subscription'],
                    data=payload,
                    vapid_private_key=vapid_key,
                    vapid_claims=vapid_claims
                )
            except Exception as e:
                print(f'Push error: {e}')
    except Exception as e:
        print(f'Notify error: {e}')

def _auto_match(req_id):
    req = db.get_request(req_id)
    if not req:
        return
    surgeons = db.get_available_surgeons(req['specialty'])
    if not surgeons:
        return
    ranked = sorted(surgeons, key=lambda s: _calc_travel(s, req)['mins'])
    best = ranked[0]
    travel = _calc_travel(best, req)
    db.match_request(req_id, best['id'], travel['mins'], travel['dist'])

# ── hospitals list ───────────────────────────────────────────────
@app.route('/api/audit-log')
@login_required(roles=['admin'])
def get_audit_log(current_user):
    logs = db.get_audit_log(limit=200)
    return jsonify(logs)

@app.route('/manifest.json')
def manifest():
    return send_from_directory(BASE_DIR, 'manifest.json')

@app.route('/sw.js')
def service_worker():
    response = send_from_directory(BASE_DIR, 'sw.js')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/api/push/subscribe', methods=['POST'])
@login_required()
def push_subscribe(current_user):
    data = request.json
    sub = data.get('subscription')
    if not sub:
        return jsonify({'error': 'חסר subscription'}), 400
    db.save_push_subscription(current_user['id'], sub)
    return jsonify({'ok': True})

@app.route('/api/push/unsubscribe', methods=['POST'])
@login_required()
def push_unsubscribe(current_user):
    db.delete_push_subscription(current_user['id'])
    return jsonify({'ok': True})

@app.route('/api/hospitals')
def hospitals():
    return jsonify([
        'איכילוב', 'שיבא', 'הדסה עין כרם', 'הדסה הר הצופים',
        'רמב"ם', 'וולפסון', 'סורוקה', 'שערי צדק', 'בני ציון', 'זיו'
    ])

# ── serve frontend ───────────────────────────────────────────────
def safe_user(u):
    return {k: v for k, v in u.items() if k != 'password_hash'}

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    db.init()
    db.migrate()
    port = int(os.environ.get('PORT', 5000))
    is_production = bool(os.environ.get('DATABASE_URL'))
    host = '0.0.0.0'
    debug = not is_production
    print(f'\n✅ SurgeNet פועל על port {port} בכתובת {host}\n')
    app.run(host=host, port=port, debug=debug, use_reloader=False)
