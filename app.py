"""Streamlit prototype: participant reviews an IDS table and gives an independent
judgment, then discusses with a dummy LLM teammate before finalizing.
Flow: consent -> (trial_initial -> trial_discuss -> feedback) x 9 -> done."""
from datetime import datetime
import json
from html import escape

import pandas as pd
import streamlit as st

from decision import (
    aggregate_assessment,
    calculate_team_performance,
)
from utils import (
    create_trial_plan,
    load_labeled_table,
    get_dummy_llm_reply,
    get_next_condition,
    load_settings,
    load_trial,
    save_answers_csv,
    save_chat_csv,
)

st.set_page_config(page_title="IDS Evaluation Task", layout="wide")

settings = load_settings()
attack_type_options = settings["attack_type_options"]
ids_default_rows = settings["ids_table_default_rows"]
ids_rows_increment = settings["ids_table_rows_increment"]

if "page" not in st.session_state:
    st.session_state.update(
        page="consent", participant_id="", condition=None, trial_index=0,
        chat_history=[], timestamp_start=None, timestamp_pre_submit=None,
        pre_answers=None, submission_summary=None,
        ids_rows_visible=ids_default_rows, ids_rows_revealed=0,
    )

trial = None
if "trial_order" in st.session_state:
    trial_id = st.session_state.trial_order[st.session_state.trial_index]
    trial = load_trial(trial_id)
    trial["trial_number"] = st.session_state.trial_index + 1
    trial["llm_initial_assessment"] = st.session_state.llm_assessments[trial_id]
    ids_total_rows = len(trial["ids_events"])
    st.caption(f"Episode {trial['trial_number']} of {len(st.session_state.trial_order)}")


def now():
    return datetime.now().isoformat(timespec="seconds")


def match_color(is_match):
    return "#2e7d32" if is_match else "#c62828"  # green if match, red if different


def colored_line(text, is_match):
    return f'<span style="color:{match_color(is_match)};font-weight:bold;">{text}</span>'


def render_ids_table():
    visible_rows = st.session_state.ids_rows_visible
    st.caption(f"Showing {visible_rows} of {ids_total_rows} rows")
    st.dataframe(
        pd.DataFrame(trial["ids_events"][:visible_rows]),
        width="stretch", hide_index=True,
    )

    if visible_rows < ids_total_rows:
        rows_to_reveal = min(ids_rows_increment, ids_total_rows - visible_rows)
        if st.button(
            f"Show {rows_to_reveal} more rows",
            key="show_more_ids_rows",
        ):
            st.session_state.ids_rows_visible += rows_to_reveal
            st.session_state.ids_rows_revealed += 1
            st.rerun()


# ---------------------------------------------------------------- consent page
if st.session_state.page == "consent":
    st.title(settings["experiment_name"])
    st.header("Consent & Participant ID")

    participant_id = st.text_input("Please enter your participant ID:")
    consent_given = st.checkbox("I have read the study information and consent to participate.")

    if st.button("Continue"):
        if not participant_id.strip():
            st.error("Please enter a participant ID.")
        elif any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in participant_id.strip()):
            st.error("Use letters, numbers, underscores, or hyphens in your participant ID.")
        elif not consent_given:
            st.error("You must consent to participate before continuing.")
        else:
            st.session_state.participant_id = participant_id.strip()
            st.session_state.condition = get_next_condition()
            order, assessments = create_trial_plan(settings)
            st.session_state.trial_order = order
            st.session_state.llm_assessments = assessments
            st.session_state.timestamp_start = now()
            st.session_state.chat_history = []
            st.session_state.page = "trial_initial"
            st.rerun()

