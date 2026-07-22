import json
from datetime import date

import anthropic

SYSTEM_PROMPT = """You are a training plan editor. You receive the user's current week's \
planned workouts (as JSON) and a natural-language instruction. You must respond with ONLY a \
JSON object (no prose, no markdown fences) describing the actions to apply, in this exact shape:

{
  "actions": [
    {"op": "create", "date": "YYYY-MM-DD", "sport": "run", "title": "...", \
"description": "...", "planned_distance_km": 10.0, "planned_duration_min": 60, \
"intensity": "easy", "notes": ""},
    {"op": "update", "id": 123, "fields": {"date": "YYYY-MM-DD", "title": "...", \
"planned_distance_km": 12.0}},
    {"op": "delete", "id": 123}
  ],
  "summary": "One sentence describing what you changed, for the user to read."
}

Rules:
- Only include fields that should change in "update" actions.
- sport must be one of: run, bike, swim, strength, walk, rest, other.
- intensity is a free short label like: easy, tempo, threshold, interval, long, race, recovery.
- If the instruction is ambiguous, make the most reasonable training-sense interpretation.
- Never invent workout ids that were not given to you.
"""


def apply_ai_edit(supabase, user_id, instruction, week_start, week_end, api_key):
    client = anthropic.Anthropic(api_key=api_key)

    res = (
        supabase.table("planned_workouts")
        .select("*")
        .eq("user_id", user_id)
        .gte("date", week_start.isoformat())
        .lte("date", week_end.isoformat())
        .order("date")
        .execute()
    )
    workouts = res.data

    context = {
        "today": date.today().isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "current_plan": workouts,
    }

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Current plan context:\n{json.dumps(context)}\n\nInstruction: {instruction}",
        }],
    )

    text = "".join(block.text for block in message.content if block.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    parsed = json.loads(text)
    actions = parsed.get("actions", [])
    summary = parsed.get("summary", "Plan updated.")

    for action in actions:
        op = action.get("op")
        if op == "create":
            row = {
                "user_id": user_id,
                "date": action["date"],
                "sport": action.get("sport", "run"),
                "title": action.get("title", "Workout"),
                "description": action.get("description", ""),
                "planned_distance_km": action.get("planned_distance_km"),
                "planned_duration_min": action.get("planned_duration_min"),
                "intensity": action.get("intensity", ""),
                "notes": action.get("notes", ""),
            }
            supabase.table("planned_workouts").insert(row).execute()
        elif op == "update":
            wid = action.get("id")
            fields = action.get("fields", {})
            if wid and fields:
                supabase.table("planned_workouts").update(fields).eq("id", wid).eq("user_id", user_id).execute()
        elif op == "delete":
            wid = action.get("id")
            if wid:
                supabase.table("planned_workouts").delete().eq("id", wid).eq("user_id", user_id).execute()

    return summary
