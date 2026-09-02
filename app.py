"""Streamlit prototype: participant reviews an IDS table, chats with a dummy LLM
teammate, and submits a scenario judgment. Flow: consent -> trial -> done."""
from datetime import datetime

import pandas as pd
import streamlit as st

from utils import (
    load_settings,
    load_trial,
    get_dummy_llm_reply,
    save_answers_csv,
    save_chat_csv,
)

st.set_page_config(page_title="IDS Evaluation Task", layout="wide")

settings = load_settings()
trial = load_trial(settings["trial_order"][0])

if "page" not in st.session_state:
    st.session_state.page = "consent"
    st.session_state.participant_id = ""
    st.session_state.chat_history = []
    st.session_state.timestamp_start = None


def now():
    return datetime.now().isoformat(timespec="seconds")


def format_initial_assessment(assessment):
    return (
        f"**Initial assessment**\n\n"
        f"- Ongoing attack detected: {'Yes' if assessment['attack_detected'] else 'No'}\n"
        f"- Suspected attack type: {assessment['attack_type']}\n"
        f"- Confidence: {assessment['confidence']}/100\n\n"
        f"{assessment['explanation']}"
    )


# ---------------------------------------------------------------- consent page
if st.session_state.page == "consent":
    st.title(settings["experiment_name"])
    st.header("Consent & Participant ID")

    participant_id = st.text_input("Please enter your participant ID:")
    consent_given = st.checkbox("I have read the study information and consent to participate.")

    if st.button("Continue"):
        if not participant_id.strip():
            st.error("Please enter a participant ID.")
        elif not consent_given:
            st.error("You must consent to participate before continuing.")
        else:
            st.session_state.participant_id = participant_id.strip()
            st.session_state.timestamp_start = now()
            st.session_state.chat_history = [
                {
                    "role": "llm",
                    "message": format_initial_assessment(trial["llm_initial_assessment"]),
                    "timestamp": now(),
                }
            ]
            st.session_state.page = "trial"
            st.rerun()

# ------------------------------------------------------------------ trial page
elif st.session_state.page == "trial":
    st.title(settings["experiment_name"])
    st.subheader("Network Event Log (IDS Output)")
    st.dataframe(pd.DataFrame(trial["ids_events"]), use_container_width=True)

    st.subheader("LLM Teammate Chat")
    for msg in st.session_state.chat_history:
        role = "assistant" if msg["role"] == "llm" else "user"
        with st.chat_message(role):
            st.markdown(msg["message"])

    user_message = st.chat_input("Ask your LLM teammate a question...")
    if user_message:
        st.session_state.chat_history.append(
            {"role": "human", "message": user_message, "timestamp": now()}
        )
        reply = get_dummy_llm_reply(trial, user_message)
        st.session_state.chat_history.append(
            {"role": "llm", "message": reply, "timestamp": now()}
        )
        st.rerun()

    st.subheader("Your Assessment")
    attack_detected = st.radio("Is there an ongoing cyberattack?", ["Yes", "No"], index=None)
    attack_type = ""
    if attack_detected == "Yes":
        attack_type = st.text_input("If yes, what type of attack?")
    confidence = st.slider("How confident are you?", 1, 100, 50)

    if st.button("Submit"):
        if attack_detected is None:
            st.error("Please answer whether there is an ongoing cyberattack.")
        elif attack_detected == "Yes" and not attack_type.strip():
            st.error("Please describe the suspected attack type.")
        else:
            record = {
                "participant_id": st.session_state.participant_id,
                "trial_number": trial["trial_number"],
                "condition": settings["condition"],
                "timestamp_start": st.session_state.timestamp_start,
                "timestamp_submit": now(),
                "attack_detected": attack_detected,
                "attack_type": attack_type.strip(),
                "confidence": confidence,
            }
            answers_path = save_answers_csv(
                st.session_state.participant_id, trial["trial_number"], record
            )
            chat_path = save_chat_csv(
                st.session_state.participant_id, trial["trial_number"], st.session_state.chat_history
            )
            st.session_state.answers_path = answers_path
            st.session_state.chat_path = chat_path
            st.session_state.page = "done"
            st.rerun()

# ------------------------------------------------------------------- done page
elif st.session_state.page == "done":
    st.title(settings["experiment_name"])
    st.success("Trial completed. Your responses have been saved.")
    st.write(f"Answers saved to: `{st.session_state.answers_path}`")
    st.write(f"Chat log saved to: `{st.session_state.chat_path}`")
