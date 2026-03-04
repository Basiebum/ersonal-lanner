import os
import json
import logging
import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_SCOPES        = ["https://www.googleapis.com/auth/calendar"]


# ── HELPERS ──────────────────────────────────────────────

def _google_client_config():
    return {"web": {
        "client_id":     GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
        "token_uri":     "https://oauth2.googleapis.com/token",
    }}

def _save_token(token_dict):
    """Save Google token to Supabase for the current user."""
    uid = session.get('user_id')
    if not uid or not supabase:
        # fallback to session only
        session['google_token'] = token_dict
        return
    try:
        supabase.table('users').update({'google_token': token_dict}).eq('id', uid).execute()
        session['google_token'] = token_dict  # cache in session too
    except Exception as e:
        logging.error("Failed to save google token: %s", e)
        session['google_token'] = token_dict

def _load_token():
    """Load Google token — try session cache first, then Supabase."""
    # Try session cache first (fast)
    token = session.get('google_token')
    if token:
        return token
    # Fall back to Supabase (handles multi-worker environments)
    uid = session.get('user_id')
    if not uid or not supabase:
        return None
    try:
        rows = supabase.table('users').select('google_token').eq('id', uid).execute().data
        if rows and rows[0].get('google_token'):
            token = rows[0]['google_token']
            session['google_token'] = token  # cache it
            return token
    except Exception as e:
        logging.error("Failed to load google token: %s", e)
    return None

def _delete_token():
    """Remove Google token from both session and Supabase."""
    session.pop('google_token', None)
    uid = session.get('user_id')
    if uid and supabase:
        try:
            supabase.table('users').update({'google_token': None}).eq('id', uid).execute()
        except Exception as e:
            logging.error("Failed to delete google token: %s", e)

def _get_google_creds():
    """Return valid Google Credentials, refreshing if needed."""
    token_json = _load_token()
    if not token_json:
        return None
    try:
        creds = Credentials.from_authorized_user_info(token_json, GOOGLE_SCOPES)
    except Exception:
        return None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(json.loads(creds.to_json()))
        except Exception:
            _delete_token()
            return None
    return creds if (creds and creds.valid) else None

def _wigbo_to_gcal(ev):
    date_str  = ev.get('date', '')
    start_str = ev.get('start', '09:00')
    end_str   = ev.get('end',   '10:00')
    cat_color = {'work':'9','sports':'2','social':'4','personal':'3'}
    return {
        'summary':     ev.get('title', 'Wigbo event'),
        'description': ev.get('note', ''),
        'start': {'dateTime': f"{date_str}T{start_str}:00", 'timeZone': 'Europe/Amsterdam'},
        'end':   {'dateTime': f"{date_str}T{end_str}:00",   'timeZone': 'Europe/Amsterdam'},
        'colorId': cat_color.get(ev.get('cat','personal'), '3'),
        'extendedProperties': {'private': {
            'wigbo': 'true',
            'wigbo_id':  str(ev.get('id','')),
            'wigbo_cat': ev.get('cat','personal'),
        }}
    }

def _gcal_to_wigbo(gcal_ev):
    start = gcal_ev.get('start', {})
    end   = gcal_ev.get('end',   {})
    if 'dateTime' in start:
        s = datetime.datetime.fromisoformat(start['dateTime'].replace('Z','+00:00'))
        e = datetime.datetime.fromisoformat(end['dateTime'].replace('Z','+00:00'))
        date_str, start_str, end_str = s.strftime('%Y-%m-%d'), s.strftime('%H:%M'), e.strftime('%H:%M')
    else:
        date_str, start_str, end_str = start.get('date',''), '00:00', '23:59'
    color_cat = {'9':'work','1':'work','2':'sports','10':'sports','4':'social','11':'social','3':'personal','7':'personal'}
    private   = gcal_ev.get('extendedProperties',{}).get('private',{})
    cat       = private.get('wigbo_cat') or color_cat.get(gcal_ev.get('colorId','3'),'personal')
    return {
        'id':        f"gcal_{gcal_ev['id']}",
        'gcal_id':   gcal_ev['id'],
        'title':     gcal_ev.get('summary','(no title)'),
        'date':      date_str,
        'start':     start_str,
        'end':       end_str,
        'cat':       cat,
        'note':      gcal_ev.get('description',''),
        'from_gcal': True,
    }


# ── PAGE ROUTES ───────────────────────────────────────────

@app.route("/")
def home():
    return render_template('landing.html')

@app.route('/planner')
def planner():
    if not session.get('user_id'):
        return render_template('login.html')
    return render_template('index.html')

@app.route('/login')
def login_page():
    if session.get('user_id'):
        return render_template('index.html')
    return render_template('login.html')

@app.route('/app')
def app_page():
    if not session.get('user_id'):
        return render_template('login.html')
    return render_template('index.html')


# ── GOOGLE OAUTH ──────────────────────────────────────────

