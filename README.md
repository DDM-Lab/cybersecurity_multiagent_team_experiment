# IDS evaluation experiment

Run using the project virtual environment:

```powershell
& "C:\Users\groessli\Documents\Virtual_Env\ids_exp\Scripts\python.exe" -m streamlit run app.py
```

Participants consent once and complete all nine episodes once in a random order: six attacks (DoS, Evasion, Exfiltration, SMB, Recon, DVWA) and three benign office datasets. Each participant is randomly assigned to human leader or confidence pooling for all nine episodes. Pooling uses the higher-confidence judgment, with a random tie-breaker.

Each episode shows the unlabeled CSV from `IDS_tables/attacks` or `IDS_tables/benign`, starting with 10 rows. Each reveal adds 10 rows. Participants submit an independent assessment, discuss with a scripted AI teammate, and submit a final assessment. The AI represents a full-table assessment and does not change after discussion. Each participant randomly receives four or five AI assessments correct on both detection and type; the remaining assessments are wrong on both. Incorrect attack episodes report no attack; incorrect benign episodes report an attack and randomly choose one of the six attack types.

For attack episodes, detection is correct above 50%. For benign episodes, detection is correct at or below 50%, and the correct category is No attack. Detection and attack-type correctness are recorded separately for the human and AI, before and after discussion. Other requires a written answer; it matches the correct type after trimming spaces and ignoring capitalization. The team outcome scores both answers out of two using the same selected teammate: green for 2/2, yellow for 1/2, and red for 0/2. The original `team_performance` field remains detection-only; `team_score` stores the combined score alongside separate team correctness fields.

After each final submission, an episode-complete screen hides results until the participant clicks "Reveal results". Feedback shows the team outcome, whose judgment determined it (including random ties), and separate initial/final teammate scores. "Review labeled IDS events" expands the full labeled CSV with malicious rows highlighted red. Participant screens do not display saved file paths. Labeled files are used only for feedback; key files and JSON tables are unused. The dropdown includes all six types, existing distractors, No attack (first), and Other (last).

`config/settings.json` maps trial IDs to CSVs, attack presence, and correct types. `config/trial_1.json` is legacy and unused. `app.py` controls the flow; `utils.py` loads data and saves CSVs; `decision.py` combines team decisions.

Responses and timestamped chat are saved in `data/{participant_id}_answers.csv` and `data/{participant_id}_chat.csv`. Responses include trial identity, presentation order, condition, initial/final answers, separate correctness scores, and row-reveal counts. Assignment and progress persist during the browser session; refreshing into a new session does not resume a previous experiment. Use a unique participant ID per session.

Real LLM integration is not implemented.

The Ben-Asher dataset can be consolidated with `python consolidate_ben_asher.py`.
This regenerates `ben_asher_dataset/overall_attack_decisions.csv`, with one
overall attack decision per participant and trial. The `security_education_code`
and `security_education_answer` columns preserve the reported highest degree
qualification related to network operation and security (`Degree` in the
processed survey; Q14 in the original questionnaire). Codes are 1 = None,
2 = Associate/certificate, 3 = Bachelors, and 4 = Masters.

The `expertise_group` column uses the requested education-based split:
**novice** when the security-related education answer is **None**, and
**expert** for any other reported answer. This is our operational classification,
not a published score threshold or the papers' recruitment-based expert/novice
grouping. Missing education or an unreliable survey match leaves the label
blank, including participants 6036 and 9036. See
[dataset documentation](ben_asher_dataset/CONSOLIDATION.md) for join and label details.

Run the automated checks (temporary output is isolated from participant data):

```powershell
& "C:\Users\groessli\Documents\Virtual_Env\ids_exp\Scripts\python.exe" -m unittest test_experiment -v
```
