import os
import logging
from flask import Flask, render_template, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client

app = Flask(__name__, template_folder="templates")
# secret for Flask session cookies; set SECRET_KEY in production
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret')

# Configure Supabase client using environment variables
# Set SUPABASE_URL and SUPABASE_SERVICE_KEY (service_role) in your host environment
SUPABASE_URL = os.environ.get("SUPABASE_URL")
# prefer the secure service role key on the server; fall back to SUPABASE_KEY if set
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None


@app.route("/")
def home():
    # Always show personal website
    return render_template('landing.html')


@app.route('/login')
def login_page():
    # If already logged in go straight to planner
    if session.get('user_id'):
        from flask import redirect, url_for
        return redirect('/planner')
    return render_template('login.html')


@app.route('/app')
@app.route('/planner')
def app_page():
    # Planner — redirect to login if not authenticated
    if not session.get('user_id'):
        from flask import redirect
        return redirect('/login')
    return render_template('index.html')


@app.route("/api/save", methods=["POST"])
def api_save():
    logging.info("/api/save called from %s", request.remote_addr)
    try:
        if not supabase:
            logging.warning("Supabase client not configured when /api/save called")
            return jsonify({"error": "Supabase not configured on server."}), 500
        payload = request.get_json() or {}
        # expected payload: { name: string, data: object }
        # use logged-in session user_id when available
        name = payload.get("name", "plan")
        data = payload.get("data", {})
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "authentication required"}), 401
        row = {"name": name, "data": data, "user_id": user_id}
        res = supabase.table("plans").insert(row).execute()
        if hasattr(res, 'error') and res.error:
            logging.error("Supabase insert error: %s", res.error)
            return jsonify({"error": str(res.error)}), 500
        return jsonify({"data": res.data}), 200
    except Exception:
        logging.exception("Unhandled exception in /api/save")
        return jsonify({"error": "internal server error"}), 500


@app.route("/api/plans", methods=["GET"])
def api_plans():
    logging.info("/api/plans called from %s", request.remote_addr)
    try:
        if not supabase:
            logging.warning("Supabase client not configured when /api/plans called")
            return jsonify({"error": "Supabase not configured on server."}), 500
        # require authenticated user and return their plans only
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"error": "authentication required"}), 401
        query = supabase.table("plans").select("*").eq("user_id", user_id)
        # supabase-py order() expects a column and a desc flag (desc=True for newest first)
        res = query.order("created_at", desc=True).execute()
        if hasattr(res, 'error') and res.error:
            logging.error("Supabase select error: %s", res.error)
            return jsonify({"error": str(res.error)}), 500
        return jsonify({"data": res.data}), 200
    except Exception:
        logging.exception("Unhandled exception in /api/plans")
        return jsonify({"error": "internal server error"}), 500


@app.route("/health", methods=["GET"])
def health():
    """Simple health endpoint that reports whether Supabase env vars were read.
    Use this to verify the deployed service can see `SUPABASE_URL` and a key.
    """
    configured = bool(SUPABASE_URL and SUPABASE_KEY)
    # don't return keys — only indicate presence
    return jsonify({
        "supabase_configured": configured,
        "supabase_url": SUPABASE_URL or None
    }), 200


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
        # check existing
        q = supabase.table('users').select('id').eq('email', email).execute()
        if q.data and len(q.data):
            return jsonify({'error': 'user already exists'}), 400
        pwd_hash = generate_password_hash(password)
        ins = supabase.table('users').insert({'email': email, 'password_hash': pwd_hash}).execute()
        if hasattr(ins, 'error') and ins.error:
            logging.error('Supabase insert user error: %s', ins.error)
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
        pwd_hash = user.get('password_hash')
        if not pwd_hash or not check_password_hash(pwd_hash, password):
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
        q = supabase.table('users').select('id,email,created_at').eq('id', uid).execute()
        if q.data and len(q.data):
            return jsonify({'data': q.data[0]}), 200
        # fallback: return minimal id
        return jsonify({'data': {'id': uid}}), 200
    except Exception:
        logging.exception('Unhandled exception in /api/me')
        return jsonify({'error': 'internal server error'}), 500


if __name__ == "__main__":
    # during local development you can set these env vars or use a .env loader
    app.run(debug=True)
