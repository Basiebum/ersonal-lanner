import os
import logging
from flask import Flask, render_template, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret')

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None


@app.route("/")
def home():
    # Public personal website — always accessible, no login required
    return render_template('landing.html')


@app.route('/planner')
def planner():
    # Private planner app — requires authentication
    if not session.get('user_id'):
        return render_template('login.html')
    return render_template('index.html')


@app.route('/login')
def login_page():
    if session.get('user_id'):
        return render_template('index.html')
    return render_template('login.html')


# ── keep /app as alias so old bookmarks still work ──
@app.route('/app')
def app_page():
    if not session.get('user_id'):
        return render_template('login.html')
    return render_template('index.html')


@app.route("/api/save", methods=["POST"])
def api_save():
    logging.info("/api/save called from %s", request.remote_addr)
    try:
        if not supabase:
            return jsonify({"error": "Supabase not configured on server."}), 500
        payload = request.get_json() or {}
        name = payload.get("name", "plan")
        data = payload.get("data", {})
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "authentication required"}), 401
        row = {"name": name, "data": data, "user_id": user_id}
        res = supabase.table("plans").insert(row).execute()
        if hasattr(res, 'error') and res.error:
            return jsonify({"error": str(res.error)}), 500
        return jsonify({"data": res.data}), 200
    except Exception:
        logging.exception("Unhandled exception in /api/save")
        return jsonify({"error": "internal server error"}), 500


@app.route("/api/plans", methods=["GET"])
def api_plans():
    try:
        if not supabase:
            return jsonify({"error": "Supabase not configured on server."}), 500
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "authentication required"}), 401
        res = supabase.table("plans").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        if hasattr(res, 'error') and res.error:
            return jsonify({"error": str(res.error)}), 500
        return jsonify({"data": res.data}), 200
    except Exception:
        logging.exception("Unhandled exception in /api/plans")
        return jsonify({"error": "internal server error"}), 500


@app.route("/health", methods=["GET"])
def health():
    configured = bool(SUPABASE_URL and SUPABASE_KEY)
    return jsonify({"supabase_configured": configured, "supabase_url": SUPABASE_URL or None}), 200


@app.route('/api/register', methods=['POST'])
def api_register():
    try:
        if not supabase:
            return jsonify({"error": "Supabase not configured on server."}), 500
        payload = request.get_json() or {}
        email = (payload.get('email') or '').strip().lower()
        password = payload.get('password') or ''
        if not email or not password:
            return jsonify({'error': 'email and password required'}), 400
        q = supabase.table('users').select('id').eq('email', email).execute()
        if q.data and len(q.data):
            return jsonify({'error': 'user already exists'}), 400
        pwd_hash = generate_password_hash(password)
        ins = supabase.table('users').insert({'email': email, 'password_hash': pwd_hash}).execute()
        if hasattr(ins, 'error') and ins.error:
            return jsonify({'error': str(ins.error)}), 500
        user = ins.data[0]
        session['user_id'] = user.get('id') or user.get('email')
        return jsonify({'data': {'user_id': session['user_id'], 'email': email}}), 200
    except Exception:
        logging.exception('Unhandled exception in /api/register')
        return jsonify({'error': 'internal server error'}), 500


@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        if not supabase:
            return jsonify({"error": "Supabase not configured on server."}), 500
        payload = request.get_json() or {}
        email = (payload.get('email') or '').strip().lower()
        password = payload.get('password') or ''
        if not email or not password:
            return jsonify({'error': 'email and password required'}), 400
        q = supabase.table('users').select('*').eq('email', email).execute()
        if not q.data or not len(q.data):
            return jsonify({'error': 'invalid credentials'}), 400
        user = q.data[0]
        if not check_password_hash(user.get('password_hash', ''), password):
            return jsonify({'error': 'invalid credentials'}), 400
        session['user_id'] = user.get('id') or user.get('email')
        return jsonify({'data': {'user_id': session['user_id'], 'email': user.get('email')}}), 200
    except Exception:
        logging.exception('Unhandled exception in /api/login')
        return jsonify({'error': 'internal server error'}), 500


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('user_id', None)
    return jsonify({'data': 'ok'}), 200


@app.route('/api/me', methods=['GET'])
def api_me():
    try:
        uid = session.get('user_id')
        if not uid:
            return jsonify({'error': 'not authenticated'}), 401
        if supabase:
            q = supabase.table('users').select('id,email,created_at').eq('id', uid).execute()
            if q.data and len(q.data):
                return jsonify({'data': q.data[0]}), 200
        return jsonify({'data': {'id': uid}}), 200
    except Exception:
        logging.exception('Unhandled exception in /api/me')
        return jsonify({'error': 'internal server error'}), 500


if __name__ == "__main__":
    app.run(debug=True)
