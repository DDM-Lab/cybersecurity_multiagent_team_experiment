"""Streamlit prototype: participant reviews an IDS table, chats with a dummy LLM
teammate, and submits a scenario judgment. Flow: consent -> trial -> done."""
from datetime import datetime

import pandas as pd
import streamlit as st

from decision import aggregate_decision, calculate_team_performance
from utils import (
    get_dummy_llm_reply,
    get_next_condition,
    load_settings,
    load_trial,
    save_answers_csv,
    save_chat_csv,
)

st.set_page_config(page_title="IDS Evaluation Task", layout="wide")

settings = load_settings()
trial = load_trial(settings["trial_order"][0])

if "page" not in st.session_state:
    st.session_state.page = "consent"
    st.session_state.participant_id = ""
    st.session_state.condition = None
    st.session_state.chat_history = []
    st.session_state.timestamp_start = None
    st.session_state.submission_summary = None


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
            st.session_state.condition = get_next_condition()
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

    assessment_column, chat_column = st.columns(2, gap="large")

    with assessment_column:
        st.subheader("LLM Teammate Assessment")
        st.markdown(st.session_state.chat_history[0]["message"])

    with chat_column:
        st.subheader("LLM Teammate Chat")
        with st.container(height=450):
            for msg in st.session_state.chat_history[1:]:
                role = "assistant" if msg["role"] == "llm" else "user"
                author = "LLM Teammate" if msg["role"] == "llm" else "You"
                with st.chat_message(role):
                    st.caption(f"{author} | {msg['timestamp']}")
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
            llm_assessment = trial["llm_initial_assessment"]
            llm_attack_detected = "Yes" if llm_assessment["attack_detected"] else "No"
            llm_attack_type = llm_assessment.get("attack_type", "")
            llm_confidence = llm_assessment.get("confidence", 0)

            correct_attack_detected = trial.get("attack_detected_correct_response", "Yes")
            correct_attack_type = trial.get("attack_type_correct_response", "")

            # Decision calculation based on condition
            agg_result = aggregate_decision(
                condition=st.session_state.condition,
                human_decision=attack_detected,
                human_confidence=confidence,
                llm_decision=llm_attack_detected,
                llm_confidence=llm_confidence,
            )
            team_decision = agg_result["team_decision"]
            team_perf = calculate_team_performance(team_decision, correct_attack_detected)

            record = {
                "participant_id": st.session_state.participant_id,
                "trial_number": trial["trial_number"],
                "condition": st.session_state.condition,
                "timestamp_start": st.session_state.timestamp_start,
                "timestamp_submit": now(),
                "attack_detected": attack_detected,
                "attack_type": attack_type.strip(),
                "confidence": confidence,
                "attack_detected_llm_response": llm_attack_detected,
                "attack_type_llm_response": llm_attack_type,
                "confidence_llm": llm_confidence,
                "attack_detected_correct_response": correct_attack_detected,
                "attack_type_correct_response": correct_attack_type,
                "team_performance": team_perf,
            }
            answers_path = save_answers_csv(
                st.session_state.participant_id, trial["trial_number"], record
            )
            chat_path = save_chat_csv(
                st.session_state.participant_id, trial["trial_number"], st.session_state.chat_history
            )
            st.session_state.answers_path = answers_path
            st.session_state.chat_path = chat_path
            st.session_state.submission_summary = {
                "condition": st.session_state.condition,
                "human_decision": attack_detected,
                "human_confidence": confidence,
                "llm_decision": llm_attack_detected,
                "llm_confidence": llm_confidence,
                "team_decision": team_decision,
                "correct_decision": correct_attack_detected,
                "team_performance": team_perf,
                "chosen_source": agg_result["chosen_source"],
            }
            st.session_state.page = "done"
            st.rerun()

# ------------------------------------------------------------------- done page
elif st.session_state.page == "done":
    st.title(settings["experiment_name"])
    st.success("Trial completed. Your responses have been saved.")

    summary = st.session_state.get("submission_summary")
    if summary:
        st.subheader("Team Performance Feedback")
        score_text = "Correct" if summary["team_performance"] == 1 else "Incorrect"
        score_color = "green" if summary["team_performance"] == 1 else "red"

        if summary["condition"] == "leader":
            st.markdown(
                f"**Team Decision Mechanism:** As the team leader, your judgment determined the final team decision.\n\n"
                f"- **Your Decision:** Attack Detected = **{summary['human_decision']}**\n"
                f"- **Ground Truth:** Attack Detected = **{summary['correct_decision']}**\n"
                f"- **Final Team Performance Score:** :{score_color}[**{score_text} ({summary['team_performance']}/1)**]"
            )
        else:
            st.markdown(
                f"**Team Decision Mechanism:** The team decision was formed by jointly combining your judgment "
                f"and your AI teammate's judgment, weighted by each party's confidence rating.\n\n"
                f"- **Your Assessment:** Attack Detected = **{summary['human_decision']}** (Confidence: {summary['human_confidence']}%)\n"
                f"- **AI Teammate Assessment:** Attack Detected = **{summary['llm_decision']}** (Confidence: {summary['llm_confidence']}%)\n"
                f"- **Joint Team Decision:** Attack Detected = **{summary['team_decision']}**\n"
                f"- **Ground Truth:** Attack Detected = **{summary['correct_decision']}**\n"
                f"- **Final Team Performance Score:** :{score_color}[**{score_text} ({summary['team_performance']}/1)**]"
            )

    st.write(f"Answers saved to: `{st.session_state.answers_path}`")
    st.write(f"Chat log saved to: `{st.session_state.chat_path}`")
