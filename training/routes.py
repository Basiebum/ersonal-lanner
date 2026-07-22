import os
from datetime import date, timedelta
from functools import wraps

from flask import (
    render_template, request, redirect, url_for, jsonify, flash, session
)

from . import training_bp
from . import strava as strava_client
from supabase_client import supabase

STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
STRAVA_REDIRECT_URI = os.environ.get("STRAVA_REDIRECT_URI")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper


def get_week_bounds(d: date):
    start = d - timedelta(days=d.weekday())  # Monday
    end = start + timedelta(days=6)
    return start, end


def _fetch_range(table, user_id, start, end, parse_dates=True):
    res = (
        supabase.table(table)
        .select("*")
        .eq("user_id", user_id)
        .gte("date", start.isoformat())
        .lte("date", end.isoformat())
        .order("date")
        .execute()
    )
    rows = res.data
    if parse_dates:
        for row in rows:
            if isinstance(row.get("date"), str):
                row["date"] = date.fromisoformat(row["date"])
    return rows


@training_bp.route("/")
@login_required
def dashboard():
    user_id = session["user_id"]
    today = date.today()
    offset = int(request.args.get("offset", 0))
    ref_day = today + timedelta(weeks=offset)
    week_start, week_end = get_week_bounds(ref_day)

    planned = _fetch_range("planned_workouts", user_id, week_start, week_end)
    activities = _fetch_range("activities", user_id, week_start, week_end)

    planned_km = sum(w.get("planned_distance_km") or 0 for w in planned)
    actual_km = sum(a.get("distance_km") or 0 for a in activities)
    planned_min = sum(w.get("planned_duration_min") or 0 for w in planned)
    actual_min = sum(a.get("duration_min") or 0 for a in activities)

    # trend: fetch last 12 weeks of activities in one query, group in Python
    trend_start, _ = get_week_bounds(today - timedelta(weeks=11))
    _, trend_end = get_week_bounds(today)
    wide_activities = _fetch_range("activities", user_id, trend_start, trend_end)

    trend_weeks = []
    for i in range(11, -1, -1):
        ws, we = get_week_bounds(today - timedelta(weeks=i))
        acts = [a for a in wide_activities if ws <= a["date"] <= we]
        trend_weeks.append({
            "label": ws.strftime("%b %d"),
            "distance_km": round(sum(a.get("distance_km") or 0 for a in acts), 1),
            "duration_min": round(sum(a.get("duration_min") or 0 for a in acts), 1),
        })

    token_res = supabase.table("strava_tokens").select("id").eq("user_id", user_id).execute()
    strava_connected = bool(token_res.data)

    return render_template(
        "training/dashboard.html",
        planned=planned,
        activities=activities,
        week_start=week_start,
        week_end=week_end,
        offset=offset,
        planned_km=round(planned_km, 1),
        actual_km=round(actual_km, 1),
        planned_min=round(planned_min, 1),
        actual_min=round(actual_min, 1),
        trend_weeks=trend_weeks,
        strava_connected=strava_connected,
    )


@training_bp.route("/plan")
@login_required
def plan():
    user_id = session["user_id"]
    today = date.today()
    offset = int(request.args.get("offset", 0))
    ref_day = today + timedelta(weeks=offset)
    week_start, week_end = get_week_bounds(ref_day)

    workouts = _fetch_range("planned_workouts", user_id, week_start, week_end)

    return render_template(
        "training/plan.html",
        workouts=workouts,
        week_start=week_start,
        week_end=week_end,
        offset=offset,
    )


@training_bp.route("/plan/add", methods=["POST"])
@login_required
def plan_add():
    user_id = session["user_id"]
    row = {
        "user_id": user_id,
        "date": request.form["date"],
        "sport": request.form.get("sport", "run"),
        "title": request.form.get("title", "Workout"),
        "description": request.form.get("description", ""),
        "planned_distance_km": float(request.form["planned_distance_km"]) if request.form.get("planned_distance_km") else None,
        "planned_duration_min": int(request.form["planned_duration_min"]) if request.form.get("planned_duration_min") else None,
        "intensity": request.form.get("intensity", ""),
        "notes": request.form.get("notes", ""),
    }
    supabase.table("planned_workouts").insert(row).execute()
    return redirect(url_for("training.plan"))


@training_bp.route("/plan/<int:workout_id>/delete", methods=["POST"])
@login_required
def plan_delete(workout_id):
    user_id = session["user_id"]
    supabase.table("planned_workouts").delete().eq("id", workout_id).eq("user_id", user_id).execute()
    return redirect(url_for("training.plan"))


@training_bp.route("/plan/<int:workout_id>/toggle", methods=["POST"])
@login_required
def plan_toggle(workout_id):
    user_id = session["user_id"]
    res = supabase.table("planned_workouts").select("completed").eq("id", workout_id).eq("user_id", user_id).execute()
    if res.data:
        current = res.data[0].get("completed", False)
        supabase.table("planned_workouts").update({"completed": not current}).eq("id", workout_id).eq("user_id", user_id).execute()
    return redirect(url_for("training.plan"))


@training_bp.route("/strava/connect")
@login_required
def strava_connect():
    url = strava_client.build_authorize_url(STRAVA_CLIENT_ID, STRAVA_REDIRECT_URI)
    return redirect(url)


@training_bp.route("/strava/callback")
@login_required
def strava_callback():
    user_id = session["user_id"]
    code = request.args.get("code")
    if not code:
        flash("Strava authorization was cancelled or failed.", "error")
        return redirect(url_for("training.dashboard"))

    data = strava_client.exchange_code_for_token(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, code)
    strava_client.save_token(supabase, user_id, data)

    flash("Strava connected.", "success")
    return redirect(url_for("training.dashboard"))


@training_bp.route("/strava/sync", methods=["POST"])
@login_required
def strava_sync():
    user_id = session["user_id"]
    try:
        count = strava_client.sync_recent_activities(
            supabase, user_id, STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET
        )
        flash(f"Synced {count} activities from Strava.", "success")
    except Exception as e:
        flash(f"Strava sync failed: {e}", "error")
    return redirect(url_for("training.dashboard"))


@training_bp.route("/api/trend")
@login_required
def api_trend():
    user_id = session["user_id"]
    today = date.today()
    trend_start, _ = get_week_bounds(today - timedelta(weeks=11))
    _, trend_end = get_week_bounds(today)
    wide_activities = _fetch_range("activities", user_id, trend_start, trend_end)

    weeks = []
    for i in range(11, -1, -1):
        ws, we = get_week_bounds(today - timedelta(weeks=i))
        acts = [a for a in wide_activities if ws <= a["date"] <= we]
        weeks.append({
            "label": ws.strftime("%b %d"),
            "distance_km": round(sum(a.get("distance_km") or 0 for a in acts), 1),
            "duration_min": round(sum(a.get("duration_min") or 0 for a in acts), 1),
        })
    return jsonify(weeks)
