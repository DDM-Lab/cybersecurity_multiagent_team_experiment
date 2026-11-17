"""Streamlit prototype: participant reviews an IDS table and gives an independent
judgment, then discusses with a dummy LLM teammate before finalizing.
Flow: consent -> (trial_initial -> trial_discuss -> feedback) x 6 -> done."""
from datetime import datetime
from html import escape

import pandas as pd
import streamlit as st

from decision import (
    aggregate_decision,
    calculate_team_performance,
    round_probability_to_decision,
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
    attack_type_other = ""
    if attack_type == "Other":
        attack_type_other = st.text_input("Please specify the attack type", key="initial_other")
    confidence = st.slider("How confident are you?", 1, 100, 50, key="initial_confidence")

    if st.button("Submit Initial Assessment"):
        if attack_type is None or (attack_type == "Other" and not attack_type_other.strip()):
            st.error("Please select a suspected attack type.")
        else:
            st.session_state.pre_answers = {
                "attack_probability": attack_probability,
                "attack_type": attack_type,
                "attack_type_other": attack_type_other.strip(),
                "confidence": confidence,
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
    attack_type_other_post = ""
    if attack_type_post == "Other":
        attack_type_other_post = st.text_input(
            "Please specify the attack type", value=pre["attack_type_other"], key="post_other"
        )
    confidence_post = st.slider(
        "How confident are you?", 1, 100, pre["confidence"], key="post_confidence"
    )

    if st.button("Submit Final Assessment"):
        if attack_type_post == "Other" and not attack_type_other_post.strip():
            st.error("Please specify the attack type.")
            st.stop()
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
            "trial_id": trial["trial_id"],
            "trial_order": ",".join(st.session_state.trial_order),
            "human_attack_type_other_pre": pre["attack_type_other"],
            "human_attack_type_other_post": attack_type_other_post.strip(),
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
            "ids_rows_visible": st.session_state.ids_rows_visible,
            "ids_rows_revealed": st.session_state.ids_rows_revealed,
            "team_performance": team_perf,
        }
        for source in ("human", "llm"):
            for stage in ("pre", "post"):
                record[f"{source}_attack_detection_correct_{stage}"] = int(
                    record[f"{source}_attack_probability_{stage}"] > 50
                )
                chosen_type = record[f"{source}_attack_type_{stage}"]
                if source == "human" and chosen_type == "Other":
                    chosen_type = record[f"human_attack_type_other_{stage}"]
                record[f"{source}_attack_type_correct_{stage}"] = int(
                    chosen_type.strip().casefold() == correct_attack_type.casefold()
                )
        selected_source = agg_result.get("selected_source", agg_result["chosen_source"])
        team_attack_type = record[f"{selected_source}_attack_type_post"]
        if selected_source == "human" and team_attack_type == "Other":
            team_attack_type = record["human_attack_type_other_post"]
        record.update(
            team_decision=team_decision,
            team_attack_type=team_attack_type,
            team_selected_source=selected_source,
            team_attack_detection_correct=record[f"{selected_source}_attack_detection_correct_post"],
            team_attack_type_correct=record[f"{selected_source}_attack_type_correct_post"],
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
            "human_confidence": confidence_post,
            "llm_decision": llm_decision_post,
            "llm_confidence": llm_confidence_post,
            "team_decision": team_decision,
            "correct_decision": correct_attack_detected,
            "team_performance": team_perf,
            "chosen_source": agg_result["chosen_source"],
            "selected_source": agg_result.get("selected_source", agg_result["chosen_source"]),
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
        if record["team_attack_detection_correct"]:
            detail = "Attack detected" if record["team_attack_type_correct"] else "Attack detected - incorrect attack type"
        else:
            detail = "Missed attack - correct attack type" if record["team_attack_type_correct"] else "Missed attack - incorrect attack type"
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
            (truth_col, "GROUND TRUTH", "Attack present", trial["attack_type_correct_response"], "#065f46", "#d1fae5"),
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
        elif summary["chosen_source"] == "tie_breaker":
            selected = "your judgment" if summary["selected_source"] == "human" else "the AI teammate's judgment"
            st.markdown(f"**Your confidence ratings were equal. A random tie-break selected {selected} to determine the team decision.**")
        elif summary["chosen_source"] == "human":
            st.markdown("**Your final judgment determined the team decision because your confidence was higher.**")
        else:
            st.markdown("**Your AI teammate's final judgment determined the team decision because its confidence was higher.**")

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
            for key in ("initial_attack_probability", "initial_attack_type", "initial_confidence",
                        "post_attack_probability", "post_attack_type", "post_confidence",
                        "initial_other", "post_other"):
                st.session_state.pop(key, None)
            st.session_state.page = "trial_initial"
        st.rerun()

elif st.session_state.page == "done":
    st.title(settings["experiment_name"])
    st.success("All six episodes completed. Your responses and chat logs have been saved. Thank you!")
