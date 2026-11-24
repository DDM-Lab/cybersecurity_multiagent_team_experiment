# IDS evaluation experiment

Run using the project virtual environment:

```powershell
& "C:\Users\groessli\Documents\Virtual_Env\ids_exp\Scripts\python.exe" -m streamlit run app.py
```

Participants consent once and complete all nine episodes once in a random order: six attacks (DoS, Evasion, Exfiltration, SMB, Recon, DVWA) and three benign office datasets. Each participant is randomly assigned to human leader or confidence pooling for all nine episodes. Pooling uses fixed equal teammate coefficients (0.5 each), with task-specific confidence affecting each judgment's contribution. This is an untrained adaptation; the scores are not calibrated probabilities.

Each episode shows the unlabeled CSV from `IDS_tables/attacks` or `IDS_tables/benign`, starting with 10 rows. Each reveal adds 10 rows. Participants submit an independent assessment, discuss with an AI teammate, and submit a final assessment. The AI teammate is the Foundation-Sec-8B-Reasoning model, which assesses the full table itself at the start of the episode and gives its own final conclusion when the participant submits. See "LLM teammate" below.

Participants answer ?Is there an ongoing cyberattack?? (Yes/No). Only Yes reveals the attack-category question. Detection and category have separate 1?100 confidence ratings (1 = least confident; 100 = most confident), with the same scale and meaning for the human and the AI. Answering No hides the category question and its confidence slider: category is recorded as None and category confidence inherits detection confidence. This also overrides any previous category selection or rating. The same rule is applied to the model's answers. Categories are None, DoS, Evasion, Exfiltration, SMB, Recon, DVWA, C&C beaconing, and Credential harvesting. None is correct for benign episodes; both tasks are scored on every episode.

Pooling uses fixed 0.5 coefficients. Confidence / 100 only rescales the ratings; it does not calibrate them. Detection evidence uses detection confidence, signed positive for Yes and negative for No. Each category receives 0.5 times category confidence from each teammate choosing it, including None. Agreement is retained; disagreements follow the higher confidence for that task. Different teammates can determine detection and category. Equal-confidence disagreements use one fair random teammate draw shared by all tied tasks in the episode. Untied tasks still follow their own confidence ratings. Neither pooled result overrides the other. Human leader decisions continue to follow the human's final answers.

Records include both teammates' initial/final answers and task-specific confidence, flags indicating inferred human category confidence, both final team answers, separate sources and tie-break flags, the shared tie selection, fixed coefficients, detection evidence, and category support. Results are saved at final submission and reused on feedback reruns. The team score is detection accuracy plus category accuracy (0?2), including benign episodes. The original `team_performance` field remains detection-only. The aggregation version is `equal_weight_task_confidence_v2` for pooling.

After each final submission, an episode-complete screen hides results until the participant clicks "Reveal results". Feedback shows the team outcome, whose judgment determined it (including random ties), and separate initial/final teammate scores. "Review labeled IDS events" expands the full labeled CSV with malicious rows highlighted red. Participant screens do not display saved file paths. Labeled files are used only for feedback; key files and JSON tables are unused. The conditional category dropdown contains the eight attack categories.

`config/settings.json` maps trial IDs to CSVs, attack presence, and correct types. `config/trial_1.json` is legacy and unused. `app.py` controls the flow; `utils.py` loads data and saves CSVs; `decision.py` combines team decisions.

Responses and timestamped chat are saved in `data/{participant_id}_answers.csv` and `data/{participant_id}_chat.csv`. Responses include trial identity, presentation order, condition, initial/final answers, separate correctness scores, and row-reveal counts. Assignment and progress persist during the browser session; refreshing into a new session does not resume a previous experiment. Use a unique participant ID per session.

## LLM teammate

The AI teammate is Foundation-Sec-8B-Reasoning (Q4_K_M), served on the lab server talos. `llm.py` holds the integration and `prompts/` holds every word the model is given.

**One conversation per episode.** Each table starts a fresh conversation, so nothing from one episode reaches the model in the next. It has three phases.

1. **Initial assessment.** As soon as the episode loads, the model receives the whole table (all rows, not only those the participant has revealed) and answers in a fixed format: attack Yes or No, attack type, detection confidence and category confidence, each confidence from 1 to 100, and an explanation. This runs in the background while the participant makes their own judgment, and fills the assessment card on the discussion page. If it is not ready when the participant submits, a spinner waits for it.
2. **Discussion.** The participant's chat messages go to the same conversation. The first one is sent together with the participant's initial assessment. Replies are conversational.
3. **Final conclusion.** When the participant clicks Submit Final Assessment, the model is asked for its own final conclusion in the same format. It is not told the participant's final answer, so the two final judgments stay independent for pooling. Its answer may differ from its initial assessment, and the `llm_*_changed` fields record whether it did.