@app.route('/auth/google')
def auth_google():
    redirect_uri = url_for('auth_google_callback', _external=True, _scheme='https') \
                   if not os.environ.get('FLASK_DEBUG') \
                   else url_for('auth_google_callback', _external=True)
    flow = Flow.from_client_config(
        _google_client_config(), scopes=GOOGLE_SCOPES,
        redirect_uri=redirect_uri
    )
    auth_url, state = flow.authorization_url(
        access_type='offline', include_granted_scopes='true', prompt='consent'
    )
    # Store state in Supabase so it survives across workers
    uid = session.get('user_id')
    if uid and supabase:
        try:
            supabase.table('users').update({'google_token': {'oauth_state': state}}).eq('id', uid).execute()
        except Exception:
            pass
    session['oauth_state'] = state  # also keep in session as fallback
    return redirect(auth_url)

@app.route('/auth/google/callback')
def auth_google_callback():
    # Retrieve state — try session first, then Supabase
    state = session.get('oauth_state')
    if not state:
        uid = session.get('user_id')
        if uid and supabase:
            try:
                rows = supabase.table('users').select('google_token').eq('id', uid).execute().data
                if rows and rows[0].get('google_token'):
                    state = rows[0]['google_token'].get('oauth_state')
            except Exception:
                pass

    redirect_uri = url_for('auth_google_callback', _external=True, _scheme='https') \
                   if not os.environ.get('FLASK_DEBUG') \
                   else url_for('auth_google_callback', _external=True)

    # Fix URL scheme — Render receives http but token fetch needs https
    callback_url = request.url
    if callback_url.startswith('http://') and not os.environ.get('FLASK_DEBUG'):
        callback_url = callback_url.replace('http://', 'https://', 1)

    try:
        flow = Flow.from_client_config(
            _google_client_config(), scopes=GOOGLE_SCOPES,
            redirect_uri=redirect_uri
        )
        # Skip state verification — it's unreliable across workers
        os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
        flow.fetch_token(authorization_response=callback_url)
        _save_token(json.loads(flow.credentials.to_json()))
        return redirect('/planner?gcal_connected=1')
    except Exception as e:
        logging.error("OAuth callback error: %s", e)
        return redirect(f'/planner?gcal_error=1&msg={str(e)[:80]}')

@app.route('/auth/google/disconnect', methods=['POST'])
def auth_google_disconnect():
    _delete_token()
    return jsonify({'data': 'disconnected'}), 200

@app.route('/api/gcal/status')
def gcal_status():
    return jsonify({'connected': _get_google_creds() is not None}), 200


# ── GCAL SYNC ─────────────────────────────────────────────

