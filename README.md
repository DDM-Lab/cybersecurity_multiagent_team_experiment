# IDS evaluation experiment

Run using the project virtual environment:

```powershell
& "C:\Users\groessli\Documents\Virtual_Env\ids_exp\Scripts\python.exe" -m streamlit run app.py
```

Participants consent once and complete all nine episodes once in a random order: six attacks (DoS, Evasion, Exfiltration, SMB, Recon, DVWA) and three benign office datasets. Each participant is randomly assigned to human leader or confidence pooling for all nine episodes. Pooling uses fixed equal teammate coefficients (0.5 each), with task-specific confidence affecting each judgment's contribution. This is an untrained adaptation; the scores are not calibrated probabilities.

Each episode shows the unlabeled CSV from `IDS_tables/attacks` or `IDS_tables/benign`, starting with 10 rows. Each reveal adds 10 rows. Participants submit an independent assessment, discuss with a scripted AI teammate, and submit a final assessment. The AI represents a full-table assessment and does not change after discussion. Each participant randomly receives four or five AI assessments correct on both detection and type; the remaining assessments are wrong on both. Incorrect attack episodes report no attack; incorrect benign episodes report an attack and randomly choose one of the six attack types. Their category is None when reporting no attack; this scripted generation does not constrain human answers or pooled results.

Participants answer ?Is there an ongoing cyberattack?? (Yes/No). Only Yes reveals the attack-category question. Detection and category have separate 1?100 confidence ratings (1 = least confident; 100 = most confident), with the same scale and meaning for the human and scripted AI. Answering No hides the category question and its confidence slider: category is recorded as None and category confidence inherits detection confidence. This also overrides any previous category selection or rating. The scripted AI currently supplies 80 for each task. Categories are None, DoS, Evasion, Exfiltration, SMB, Recon, DVWA, C&C beaconing, and Credential harvesting. None is correct for benign episodes; both tasks are scored on every episode.

Pooling uses fixed 0.5 coefficients. Confidence / 100 only rescales the ratings; it does not calibrate them. Detection evidence uses detection confidence, signed positive for Yes and negative for No. Each category receives 0.5 times category confidence from each teammate choosing it, including None. Agreement is retained; disagreements follow the higher confidence for that task. Different teammates can determine detection and category. Equal-confidence disagreements use one fair random teammate draw shared by all tied tasks in the episode. Untied tasks still follow their own confidence ratings. Neither pooled result overrides the other. Human leader decisions continue to follow the human's final answers.

Records include both teammates' initial/final answers and task-specific confidence, flags indicating inferred human category confidence, both final team answers, separate sources and tie-break flags, the shared tie selection, fixed coefficients, detection evidence, and category support. Results are saved at final submission and reused on feedback reruns. The team score is detection accuracy plus category accuracy (0?2), including benign episodes. The original `team_performance` field remains detection-only. The aggregation version is `equal_weight_task_confidence_v2` for pooling.

After each final submission, an episode-complete screen hides results until the participant clicks "Reveal results". Feedback shows the team outcome, whose judgment determined it (including random ties), and separate initial/final teammate scores. "Review labeled IDS events" expands the full labeled CSV with malicious rows highlighted red. Participant screens do not display saved file paths. Labeled files are used only for feedback; key files and JSON tables are unused. The conditional category dropdown contains the eight attack categories.

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
