import os
from flask import Flask, render_template, request, jsonify
from supabase import create_client

app = Flask(__name__, template_folder="templates")

# Configure Supabase client using environment variables
# Set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (service_role) in your host environment
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/save", methods=["POST"])
def api_save():
    if not supabase:
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
    if res.error:
        return jsonify({"error": str(res.error)}), 500
    return jsonify({"data": res.data}), 200


@app.route("/api/plans", methods=["GET"])
def api_plans():
    if not supabase:
        return jsonify({"error": "Supabase not configured on server."}), 500
    # optional ?user_id=... to filter
    user_id = request.args.get("user_id")
    query = supabase.table("plans").select("*")
    if user_id:
        query = query.eq("user_id", user_id)
    res = query.order("created_at", {"ascending": False}).execute()
    if res.error:
        return jsonify({"error": str(res.error)}), 500
    return jsonify({"data": res.data}), 200


if __name__ == "__main__":
    # during local development you can set these env vars or use a .env loader
    app.run(debug=True)