@app.route('/api/gcal/pull')
def gcal_pull():
    creds = _get_google_creds()
    if not creds:
        return jsonify({'error': 'not connected'}), 401
    try:
        now      = datetime.datetime.utcnow()
        time_min = (now - datetime.timedelta(days=int(request.args.get('days_back',30)))).isoformat()+'Z'
        time_max = (now + datetime.timedelta(days=int(request.args.get('days_forward',60)))).isoformat()+'Z'
        svc      = build('calendar','v3',credentials=creds)
        result   = svc.events().list(
            calendarId='primary', timeMin=time_min, timeMax=time_max,
            maxResults=500, singleEvents=True, orderBy='startTime'
        ).execute()
        events = [_gcal_to_wigbo(e) for e in result.get('items',[]) if e.get('status')!='cancelled']
        return jsonify({'data': events}), 200
    except Exception as e:
        logging.error("gcal pull: %s", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/gcal/push', methods=['POST'])
def gcal_push():
    creds = _get_google_creds()
    if not creds:
        return jsonify({'error': 'not connected'}), 401
    ev = (request.get_json() or {}).get('event', {})
    if not ev:
        return jsonify({'error': 'no event'}), 400
    try:
        svc      = build('calendar','v3',credentials=creds)
        existing = ev.get('gcal_id')
        if existing:
            result = svc.events().update(calendarId='primary', eventId=existing, body=_wigbo_to_gcal(ev)).execute()
        else:
            result = svc.events().insert(calendarId='primary', body=_wigbo_to_gcal(ev)).execute()
        return jsonify({'data': {'gcal_id': result['id']}}), 200
    except Exception as e:
        logging.error("gcal push: %s", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/gcal/delete', methods=['POST'])
def gcal_delete():
    creds = _get_google_creds()
    if not creds:
        return jsonify({'error': 'not connected'}), 401
    gcal_id = (request.get_json() or {}).get('gcal_id')
    if not gcal_id:
        return jsonify({'error': 'no gcal_id'}), 400
    try:
        build('calendar','v3',credentials=creds).events().delete(
            calendarId='primary', eventId=gcal_id
        ).execute()
        return jsonify({'data': 'deleted'}), 200
    except Exception as e:
        logging.error("gcal delete: %s", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/gcal/sync', methods=['POST'])
def gcal_sync():
    creds = _get_google_creds()
    if not creds:
        return jsonify({'error': 'not connected'}), 401
    payload        = request.get_json() or {}
    events_to_push = [e for e in payload.get('events',[]) if not e.get('from_gcal')]
    try:
        svc    = build('calendar','v3',credentials=creds)
        pushed = []
        for ev in events_to_push:
            r = svc.events().insert(calendarId='primary', body=_wigbo_to_gcal(ev)).execute()
            pushed.append({'wigbo_id': ev.get('id'), 'gcal_id': r['id']})
        now      = datetime.datetime.utcnow()
        time_min = (now - datetime.timedelta(days=30)).isoformat()+'Z'
        time_max = (now + datetime.timedelta(days=60)).isoformat()+'Z'
        result   = svc.events().list(
            calendarId='primary', timeMin=time_min, timeMax=time_max,
            maxResults=500, singleEvents=True, orderBy='startTime'
        ).execute()
        pulled = [_gcal_to_wigbo(e) for e in result.get('items',[]) if e.get('status')!='cancelled']
        return jsonify({'data': {'pushed': pushed, 'pulled': pulled}}), 200
    except Exception as e:
        logging.error("gcal sync: %s", e)
        return jsonify({'error': str(e)}), 500


# ── AUTH & DATA ───────────────────────────────────────────

@app.route("/api/save", methods=["POST"])
def api_save():
    try:
        if not supabase: return jsonify({"error": "Supabase not configured."}), 500
        payload = request.get_json() or {}
        user_id = session.get('user_id')
        if not user_id: return jsonify({"error": "authentication required"}), 401
        res = supabase.table("plans").insert({"name": payload.get("name","plan"), "data": payload.get("data",{}), "user_id": user_id}).execute()
        return jsonify({"data": res.data}), 200
    except Exception:
        logging.exception("/api/save")
        return jsonify({"error": "internal server error"}), 500

@app.route("/api/plans", methods=["GET"])
def api_plans():
    try:
        if not supabase: return jsonify({"error": "Supabase not configured."}), 500
        user_id = session.get('user_id')
        if not user_id: return jsonify({"error": "authentication required"}), 401
        res = supabase.table("plans").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return jsonify({"data": res.data}), 200
    except Exception:
        logging.exception("/api/plans")
        return jsonify({"error": "internal server error"}), 500

@app.route("/health")
def health():
    return jsonify({"supabase_configured": bool(SUPABASE_URL and SUPABASE_KEY)}), 200

@app.route('/api/register', methods=['POST'])
def api_register():
    try:
        if not supabase: return jsonify({"error": "Supabase not configured."}), 500
        p = request.get_json() or {}
        email, password = (p.get('email') or '').strip().lower(), p.get('password') or ''
        if not email or not password: return jsonify({'error': 'email and password required'}), 400
        if supabase.table('users').select('id').eq('email', email).execute().data:
            return jsonify({'error': 'user already exists'}), 400
        ins = supabase.table('users').insert({'email': email, 'password_hash': generate_password_hash(password)}).execute()
        session['user_id'] = ins.data[0].get('id') or email
        return jsonify({'data': {'user_id': session['user_id'], 'email': email}}), 200
    except Exception:
        logging.exception('/api/register')
        return jsonify({'error': 'internal server error'}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        if not supabase: return jsonify({"error": "Supabase not configured."}), 500
        p = request.get_json() or {}
        email, password = (p.get('email') or '').strip().lower(), p.get('password') or ''
        if not email or not password: return jsonify({'error': 'email and password required'}), 400
        rows = supabase.table('users').select('*').eq('email', email).execute().data
        if not rows or not check_password_hash(rows[0].get('password_hash',''), password):
            return jsonify({'error': 'invalid credentials'}), 400
        session['user_id'] = rows[0].get('id') or email
        # Cache google token in session if it exists in db
        if rows[0].get('google_token'):
            session['google_token'] = rows[0]['google_token']
        return jsonify({'data': {'user_id': session['user_id'], 'email': email}}), 200
    except Exception:
        logging.exception('/api/login')
        return jsonify({'error': 'internal server error'}), 500

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'data': 'ok'}), 200

@app.route('/api/me')
def api_me():
    try:
        uid = session.get('user_id')
        if not uid: return jsonify({'error': 'not authenticated'}), 401
        gcal_connected = _get_google_creds() is not None
        if supabase:
            rows = supabase.table('users').select('id,email,created_at').eq('id', uid).execute().data
            if rows:
                return jsonify({'data': {**rows[0], 'gcal_connected': gcal_connected}}), 200
        return jsonify({'data': {'id': uid, 'gcal_connected': gcal_connected}}), 200
    except Exception:
        logging.exception('/api/me')
        return jsonify({'error': 'internal server error'}), 500

if __name__ == "__main__":
    app.run(debug=True)
