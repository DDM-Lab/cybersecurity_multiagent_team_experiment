"""Helper functions for config loading and CSV persistence. LLM replies are in llm.py."""
import csv
import json
import os
import random

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LLM_CHAT_FIELDS = ["fidelity", "prompt_sha256", "seed", "status", "finish_reason",
                   "completion_tokens", "latency_seconds", "raw_message", "cut_text", "error"]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_settings():
    return load_json(os.path.join(CONFIG_DIR, "settings.json"))


def load_trial(trial_id):
    """Load only the unlabeled CSV for the assessment stages."""
    config = load_settings()["trials"][trial_id]
    path = os.path.join(os.path.dirname(__file__), "IDS_tables", config["csv"])
    with open(path, newline="", encoding="utf-8") as f:
        events = list(csv.DictReader(f))
    return {"trial_id": trial_id, "ids_events": events,
            "attack_detected_correct_response": "Yes" if config["attack_present"] else "No",
            "attack_type_correct_response": config["attack_type"]}


def load_labeled_table(trial_id):
    """Feedback only: never used while participants are making decisions."""
    filename = load_settings()["trials"][trial_id]["csv"].replace(".csv", "-labelled.csv")
    with open(os.path.join(os.path.dirname(__file__), "IDS_tables", filename),
              newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_next_condition():
    """Random between-subjects assignment, called once at consent."""
    return random.choice(["leader", "pool"])


def create_trial_plan(settings):
    """A random episode order. The AI teammate's assessments come from the model during
    each episode (llm.py), so nothing about them is planned here."""
    return random.sample(settings["trial_order"], len(settings["trial_order"]))


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
    # The columns after `timestamp` describe LLM replies and are blank on the
    # participant's own messages. `message` is what the participant saw, `raw_message`
    # the model's full answer, and `prompt_sha256` identifies the exact system prompt.
    fieldnames = ["participant_id", "trial_number", "message_index", "role", "message", "timestamp",
                  *LLM_CHAT_FIELDS]
    rows = [r for r in _read_existing_rows(path) if str(r.get("trial_number")) != str(trial_number)]
    for i, msg in enumerate(chat_history):
        rows.append({
            "participant_id": participant_id,
            "trial_number": trial_number,
            "message_index": i,
            "role": msg["role"],
            "message": msg["message"],
            "timestamp": msg["timestamp"],
            **{field: msg.get(field, "") for field in LLM_CHAT_FIELDS},
        })
    _write_rows(path, fieldnames, rows)
    return path
