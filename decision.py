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
