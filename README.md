# IDS Evaluation Task with Multi-agent teams

In this experiment, human subjects will interact with an LLM chat to make scenario judgements with corresponding confidence ratings after looking through an IDS table with a series of network events. 

Please use the following virtual environment located in: "C:\Users\groessli\Documents\Virtual_Env\ids_exp"

The requirements are located in requirements.txt.

This application should use streamlit, and the focus is MVP! We will slowly integrate and add more features for experimental structure, LLM API key, etc. as we proceed with this repository. Let's just get a prototype up and running so we have a visualization on what this experiment can look like at a basic level, alongside a basic mechanism to store data as CSV files. No database management! No frills. Just a simple mechanism to store the chat convos with the human in the chat with timestamps, alongside their answers to the required questions. 


Please make sure to update this Readme once you've finished implementation. Be VERY concise and use plain english. 

## Current status: working prototype

Run it with:
```
streamlit run app.py
```

**Flow:** consent page (participant ID + consent checkbox) → IDS table + dummy LLM chat + judgment form → confirmation page.

**Files:**
- `app.py` — the whole app (3 pages via `st.session_state`).
- `utils.py` — config loading, dummy LLM reply, CSV saving.
- `config/settings.json` — experiment-wide settings (name, condition, trial order).
- `config/trial_1.json` — the one dummy trial: IDS table rows, LLM's initial assessment, and its fixed chat reply.
- `data/{participant_id}/trial_{n}_answers.csv` and `trial_{n}_chat.csv` — saved after each submission (folder is git-ignored).

**Not yet implemented:** real LLM API calls, multiple/randomized trials, the 5 experimental conditions, Prolific ID capture, authentication.