# --------------------------------------------------------- trial: initial page
elif st.session_state.page == "trial_initial":
    st.title(settings["experiment_name"])
    st.subheader("Network Event Log (IDS Output)")
    render_ids_table()

    st.subheader("Your Independent Assessment")
    st.caption("Please form your own judgment before seeing your AI teammate's assessment.")
    attack_detected = st.selectbox(
        "Is there an ongoing cyberattack?", ["Yes", "No"],
        index=None, key="initial_attack_detected",
    )
    detection_confidence = st.slider(
        "How confident are you about whether an attack is ongoing?", 1, 100, 50,
        key="initial_detection_confidence",
        help="1 = least confident; 100 = most confident.",
    )
    attack_type = "None"
    if attack_detected == "Yes":
        attack_type = st.selectbox(
            "What type of attack do you suspect?",
            [category for category in attack_type_options if category != "None"],
            index=None,
            placeholder="Select an attack type...",
            key="initial_attack_type",
        )

    category_confidence = detection_confidence
    if attack_detected == "Yes":
        category_confidence = st.slider(
            "How confident are you in the attack category?", 1, 100, 50,
            key="initial_category_confidence",
            help="1 = least confident; 100 = most confident.",
        )

    if st.button("Submit Initial Assessment"):
        if attack_type is None or attack_detected is None:
            st.error("Please answer both questions.")
        else:
            st.session_state.pre_answers = {
                "attack_detected": attack_detected,
                "attack_type": attack_type,
                "detection_confidence": detection_confidence,
                "category_confidence": category_confidence,
            }
            st.session_state.timestamp_pre_submit = now()
            st.session_state.page = "trial_discuss"
            st.rerun()

