# IDS evaluation experiment

Run using the project virtual environment:

```powershell
& "C:\Users\groessli\Documents\Virtual_Env\ids_exp\Scripts\python.exe" -m streamlit run app.py
```

Participants consent once and complete six trials in a random order: DoS, Evasion, Exfiltration, SMB, Recon, and DVWA. Each participant is randomly assigned to human leader or confidence pooling for all six trials. Pooling uses the higher-confidence judgment, with a random tie-breaker.

Each trial shows the unlabeled CSV from `IDS_tables`, starting with 10 rows. Each reveal adds 10 rows. Participants submit an independent assessment, discuss with a scripted AI teammate, and submit a final assessment. The AI represents a full-table assessment and does not change after discussion. Exactly three AI assessments are correct on both detection and type; three incorrectly report no attack. Which three are correct is randomized per participant.

All six tables contain an attack. Detection is correct only above 50%; exactly 50% is incorrect. Detection and attack-type correctness are recorded separately for the human and AI, before and after discussion. Other requires a written answer; it matches the correct type after trimming spaces and ignoring capitalization. The team outcome scores both answers out of two using the same selected teammate: green for 2/2, yellow for 1/2, and red for 0/2. The original `team_performance` field remains detection-only; `team_score` stores the combined score alongside separate team correctness fields.

After each final submission, an episode-complete screen hides results until the participant clicks "Reveal results". Feedback shows the team outcome, whose judgment determined it (including random ties), and separate initial/final teammate scores. "Review labeled IDS events" expands the full labeled CSV with malicious rows highlighted red. Participant screens do not display saved file paths. Labeled files are used only for feedback; key files and JSON tables are unused. The dropdown includes all six types, existing distractors, No attack (first), and Other (last).

`config/settings.json` maps trial IDs to CSVs and correct types. `config/trial_1.json` is legacy and unused. `app.py` controls the flow; `utils.py` loads data and saves CSVs; `decision.py` combines team decisions.

Responses and timestamped chat are saved in `data/{participant_id}_answers.csv` and `data/{participant_id}_chat.csv`. Responses include trial identity, presentation order, condition, initial/final answers, separate correctness scores, and row-reveal counts. Assignment and progress persist during the browser session; refreshing into a new session does not resume a previous experiment. Use a unique participant ID per session.

Real LLM integration is not implemented.

Run the automated checks (temporary output is isolated from participant data):

```powershell
& "C:\Users\groessli\Documents\Virtual_Env\ids_exp\Scripts\python.exe" -m unittest test_experiment -v
```
