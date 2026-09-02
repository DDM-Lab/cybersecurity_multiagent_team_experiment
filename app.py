"""Streamlit prototype: participant reviews an IDS table and gives an independent
judgment, then discusses with a dummy LLM teammate before finalizing.
Flow: consent -> trial_initial -> trial_discuss -> done."""
from datetime import datetime

import pandas as pd
import streamlit as st

from decision import (
    aggregate_decision,
    calculate_team_performance,
    round_probability_to_decision,
)
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
attack_type_options = settings["attack_type_options"]

if "page" not in st.session_state:
    st.session_state.page = "consent"
    st.session_state.participant_id = ""
    st.session_state.condition = None
    st.session_state.chat_history = []
    st.session_state.timestamp_start = None
    st.session_state.timestamp_pre_submit = None
    st.session_state.pre_answers = None
    st.session_state.submission_summary = None


def now():
    return datetime.now().isoformat(timespec="seconds")


def match_color(is_match):
    return "#2e7d32" if is_match else "#c62828"  # green if match, red if different


def colored_line(text, is_match):
    return f'<span style="color:{match_color(is_match)};font-weight:bold;">{text}</span>'


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
            st.session_state.chat_history = []
            st.session_state.page = "trial_initial"
            st.rerun()

# --------------------------------------------------------- trial: initial page
elif st.session_state.page == "trial_initial":
    st.title(settings["experiment_name"])
    st.subheader("Network Event Log (IDS Output)")
    st.dataframe(pd.DataFrame(trial["ids_events"]), use_container_width=True)

    st.subheader("Your Independent Assessment")
    st.caption("Please form your own judgment before seeing your AI teammate's assessment.")
    attack_probability = st.slider(
        "What is the probability that there is an ongoing cyberattack?",
        1, 100, 50, key="initial_attack_probability",
    )
    attack_type = st.selectbox(
        "What type of attack do you suspect?",
        attack_type_options,
        index=None,
        placeholder="Select an attack type...",
        key="initial_attack_type",
    )
    confidence = st.slider("How confident are you?", 1, 100, 50, key="initial_confidence")

    if st.button("Submit Initial Assessment"):
        if attack_type is None:
            st.error("Please select a suspected attack type.")
        else:
            st.session_state.pre_answers = {
                "attack_probability": attack_probability,
                "attack_type": attack_type,
                "confidence": confidence,
            }
            st.session_state.timestamp_pre_submit = now()
            st.session_state.page = "trial_discuss"
            st.rerun()

