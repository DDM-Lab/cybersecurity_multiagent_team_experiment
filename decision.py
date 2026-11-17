"""Decision aggregation and team performance scoring algorithms.

Modularized logic to compute team decisions and team performance
scores based on experimental conditions (leader vs pool).
"""
import random


def round_probability_to_decision(probability):
    """Round an attack-probability score (0-100) to a binary decision.

    Rule: > 50 -> 'Yes', <= 50 -> 'No'.
    """
    return "Yes" if probability > 50 else "No"


def normalize_binary_choice(value):
    """Normalize boolean or string binary values to 'Yes' or 'No'."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str):
        val_clean = value.strip().capitalize()
        if val_clean in ["Yes", "True", "1"]:
            return "Yes"
        if val_clean in ["No", "False", "0"]:
            return "No"
    return str(value)


def aggregate_decision(
    condition,
    human_decision,
    human_confidence,
    llm_decision,
    llm_confidence,
):
    """Aggregate human and LLM decisions depending on condition.

    Args:
        condition (str): 'leader' or 'pool'
        human_decision (str/bool): 'Yes' or 'No' (or boolean)
        human_confidence (int/float): confidence score (e.g. 1-100)
        llm_decision (str/bool): 'Yes' or 'No' (or boolean)
        llm_confidence (int/float): confidence score (e.g. 1-100)

    Returns:
        dict: {
            "team_decision": str ("Yes" or "No"),
            "chosen_source": str ("human", "llm", or "tie_breaker")
        }
    """
    human_norm = normalize_binary_choice(human_decision)
    llm_norm = normalize_binary_choice(llm_decision)

    if condition == "leader":
        return {
            "team_decision": human_norm,
            "chosen_source": "human",
        }

    # condition == 'pool'
    if human_confidence > llm_confidence:
        return {
            "team_decision": human_norm,
            "chosen_source": "human",
        }
    elif llm_confidence > human_confidence:
        return {
            "team_decision": llm_norm,
            "chosen_source": "llm",
        }
    else:
        # Tie breaker: randomly select between human and llm
        chosen_source = random.choice(["human", "llm"])
        chosen_decision = human_norm if chosen_source == "human" else llm_norm
        return {
            "team_decision": chosen_decision,
            "chosen_source": "tie_breaker",
            "selected_source": chosen_source,
        }


def calculate_team_performance(team_decision, correct_response):
    """Calculate binary team performance metric.

    For performance calculation, we solely look at the binary choice of 'Yes'/'No'
    for attack_detected. Returns 1 if team_decision matches correct_response, else 0.

    Args:
        team_decision (str/bool): The aggregated team decision.
        correct_response (str/bool): Ground truth response.

    Returns:
        int: 1 for correct, 0 for incorrect.
    """
    team_norm = normalize_binary_choice(team_decision)
    correct_norm = normalize_binary_choice(correct_response)

    return 1 if team_norm == correct_norm else 0


ATTACK_CATEGORIES = (
    "None", "DoS", "Evasion", "Exfiltration", "SMB", "Recon", "DVWA",
    "C&C beaconing", "Credential harvesting",
)


def aggregate_assessment(condition, human_decision, human_category, human_detection_confidence,
                         llm_decision, llm_category, llm_detection_confidence,
                         human_category_confidence, llm_category_confidence):
    """Equal coefficients with task-specific confidence; scores are uncalibrated.

    One fair teammate draw resolves all tied disagreements in an episode.
    Call once at final submission and save the result.
    """
    if condition not in ("leader", "pool"):
        raise ValueError("Unknown condition")
    if human_decision not in ("Yes", "No") or llm_decision not in ("Yes", "No"):
        raise ValueError("Detection answers must be Yes or No")
    if human_category not in ATTACK_CATEGORIES or llm_category not in ATTACK_CATEGORIES:
        raise ValueError("Unknown attack category")
    if not all(1 <= c <= 100 for c in (human_detection_confidence, llm_detection_confidence,
                                      human_category_confidence, llm_category_confidence)):
        raise ValueError("Confidence must be between 1 and 100")
    hd, ld = human_detection_confidence / 100, llm_detection_confidence / 100
    hc, lc = human_category_confidence / 100, llm_category_confidence / 100
    evidence = 0.5 * hd * (1 if human_decision == "Yes" else -1) + 0.5 * ld * (1 if llm_decision == "Yes" else -1)
    support = {category: 0.5 * hc * (human_category == category) +
               0.5 * lc * (llm_category == category) for category in ATTACK_CATEGORIES}
    detection_tie = condition == "pool" and human_decision != llm_decision and hd == ld
    category_tie = condition == "pool" and human_category != llm_category and hc == lc
    tie_source = random.choice(["human", "llm"]) if detection_tie or category_tie else None

    def source(human_answer, llm_answer, human_confidence, llm_confidence, tied):
        if condition == "leader":
            return "human"
        if human_answer == llm_answer:
            return "agreement"
        if tied:
            return tie_source
        return "human" if human_confidence > llm_confidence else "llm"

    detection_source = source(human_decision, llm_decision, hd, ld, detection_tie)
    category_source = source(human_category, llm_category, hc, lc, category_tie)
    return {
        "team_decision": llm_decision if detection_source == "llm" else human_decision,
        "team_attack_type": llm_category if category_source == "llm" else human_category,
        "team_detection_source": detection_source,
        "team_category_source": category_source,
        "team_tie_selected_source": tie_source or "",
        "team_detection_tie_break": detection_tie,
        "team_category_tie_break": category_tie,
        "pool_human_coefficient": 0.5,
        "pool_llm_coefficient": 0.5,
        "pool_detection_evidence": evidence,
        "pool_category_support": support,
    }
