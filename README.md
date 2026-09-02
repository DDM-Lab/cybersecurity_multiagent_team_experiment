# IDS Evaluation Task with Multi-agent teams

In this experiment, human subjects will interact with an LLM chat to make scenario judgements with corresponding confidence ratings after looking through an IDS table with a series of network events. 

Please use the following virtual environment located in: "C:\Users\groessli\Documents\Virtual_Env\ids_exp"

The requirements are located in requirements.txt.

This application should use streamlit, and the focus is MVP! We will slowly integrate and add more features for experimental structure, LLM API key, etc. as we proceed with this repository. Let's just get a prototype up and running so we have a visualization on what this experiment can look like at a basic level, alongside a basic mechanism to store data as CSV files. No database management! No frills. Just a simple mechanism to store the chat convos with the human in the chat with timestamps, alongside their answers to the required questions. 


Please make sure to update this Readme once you've finished implementation. Be VERY concise and use plain english. 

## Current status: working prototype with authority manipulation

Run it with:
```
streamlit run app.py
```

**Flow:** consent page (participant ID + consent checkbox, condition assigned) → IDS table + dummy LLM chat + judgment form → confirmation page with condition-specific performance feedback.

**Experimental manipulation (Authority):**
- **leader**: Human decision exclusively determines the team decision and score.
- **pool**: Team decision is aggregated between human and LLM, weighted by confidence (highest confidence wins; random tie-breaker).
- Condition is alternated between incoming participants via `data/assignment_tracker.json`.

**Files:**
- `app.py` — Streamlit app UI and flow orchestration.
- `decision.py` — Standalone decision aggregation heuristics and binary team performance calculation (`1` or `0`).
- `utils.py` — Config loading, condition tracking, dummy LLM reply, and CSV persistence.
- `config/settings.json` — Experiment settings (name, trial order).
- `config/trial_1.json` — Dummy trial data: IDS events, LLM assessment/reply, and ground truth correct responses.
- `data/{participant_id}_answers.csv` and `data/{participant_id}_chat.csv` — CSV data storage per participant. Answers CSV contains condition, human responses, LLM responses, ground truth, and team performance.

**Not yet implemented:** real LLM API calls, multiple/randomized trials, additional experimental conditions, Prolific ID capture, authentication.

## For the coding agent: how to run/test

The project's Python interpreter lives in a dedicated venv, not on the default `python`/`pip` PATH. Always call it explicitly:

```
& "C:\Users\groessli\Documents\Virtual_Env\ids_exp\Scripts\python.exe" -m streamlit run app.py --server.headless true
```

Quick sanity checks (no need to click through the UI for these):
```
& "C:\Users\groessli\Documents\Virtual_Env\ids_exp\Scripts\python.exe" -c "import ast; ast.parse(open('app.py').read()); ast.parse(open('utils.py').read())"
& "C:\Users\groessli\Documents\Virtual_Env\ids_exp\Scripts\python.exe" -c "import json; json.load(open('config/settings.json')); json.load(open('config/trial_1.json'))"
```

To test `save_answers_csv`/`save_chat_csv` behavior directly without the UI:
```
& "C:\Users\groessli\Documents\Virtual_Env\ids_exp\Scripts\python.exe" -c "import utils; print(utils.save_answers_csv('test_participant', 1, {'participant_id':'test_participant','trial_number':1,'attack_detected':'Yes','attack_type':'Port scan','confidence':80}))"
```

After any manual test runs, delete the generated `data/` folder/CSVs (they're git-ignored scratch output, not fixtures):
```
Remove-Item -Recurse -Force data -ErrorAction SilentlyContinue
```

If launching Streamlit to smoke-test, run it as a background/async command, confirm it prints `Local URL: http://localhost:8501` with no traceback, then kill the process rather than leaving it running.
