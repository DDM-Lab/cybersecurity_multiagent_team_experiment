"""Helper functions for config loading, dummy LLM replies, and CSV persistence."""
import csv
import json
import os

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_settings():
    return load_json(os.path.join(CONFIG_DIR, "settings.json"))


def load_trial(trial_id):
    return load_json(os.path.join(CONFIG_DIR, f"{trial_id}.json"))


def get_dummy_llm_reply(trial_config, user_message):
    # Placeholder for a future real LLM API call; signature already accepts the user message.
    return trial_config["llm_dummy_reply"]


def ensure_participant_dir(participant_id):
    participant_dir = os.path.join(DATA_DIR, participant_id)
    os.makedirs(participant_dir, exist_ok=True)
    return participant_dir


def save_answers_csv(participant_id, trial_number, record):
    participant_dir = ensure_participant_dir(participant_id)
    path = os.path.join(participant_dir, f"trial_{trial_number}_answers.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(record.keys()))
        writer.writeheader()
        writer.writerow(record)
    return path


def save_chat_csv(participant_id, trial_number, chat_history):
    participant_dir = ensure_participant_dir(participant_id)
    path = os.path.join(participant_dir, f"trial_{trial_number}_chat.csv")
    fieldnames = ["participant_id", "trial_number", "message_index", "role", "message", "timestamp"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, msg in enumerate(chat_history):
            writer.writerow({
                "participant_id": participant_id,
                "trial_number": trial_number,
                "message_index": i,
                "role": msg["role"],
                "message": msg["message"],
                "timestamp": msg["timestamp"],
            })
    return path
