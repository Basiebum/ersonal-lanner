import time
import json
import requests
from datetime import datetime

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"

SPORT_MAP = {
    "Run": "run",
    "TrailRun": "run",
    "Ride": "bike",
    "VirtualRide": "bike",
    "Swim": "swim",
    "WeightTraining": "strength",
    "Workout": "strength",
    "Walk": "walk",
    "Hike": "walk",
}


def build_authorize_url(client_id, redirect_uri):
    params = (
        f"client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&approval_prompt=auto"
        f"&scope=activity:read_all"
    )
    return f"{AUTH_URL}?{params}"


def exchange_code_for_token(client_id, client_secret, code):
    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    return resp.json()


def save_token(supabase, user_id, data):
    row = {
        "user_id": user_id,
        "athlete_id": data.get("athlete", {}).get("id"),
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": data["expires_at"],
    }
    # upsert on the unique user_id column
    supabase.table("strava_tokens").upsert(row, on_conflict="user_id").execute()


def get_valid_access_token(supabase, user_id, client_id, client_secret):
    res = supabase.table("strava_tokens").select("*").eq("user_id", user_id).execute()
    if not res.data:
        return None
    token = res.data[0]

    if token["expires_at"] - 60 < time.time():
        resp = requests.post(TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
        })
        resp.raise_for_status()
        data = resp.json()
        supabase.table("strava_tokens").update({
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": data["expires_at"],
        }).eq("user_id", user_id).execute()
        return data["access_token"]

    return token["access_token"]


def sync_recent_activities(supabase, user_id, client_id, client_secret, per_page=50):
    access_token = get_valid_access_token(supabase, user_id, client_id, client_secret)
    if not access_token:
        raise RuntimeError("Not connected to Strava yet.")

    resp = requests.get(
        ACTIVITIES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"per_page": per_page, "page": 1},
    )
    resp.raise_for_status()
    activities = resp.json()

    rows = []
    for a in activities:
        distance_km = round((a.get("distance") or 0) / 1000, 2)
        duration_min = round((a.get("moving_time") or 0) / 60, 1)
        avg_pace = round(duration_min / distance_km, 2) if distance_km > 0 else None
        date_str = a.get("start_date_local", "")[:10]
        if not date_str:
            continue

        rows.append({
            "user_id": user_id,
            "strava_id": a.get("id"),
            "date": date_str,
            "sport": SPORT_MAP.get(a.get("type", ""), "other"),
            "name": a.get("name", ""),
            "distance_km": distance_km,
            "duration_min": duration_min,
            "avg_hr": a.get("average_heartrate"),
            "max_hr": a.get("max_heartrate"),
            "avg_pace_min_km": avg_pace,
            "elevation_gain_m": a.get("total_elevation_gain"),
            "raw_json": json.dumps(a),
        })

    if rows:
        # upsert on the (user_id, strava_id) unique constraint
        supabase.table("activities").upsert(rows, on_conflict="user_id,strava_id").execute()

    return len(rows)