# -------------------------------------------------------- trial: discuss page
elif st.session_state.page == "trial_discuss":
    st.title(settings["experiment_name"])
    st.subheader("Network Event Log (IDS Output)")
    render_ids_table()

    pre = st.session_state.pre_answers
    llm_assessment = trial["llm_initial_assessment"]
    human_decision_pre = pre["attack_detected"]
    llm_decision_pre = llm_assessment["attack_detected"]

    decision_match = human_decision_pre == llm_decision_pre
    type_match = pre["attack_type"] == llm_assessment["attack_type"]
    confidence_match = pre["detection_confidence"] == llm_assessment["detection_confidence"]
    category_confidence_match = pre["category_confidence"] == llm_assessment["category_confidence"]

    st.subheader("Compare Assessments")
    human_column, llm_column = st.columns(2, gap="large")

    with human_column:
        st.markdown(
            f"""
<div style="background-color:#eaf7ea;border:1px solid #2e7d32;border-radius:8px;padding:14px;">
<b>Your Initial Assessment</b><br>
{colored_line(f"Ongoing attack: {pre['attack_detected']}", decision_match)}<br>
{colored_line(f"Suspected attack type: {pre['attack_type']}", type_match)}<br>
{colored_line(f"Detection confidence: {pre['detection_confidence']}/100", confidence_match)}<br>
{colored_line(f"Category confidence: {pre['category_confidence']}/100", category_confidence_match)}
</div>
""",
            unsafe_allow_html=True,
        )

    with llm_column:
        st.markdown(
            f"""
<div style="background-color:#e8f0fe;border:1px solid #1a73e8;border-radius:8px;padding:14px;">
<b>LLM Teammate Assessment</b><br>
{colored_line(f"Ongoing attack: {llm_assessment['attack_detected']}", decision_match)}<br>
{colored_line(f"Suspected attack type: {llm_assessment['attack_type']}", type_match)}<br>
{colored_line(f"Detection confidence: {llm_assessment['detection_confidence']}/100", confidence_match)}<br>
{colored_line(f"Category confidence: {llm_assessment['category_confidence']}/100", category_confidence_match)}<br>
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
    attack_detected_post = st.selectbox(
        "Is there an ongoing cyberattack?", ["Yes", "No"],
        index=["Yes", "No"].index(pre["attack_detected"]), key="post_attack_detected",
    )
    detection_confidence_post = st.slider(
        "How confident are you about whether an attack is ongoing?", 1, 100, pre["detection_confidence"], key="post_detection_confidence",
        help="1 = least confident; 100 = most confident.",
    )
    attack_type_post = "None"
    if attack_detected_post == "Yes":
        categories = [category for category in attack_type_options if category != "None"]
        attack_type_post = st.selectbox(
            "What type of attack do you suspect?",
            categories,
            index=categories.index(pre["attack_type"]) if pre["attack_type"] in categories else None,
            placeholder="Select an attack type...",
            key="post_attack_type",
        )

    category_confidence_post = detection_confidence_post
    if attack_detected_post == "Yes":
        category_confidence_post = st.slider(
            "How confident are you in the attack category?", 1, 100, pre["category_confidence"],
            key="post_category_confidence",
            help="1 = least confident; 100 = most confident.",
        )

    if st.button("Submit Final Assessment"):
        if attack_type_post is None:
            st.error("Please select a suspected attack type.")
            st.stop()
        human_decision_post = attack_detected_post

        llm_attack_type_pre = llm_assessment["attack_type"]
        llm_detection_confidence_pre = llm_assessment["detection_confidence"]
        # Dummy LLM teammate does not update its assessment after chat (no real LLM yet).
        llm_attack_type_post = llm_attack_type_pre
        llm_detection_confidence_post = llm_detection_confidence_pre
        llm_decision_post = llm_decision_pre

        correct_attack_detected = trial.get("attack_detected_correct_response", "Yes")
        correct_attack_type = trial.get("attack_type_correct_response", "")

        # Decision calculation based on condition, using final (post-chat) answers
        agg_result = aggregate_assessment(
            condition=st.session_state.condition,
            human_decision=human_decision_post,
            human_category=attack_type_post,
            human_detection_confidence=detection_confidence_post,
            human_category_confidence=category_confidence_post,
            llm_decision=llm_decision_post,
            llm_category=llm_attack_type_post,
            llm_detection_confidence=llm_detection_confidence_post,
            llm_category_confidence=llm_assessment["category_confidence"],
        )
        team_decision = agg_result["team_decision"]
        team_perf = calculate_team_performance(team_decision, correct_attack_detected)

        record = {
            "participant_id": st.session_state.participant_id,
            "trial_number": trial["trial_number"],
            "trial_id": trial["trial_id"],
            "trial_order": ",".join(st.session_state.trial_order),
            "condition": st.session_state.condition,
            "timestamp_start": st.session_state.timestamp_start,
            "timestamp_pre_submit": st.session_state.timestamp_pre_submit,
            "timestamp_post_submit": now(),
            "human_attack_type_pre": pre["attack_type"],
            "human_attack_type_post": attack_type_post,
            "human_attack_type_changed": pre["attack_type"] != attack_type_post,
            "human_detection_confidence_pre": pre["detection_confidence"],
            "human_detection_confidence_post": detection_confidence_post,
            "human_detection_confidence_changed": pre["detection_confidence"] != detection_confidence_post,
            "human_category_confidence_pre": pre["category_confidence"],
            "human_category_confidence_post": category_confidence_post,
            "human_category_confidence_changed": pre["category_confidence"] != category_confidence_post,
            "human_category_confidence_inferred_pre": human_decision_pre == "No",
            "human_category_confidence_inferred_post": human_decision_post == "No",
            "human_attack_detected_pre": human_decision_pre,
            "human_attack_detected_post": human_decision_post,
            "human_attack_detected_changed": human_decision_pre != human_decision_post,
            "llm_attack_type_pre": llm_attack_type_pre,
            "llm_attack_type_post": llm_attack_type_post,
            "llm_attack_type_changed": llm_attack_type_pre != llm_attack_type_post,
            "llm_detection_confidence_pre": llm_detection_confidence_pre,
            "llm_detection_confidence_post": llm_detection_confidence_post,
            "llm_detection_confidence_changed": llm_detection_confidence_pre != llm_detection_confidence_post,
            "llm_category_confidence_pre": llm_assessment["category_confidence"],
            "llm_category_confidence_post": llm_assessment["category_confidence"],
            "llm_category_confidence_changed": False,
            "llm_attack_detected_pre": llm_decision_pre,
            "llm_attack_detected_post": llm_decision_post,
            "llm_attack_detected_changed": llm_decision_pre != llm_decision_post,
            "attack_detected_correct_response": correct_attack_detected,
            "attack_type_correct_response": correct_attack_type,
            "ids_rows_visible": st.session_state.ids_rows_visible,
            "ids_rows_revealed": st.session_state.ids_rows_revealed,
            "team_performance": team_perf,
        }
        for source in ("human", "llm"):
            for stage in ("pre", "post"):
                record[f"{source}_attack_detection_correct_{stage}"] = int(
                    record[f"{source}_attack_detected_{stage}"] == correct_attack_detected
                )
                chosen_type = record[f"{source}_attack_type_{stage}"]
                record[f"{source}_attack_type_correct_{stage}"] = int(
                    chosen_type.strip().casefold() == correct_attack_type.casefold()
                )
        team_attack_type = agg_result["team_attack_type"]
        record.update({key: value for key, value in agg_result.items()
                       if key.startswith("pool_") or key.startswith("team_")})
        record["pool_category_support"] = json.dumps(record["pool_category_support"], sort_keys=True)
        record["aggregation_method"] = "equal_weight_task_confidence_v2" if st.session_state.condition == "pool" else "human_leader"
        record.update(
            team_decision=team_decision,
            team_attack_type=team_attack_type,
            team_attack_detection_correct=int(team_decision == correct_attack_detected),
            team_attack_type_correct=int(team_attack_type == correct_attack_type),
        )
        record["team_score"] = record["team_attack_detection_correct"] + record["team_attack_type_correct"]
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
            "human_detection_confidence": detection_confidence_post,
            "human_category_confidence": category_confidence_post,
            "llm_decision": llm_decision_post,
            "llm_detection_confidence": llm_detection_confidence_post,
            "llm_category_confidence": llm_assessment["category_confidence"],
            "team_decision": team_decision,
            "correct_decision": correct_attack_detected,
            "team_performance": team_perf,
        }
        st.session_state.feedback_record = record
        st.session_state.page = "episode_complete"
        st.rerun()

# ------------------------------------------------------------ results reveal
elif st.session_state.page == "episode_complete":
    st.title("Episode complete. Reveal results:")
    if st.button("Reveal results", type="primary", key="reveal_results"):
        st.session_state.page = "feedback"
        st.rerun()

# ------------------------------------------------------------ episode feedback
elif st.session_state.page == "feedback":
    st.markdown("**IDS evaluation**")
    st.title("Episode feedback")
    summary = st.session_state.submission_summary
    record = st.session_state.feedback_record

    with st.container(border=True):
        st.header("Team outcome")
        team_score = record["team_score"]
        color = {2: "green", 1: "orange", 0: "red"}[team_score]
        outcome = {2: "Fully correct", 1: "Partially correct", 0: "Incorrect"}[team_score]
        st.subheader(f":{color}[{outcome} ({team_score}/2)]")
        attack_present = trial["attack_detected_correct_response"] == "Yes"
        if attack_present:
            detail = "Attack detected" if record["team_attack_detection_correct"] else "Missed attack"
        else:
            detail = "Correctly identified benign activity" if record["team_attack_detection_correct"] else "False alarm"
        if not record["team_attack_type_correct"]:
            detail += " - incorrect attack type"
        st.write(detail)

        # Color the full team comparison by the combined score; truth stays green.
        foreground, background = {
            2: ("#065f46", "#d1fae5"),
            1: ("#854d0e", "#fef9c3"),
            0: ("#991b1b", "#fee2e2"),
        }[team_score]
        decision_col, truth_col = st.columns(2, gap="large")
        team_detection = "Attack present" if summary["team_decision"] == "Yes" else "No attack"
        for column, label, detection, attack_type, text_color, bg_color in (
            (decision_col, "FINAL TEAM DECISION", team_detection, record["team_attack_type"], foreground, background),
            (truth_col, "GROUND TRUTH", "Attack present" if attack_present else "No attack", trial["attack_type_correct_response"], "#065f46", "#d1fae5"),
        ):
            with column:
                st.html(
                    f'<div style="padding:18px;border-radius:8px;background:{bg_color};color:{text_color}">'
                    f'<div>{label}</div><h3 style="color:inherit;margin:8px 0">{detection}</h3>'
                    f'<div>Attack type: {escape(attack_type)}</div></div>'
                )
        st.divider()
        if summary["condition"] == "leader":
            st.markdown("**Your final judgment determined the team decision.**")
        else:
            for label, task in (("Attack detection", "detection"), ("Attack category", "category")):
                source = record[f"team_{task}_source"]
                if source == "agreement":
                    message = "You and your AI teammate agreed."
                else:
                    selected = "your answer" if source == "human" else "the AI teammate's answer"
                    if record[f"team_{task}_tie_break"]:
                        message = f"Equal confidence: a random tie-break selected {selected}."
                    else:
                        message = f"The higher confidence for this task selected {selected}."
                st.markdown(f"**{label}: {message}**")

    st.header("Teammate scores")
    st.write("Detection and attack-type accuracy are scored separately.")
    score_columns = pd.MultiIndex.from_tuples([
        ("Attack detection", "Initial"), ("Attack detection", "Final"),
        ("Attack type", "Initial"), ("Attack type", "Final"),
    ])
    scores = pd.DataFrame([
        ["Correct" if record[f"{source}_{measure}_correct_{stage}"] else "Incorrect"
         for measure in ("attack_detection", "attack_type") for stage in ("pre", "post")]
        for source in ("human", "llm")
    ], index=pd.Index(["You", "AI teammate"], name="Teammate"), columns=score_columns)
    styled_scores = scores.style.map(
        lambda value: "background-color: #d1fae5; color: #065f46; font-weight: bold"
        if value == "Correct" else
        "background-color: #ffedd5; color: #9a3412; font-weight: bold"
    )
    st.table(styled_scores)

    with st.expander("Review labeled IDS events", expanded=False):
        st.caption("See the ground-truth label for each event. Rows labeled malicious are highlighted in red.")
        labeled_table = pd.DataFrame(load_labeled_table(trial["trial_id"]))
        styled_table = labeled_table.style.apply(
            lambda row: ["background-color: #ffcdd2; color: #7f0000" if str(row["malicious"]).strip() == "1" else ""] * len(row),
            axis=1,
        )
        st.dataframe(styled_table, hide_index=True, width="stretch")

    last_trial = st.session_state.trial_index == len(st.session_state.trial_order) - 1
    st.html("""<style>
    .st-key-advance_episode button {
        background-color: #15803d; border-color: #15803d; color: white;
        min-height: 60px; padding: 12px 32px;
    }
    .st-key-advance_episode button p { font-size: 1.2rem; font-weight: 700; }
    .st-key-advance_episode button:hover { background-color: #166534; border-color: #166534; color: white; }
    .st-key-advance_episode button:focus-visible { outline: 3px solid #86efac; outline-offset: 3px; }
    </style>""")
    with st.container(horizontal_alignment="right"):
        advance = st.button("Finish experiment" if last_trial else "Next episode", type="primary", icon=":material/arrow_forward:", icon_position="right", key="advance_episode", width=300)
    if advance:
        if last_trial:
            st.session_state.page = "done"
        else:
            st.session_state.trial_index += 1
            st.session_state.chat_history = []
            st.session_state.pre_answers = None
            st.session_state.submission_summary = None
            st.session_state.timestamp_start = now()
            st.session_state.timestamp_pre_submit = None
            st.session_state.ids_rows_visible = ids_default_rows
            st.session_state.ids_rows_revealed = 0
            for key in ("initial_attack_detected", "initial_attack_type", "initial_detection_confidence",
                        "post_attack_detected", "post_attack_type", "post_detection_confidence",
                        "initial_category_confidence", "post_category_confidence"):
                st.session_state.pop(key, None)
            st.session_state.page = "trial_initial"
        st.rerun()

elif st.session_state.page == "done":
    st.title(settings["experiment_name"])
    st.success(f"All {len(st.session_state.trial_order)} episodes completed. Your responses and chat logs have been saved. Thank you!")