# -------------------------------------------------------- trial: discuss page
elif st.session_state.page == "trial_discuss":
    st.title(settings["experiment_name"])
    st.subheader("Network Event Log (IDS Output)")
    st.dataframe(pd.DataFrame(trial["ids_events"]), use_container_width=True)

    pre = st.session_state.pre_answers
    llm_assessment = trial["llm_initial_assessment"]
    human_decision_pre = round_probability_to_decision(pre["attack_probability"])
    llm_decision_pre = round_probability_to_decision(llm_assessment["attack_probability"])

    decision_match = human_decision_pre == llm_decision_pre
    type_match = pre["attack_type"] == llm_assessment["attack_type"]
    confidence_match = pre["confidence"] == llm_assessment["confidence"]

    st.subheader("Compare Assessments")
    human_column, llm_column = st.columns(2, gap="large")

    with human_column:
        st.markdown(
            f"""
<div style="background-color:#eaf7ea;border:1px solid #2e7d32;border-radius:8px;padding:14px;">
<b>Your Initial Assessment</b><br>
{colored_line(f"Attack probability: {pre['attack_probability']}/100", decision_match)}<br>
{colored_line(f"Suspected attack type: {pre['attack_type']}", type_match)}<br>
{colored_line(f"Confidence: {pre['confidence']}/100", confidence_match)}
</div>
""",
            unsafe_allow_html=True,
        )

    with llm_column:
        st.markdown(
            f"""
<div style="background-color:#e8f0fe;border:1px solid #1a73e8;border-radius:8px;padding:14px;">
<b>LLM Teammate Assessment</b><br>
{colored_line(f"Attack probability: {llm_assessment['attack_probability']}/100", decision_match)}<br>
{colored_line(f"Suspected attack type: {llm_assessment['attack_type']}", type_match)}<br>
{colored_line(f"Confidence: {llm_assessment['confidence']}/100", confidence_match)}<br>
{llm_assessment['explanation']}
</div>
""",
            unsafe_allow_html=True,
        )

    st.subheader("Discuss With Your LLM Teammate")
    # Nesting inside a column (rather than at page root) keeps chat_input statically
    # placed right below the message box instead of pinned to the viewport bottom.
    chat_col = st.columns(1)[0]
    with chat_col:
        with st.container(height=350):
            for msg in st.session_state.chat_history:
                role = "assistant" if msg["role"] == "llm" else "user"
                author = "LLM Teammate" if msg["role"] == "llm" else "You"
                with st.chat_message(role):
                    st.caption(f"{author} | {msg['timestamp']}")
                    st.markdown(msg["message"])

        user_message = st.chat_input("Discuss your assessments with your LLM teammate...")
    if user_message:
        st.session_state.chat_history.append(
            {"role": "human", "message": user_message, "timestamp": now()}
        )
        reply = get_dummy_llm_reply(trial, user_message)
        st.session_state.chat_history.append(
            {"role": "llm", "message": reply, "timestamp": now()}
        )
        st.rerun()

    st.subheader("Finalize Your Assessment")
    st.caption("Feel free to revise your answers after discussing with your AI teammate.")
    attack_probability_post = st.slider(
        "What is the probability that there is an ongoing cyberattack?",
        1, 100, pre["attack_probability"], key="post_attack_probability",
    )
    attack_type_post = st.selectbox(
        "What type of attack do you suspect?",
        attack_type_options,
        index=attack_type_options.index(pre["attack_type"]),
        key="post_attack_type",
    )
    confidence_post = st.slider(
        "How confident are you?", 1, 100, pre["confidence"], key="post_confidence"
    )

    if st.button("Submit Final Assessment"):
        human_decision_post = round_probability_to_decision(attack_probability_post)

        llm_attack_probability_pre = llm_assessment["attack_probability"]
        llm_attack_type_pre = llm_assessment["attack_type"]
        llm_confidence_pre = llm_assessment["confidence"]
        # Dummy LLM teammate does not update its assessment after chat (no real LLM yet).
        llm_attack_probability_post = llm_attack_probability_pre
        llm_attack_type_post = llm_attack_type_pre
        llm_confidence_post = llm_confidence_pre
        llm_decision_post = round_probability_to_decision(llm_attack_probability_post)

        correct_attack_detected = trial.get("attack_detected_correct_response", "Yes")
        correct_attack_type = trial.get("attack_type_correct_response", "")

        # Decision calculation based on condition, using final (post-chat) answers
        agg_result = aggregate_decision(
            condition=st.session_state.condition,
            human_decision=human_decision_post,
            human_confidence=confidence_post,
            llm_decision=llm_decision_post,
            llm_confidence=llm_confidence_post,
        )
        team_decision = agg_result["team_decision"]
        team_perf = calculate_team_performance(team_decision, correct_attack_detected)

        record = {
            "participant_id": st.session_state.participant_id,
            "trial_number": trial["trial_number"],
            "condition": st.session_state.condition,
            "timestamp_start": st.session_state.timestamp_start,
            "timestamp_pre_submit": st.session_state.timestamp_pre_submit,
            "timestamp_post_submit": now(),
            "human_attack_probability_pre": pre["attack_probability"],
            "human_attack_probability_post": attack_probability_post,
            "human_attack_probability_changed": pre["attack_probability"] != attack_probability_post,
            "human_attack_type_pre": pre["attack_type"],
            "human_attack_type_post": attack_type_post,
            "human_attack_type_changed": pre["attack_type"] != attack_type_post,
            "human_confidence_pre": pre["confidence"],
            "human_confidence_post": confidence_post,
            "human_confidence_changed": pre["confidence"] != confidence_post,
            "human_attack_detected_pre": human_decision_pre,
            "human_attack_detected_post": human_decision_post,
            "llm_attack_probability_pre": llm_attack_probability_pre,
            "llm_attack_probability_post": llm_attack_probability_post,
            "llm_attack_probability_changed": llm_attack_probability_pre != llm_attack_probability_post,
            "llm_attack_type_pre": llm_attack_type_pre,
            "llm_attack_type_post": llm_attack_type_post,
            "llm_attack_type_changed": llm_attack_type_pre != llm_attack_type_post,
            "llm_confidence_pre": llm_confidence_pre,
            "llm_confidence_post": llm_confidence_post,
            "llm_confidence_changed": llm_confidence_pre != llm_confidence_post,
            "llm_attack_detected_pre": llm_decision_pre,
            "llm_attack_detected_post": llm_decision_post,
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
            "human_decision": human_decision_post,
            "human_confidence": confidence_post,
            "llm_decision": llm_decision_post,
            "llm_confidence": llm_confidence_post,
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
