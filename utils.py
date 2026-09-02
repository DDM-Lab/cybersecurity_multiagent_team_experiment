"""Helper functions for config loading, dummy LLM replies, and CSV persistence."""
import csv
import json
import os

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TRACKER_FILE = os.path.join(DATA_DIR, "assignment_tracker.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_settings():
    return load_json(os.path.join(CONFIG_DIR, "settings.json"))


def load_trial(trial_id):
    return load_json(os.path.join(CONFIG_DIR, f"{trial_id}.json"))


def get_next_condition():
    """Determine the condition for the next incoming participant.

    Alternates between 'leader' and 'pool' based on the recorded count in
    data/assignment_tracker.json.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    tracker = {"total_participants": 0, "last_condition": None}
    if os.path.exists(TRACKER_FILE):
        try:
            tracker = load_json(TRACKER_FILE)
        except Exception:
            pass

    last_condition = tracker.get("last_condition")
    next_condition = "pool" if last_condition == "leader" else "leader"
    tracker["last_condition"] = next_condition
    tracker["total_participants"] = tracker.get("total_participants", 0) + 1

    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(tracker, f, indent=2)

    return next_condition


def get_dummy_llm_reply(trial_config, user_message):
    # Placeholder for a future real LLM API call; signature already accepts the user message.
    return trial_config["llm_dummy_reply"]


def _read_existing_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_rows(path, fieldnames, rows):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_answers_csv(participant_id, trial_number, record):
    """Append/replace one trial's answer row in the participant's single answers CSV."""
    path = os.path.join(DATA_DIR, f"{participant_id}_answers.csv")
    fieldnames = list(record.keys())
    rows = [r for r in _read_existing_rows(path) if str(r.get("trial_number")) != str(trial_number)]
    rows.append(record)
    _write_rows(path, fieldnames, rows)
    return path


def save_chat_csv(participant_id, trial_number, chat_history):
    """Append/replace one trial's chat messages in the participant's single chat CSV."""
    path = os.path.join(DATA_DIR, f"{participant_id}_chat.csv")
    fieldnames = ["participant_id", "trial_number", "message_index", "role", "message", "timestamp"]
    rows = [r for r in _read_existing_rows(path) if str(r.get("trial_number")) != str(trial_number)]
    for i, msg in enumerate(chat_history):
        rows.append({
            "participant_id": participant_id,
            "trial_number": trial_number,
            "message_index": i,
            "role": msg["role"],
            "message": msg["message"],
            "timestamp": msg["timestamp"],
        })
    _write_rows(path, fieldnames, rows)
    return path
