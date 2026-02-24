import os
import logging
from flask import Flask, render_template, request, jsonify
from supabase import create_client

app = Flask(__name__, template_folder="templates")

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
    return render_template("index.html")


@app.route("/api/save", methods=["POST"])
def api_save():
    logging.info("/api/save called from %s", request.remote_addr)
    try:
        if not supabase:
            logging.warning("Supabase client not configured when /api/save called")
            return jsonify({"error": "Supabase not configured on server."}), 500
        payload = request.get_json() or {}
        # expected payload: { name: string, data: object, user_id?: string }
        name = payload.get("name", "plan")
        data = payload.get("data", {})
        user_id = payload.get("user_id")
        row = {"name": name, "data": data}
        if user_id:
            row["user_id"] = user_id
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
        # optional ?user_id=... to filter
        user_id = request.args.get("user_id")
        query = supabase.table("plans").select("*")
        if user_id:
            query = query.eq("user_id", user_id)
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


if __name__ == "__main__":
    # during local development you can set these env vars or use a .env loader
    app.run(debug=True)