**The prompts.** `system_high_fidelity.txt` and `system_low_fidelity.txt` explain the role, the three phases and the rules (cite rows, use only values in the table, some tables are ordinary traffic), and set the audience style. `turn_initial.txt` carries the table, a one-line definition of each attack category and the answer format. `turn_discussion_start.txt` carries the participant's initial assessment and first message. `turn_final.txt` asks for the final conclusion. The four `reminder_*.txt` files close every request with a short note on length and wording for the current audience (`reminder_assessment_*` after the initial and final turns, `reminder_chat_*` after each participant message). The model follows the latest message far more closely than the system prompt, so the style rules are repeated there. The participant never sees them. Placeholders such as `$table` are filled in by `llm.py`. A SHA-256 of every prompt file is saved with each episode, so results can be tied to the exact wording.

**Reading the answer.** The format is read tolerantly (markdown, `85%`, `85/100`, common wordings of a category). Attack No forces type None and sets category confidence equal to detection confidence, the same rule as for participants. An unreadable answer is retried with a new seed, up to three attempts.

**When the model fails.** If the initial assessment fails three times or the server cannot be reached, the card says so, the chat is disabled, and the participant's final answers decide the episode (`aggregation_method` is `human_only_llm_unavailable`). If only the final call fails, the initial assessment stands in for the final one (`llm_post_source` is `initial`). A failed chat reply shows a short message and the participant's text is sent again with their next message.

**Response style.** A toggle above the chat switches between high fidelity (technical detail, ports, indicators) and low fidelity (plain language for a non-technical reader). It applies from the next model call and carries over between episodes. `llm.default_fidelity` in `config/settings.json` sets the starting style, and `llm.show_fidelity_toggle: false` hides the toggle.

**Reply budget.** Fixed at 4096 tokens (`llm.max_tokens`), with no control on the page. The model reasons before it answers and the reasoning counts against the budget. Long discussions are trimmed from the oldest turns to fit the model's context, always keeping the table, the initial assessment and the participant's initial answers.

**Text after the turn.** The model sometimes keeps writing after its turn should have ended, inventing the participant's next message or a new phase. `llm.py` cuts a reply at the first line, after its first, that starts with one of the `turn_end_markers` in `config/settings.json` (for example `Participant:`, `You:`, `Discussion:` or `Phase 2:`, ignoring case and markdown). Only the part before the cut is shown, parsed and kept in the conversation. The removed text is saved in `cut_text` so its frequency can be checked.

**Saved.** The answers CSV holds the model's real initial and final answers in the existing `llm_*_pre` and `llm_*_post` fields, plus `llm_assessment_status`, `llm_attempts`, `llm_explanation`, `llm_raw` (the reply as shown), `llm_cut_text`, `llm_fidelity`, `llm_seed` and `llm_error` for each stage, `llm_post_source`, `llm_prompt_sha256`, `llm_fidelity_at_submit` and `llm_chat_replies`. Each chat reply in `data/{participant_id}_chat.csv` records `fidelity`, `prompt_sha256`, `seed`, `status`, `finish_reason`, `completion_tokens`, `latency_seconds`, `raw_message`, `cut_text` and `error`. Seeds are derived from the participant ID, episode and call number, so a reply can be reproduced.

**Model accuracy is not tuned.** The model's detection, attack type and confidence are what it produces out of the box, so the study also measures the model's own accuracy. Without the scripted assessments, that accuracy is whatever the model achieves, not a fixed four or five correct episodes. The prompts tune only the reply style, the answer format and where a turn ends. Two instructions in both system prompts bear on the model's answers and are part of the task description:

- **The ordinary-traffic rule** is a detection nudge: "Ordinary traffic includes name lookups, web browsing, mail and file access between office machines and servers. Call something an attack only when the rows show behaviour that ordinary use does not explain." Without it, the model called most attack-free tables attacks. With it, in a run of 54 episodes on 23 November 2026 (9 tables, both fidelities, 3 repeats), the model's initial call was right on 16 of 18 attack-free tables and caught 24 of 36 attacks, with the right category for 9 of them. Detection results therefore come from the model together with this instruction.
- **The confidence definition** tells the model that each confidence is how sure it is of its own answer, on the participant's 1 to 100 scale, so a certain No is 100. Without it, the model scored a No by the chance that an attack was happening. It defines the scale so the two teammates' confidences can be pooled, and does not adjust accuracy. In the same run, the model's confidence did not separate right from wrong calls (median 95 when right, 97.5 when wrong).

**Endpoint.** `llm.endpoint` in the settings, or the `LLM_ENDPOINT` environment variable. On talos the app reaches the model at `http://127.0.0.1:8080/v1/chat/completions`. To run the app on a laptop instead, open a tunnel to the chat page and set `LLM_ENDPOINT=http://127.0.0.1:8090/v1/chat/completions`.

The server handles one request at a time, so participants chatting at the same moment wait for each other.

### Using the deployed copy on talos

The app runs on talos and is reached through an SSH tunnel. With a talos account that can read `/home/ddmlab`:

```bash
ssh -N -L 8070:/home/ddmlab/hat-llm/experiment.sock you@talos.ddmlab.com
```

Leave it running and open http://127.0.0.1:8070. Participant data from the deployed copy is written on talos, not on your machine.

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
