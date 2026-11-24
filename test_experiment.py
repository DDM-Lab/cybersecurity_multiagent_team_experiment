import tempfile
from pathlib import Path
from unittest.mock import patch
import csv
import unittest
from itertools import product
import llm
import utils
from decision import aggregate_assessment
from streamlit.testing.v1 import AppTest

class ExperimentTest(unittest.TestCase):
    def test_equal_weight_pooling(self):
        for hd, ld, ha, la, hc, lc in product(
            ('Yes', 'No'), ('Yes', 'No'), ('None', 'Exfiltration'),
            ('None', 'Exfiltration'), (1, 80, 100), (1, 80, 100)
        ):
            for selected in ('human', 'llm'):
                with patch('decision.random.choice', return_value=selected) as draw:
                    result = aggregate_assessment('pool', hd, ha, hc, ld, la, lc, hc, lc)
                tie = hc == lc and (hd != ld or ha != la)
                self.assertEqual(draw.call_count, int(tie))
                source = selected if tie else ('human' if hc >= lc else 'llm')
                self.assertEqual(result['team_decision'], hd if source == 'human' else ld)
                self.assertEqual(result['team_attack_type'], ha if source == 'human' else la)
                self.assertEqual(result['team_detection_tie_break'], hc == lc and hd != ld)
                self.assertEqual(result['team_category_tie_break'], hc == lc and ha != la)
                self.assertEqual(result['pool_human_coefficient'], 0.5)
                self.assertEqual(result['pool_llm_coefficient'], 0.5)
                self.assertAlmostEqual(result['pool_detection_evidence'],
                    0.5 * hc / 100 * (1 if hd == 'Yes' else -1) +
                    0.5 * lc / 100 * (1 if ld == 'Yes' else -1))
                for category, support in result['pool_category_support'].items():
                    self.assertAlmostEqual(support, 0.5 * hc / 100 * (ha == category) +
                                           0.5 * lc / 100 * (la == category))
        # No consistency override: a No answer can carry any attack category.
        result = aggregate_assessment('pool', 'No', 'Exfiltration', 90, 'Yes', 'None', 80, 90, 80)
        self.assertEqual((result['team_decision'], result['team_attack_type']), ('No', 'Exfiltration'))
        with patch('decision.random.choice', side_effect=AssertionError('Leader tie')):
            result = aggregate_assessment('leader', 'No', 'None', 1, 'Yes', 'DoS', 100, 1, 100)
        self.assertEqual((result['team_decision'], result['team_attack_type']), ('No', 'None'))

    def test_different_task_winners(self):
        result = aggregate_assessment('pool', 'Yes', 'DoS', 90, 'No', 'None', 60, 30, 80)
        self.assertEqual((result['team_decision'], result['team_attack_type']), ('Yes', 'None'))
        self.assertEqual(result['team_detection_source'], 'human')
        self.assertEqual(result['team_category_source'], 'llm')
        self.assertFalse(result['team_detection_tie_break'])
        self.assertFalse(result['team_category_tie_break'])
        with patch('decision.random.choice', return_value='llm') as draw:
            result = aggregate_assessment('pool', 'Yes', 'DoS', 90, 'No', 'None', 60, 80, 80)
        draw.assert_called_once()
        self.assertEqual(result['team_detection_source'], 'human')
        self.assertEqual(result['team_category_source'], 'llm')
        self.assertFalse(result['team_detection_tie_break'])
        self.assertTrue(result['team_category_tie_break'])

    def test_plan_and_tables(self):
        settings=utils.load_settings()
        for _ in range(20):
            order=utils.create_trial_plan(settings)
            self.assertEqual(sorted(order),sorted(settings['trial_order']))
        for i in settings['trial_order']:
            rows=utils.load_trial(i)['ids_events']
            self.assertNotIn('malicious', rows[0])
            self.assertEqual(len(rows),len(utils.load_labeled_table(i)))
        with patch('utils.random.choice',return_value='pool'):
            self.assertEqual(utils.get_next_condition(),'pool')

    def test_feedback_outcomes_and_sources(self):
        settings = utils.load_settings()
        order = utils.create_trial_plan(settings)
        order.remove('dos')
        order.insert(0, 'dos')
        record = {f"{source}_{measure}_correct_{stage}": 1
                  for source in ("human", "llm")
                  for measure in ("attack_detection", "attack_type")
                  for stage in ("pre", "post")}
        cases = [
            ("leader", "human", "human", "Your final judgment determined"),
            ("pool", "human", "human", "selected your answer"),
            ("pool", "llm", "llm", "selected the AI teammate's answer"),
            ("pool", "tie_breaker", "human", "selected your answer"),
            ("pool", "tie_breaker", "llm", "selected the AI teammate's answer"),
        ]
        for condition, chosen, selected, expected, scenario in (
            (*case, scenario) for case in cases for scenario in ('dos', 'benign_1')
        ):
            order.remove(scenario)
            order.insert(0, scenario)
            for detection_correct, type_correct in ((0, 0), (0, 1), (1, 0), (1, 1)):
                correct = detection_correct
                score = detection_correct + type_correct
                record.update(team_score=score, team_attack_detection_correct=detection_correct,
                              team_attack_type_correct=type_correct, team_attack_type="Recon",
                              team_detection_source=selected, team_category_source=selected,
                              team_detection_tie_break=chosen == "tie_breaker",
                              team_category_tie_break=chosen == "tie_breaker")
                at = AppTest.from_file('app.py', default_timeout=15)
                state = dict(
                    page="feedback", trial_order=order, trial_index=0,
                    feedback_record=record,
                    submission_summary={"condition": condition, "chosen_source": chosen,
                                        "selected_source": selected, "team_performance": correct,
                                        "team_decision": "Yes" if correct else "No"},
                )
                for key, value in state.items():
                    at.session_state[key] = value
                at.run()
                self.assertFalse(at.exception)
                self.assertTrue(any(expected in element.value for element in at.markdown))
                self.assertTrue(any(f"({score}/2)" in element.value for element in at.subheader))
                expected_outcome = (("Attack detected" if correct else "Missed attack") if scenario == 'dos'
                                    else ("Correctly identified benign activity" if correct else "False alarm"))
                self.assertTrue(any(expected_outcome in element.value for element in at.markdown))

    def test_nine_episode_flow(self):
        self._check_nine_episode_flow('pool')

    def test_nine_episode_leader_flow(self):
        self._check_nine_episode_flow('leader')

    def test_initial_no_and_final_yes(self):
        with tempfile.TemporaryDirectory(dir='.') as tmp, patch.object(utils, 'DATA_DIR', tmp), \
                patch('llm.request_reply', side_effect=FakeModel()):
            at = AppTest.from_file('app.py', default_timeout=15).run()
            at.text_input[0].set_value('conditional_test')
            at.checkbox[0].check()
            at.button[0].click().run()
            at.selectbox(key='initial_attack_detected').select('No').run()
            next(b for b in at.button if b.label == 'Submit Initial Assessment').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state.pre_answers['attack_type'], 'None')
            self.assertFalse(any(w.key == 'post_attack_type' for w in at.selectbox))
            at.selectbox(key='post_attack_detected').select('Yes').run()
            next(b for b in at.button if b.label == 'Submit Final Assessment').click().run()
            self.assertTrue(at.error)
            self.assertEqual(at.session_state.page, 'trial_discuss')
            at.selectbox(key='post_attack_type').select('Exfiltration')
            at.slider(key='post_detection_confidence').set_value(90)
            at.slider(key='post_category_confidence').set_value(30)
            next(b for b in at.button if b.label == 'Submit Final Assessment').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state.feedback_record['human_attack_type_pre'], 'None')
            self.assertEqual(at.session_state.feedback_record['human_attack_type_post'], 'Exfiltration')
            self.assertEqual(at.session_state.feedback_record['human_detection_confidence_post'], 90)
            self.assertEqual(at.session_state.feedback_record['human_category_confidence_post'], 30)
            self.assertFalse(at.session_state.feedback_record['human_category_confidence_inferred_post'])

    def _check_nine_episode_flow(self, assigned_condition):
        with tempfile.TemporaryDirectory(dir='.') as tmp, patch.object(utils,'DATA_DIR',tmp), patch('utils.get_next_condition', return_value=assigned_condition), \
                patch('llm.request_reply', side_effect=FakeModel()):
            at=AppTest.from_file('app.py',default_timeout=15).run()
            self.assertFalse(at.exception)
            at.text_input[0].set_value('test_participant')
            at.checkbox[0].check()
            at.button[0].click().run()
            condition=at.session_state.condition
            order=list(at.session_state.trial_order)
            for n, trial_id in enumerate(order):
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state.condition,condition)
                self.assertEqual(len(at.dataframe[0].value),10)
                self.assertNotIn('malicious',at.dataframe[0].value.columns)
                total=len(utils.load_trial(trial_id)['ids_events'])
                for _ in range(total//10-1):
                    at.button(key='show_more_ids_rows').click().run()
                self.assertEqual(len(at.dataframe[0].value),total)
                if n==0:
                    next(b for b in at.button if b.label=='Submit Initial Assessment').click().run()
                    self.assertTrue(at.error)
                self.assertFalse(any(w.key == 'initial_attack_type' for w in at.selectbox))
                at.selectbox(key='initial_attack_detected').select('No').run()
                self.assertFalse(any(w.key == 'initial_attack_type' for w in at.selectbox))
                at.selectbox(key='initial_attack_detected').select('Yes').run()
                self.assertNotIn('None', at.selectbox(key='initial_attack_type').options)
                at.selectbox(key='initial_attack_type').select('DoS')
                at.slider(key='initial_detection_confidence').set_value(80)
                at.slider(key='initial_category_confidence').set_value(80)
                next(b for b in at.button if b.label=='Submit Initial Assessment').click().run()
                self.assertFalse(at.exception)
                if n==0:
                    at.chat_input[0].set_value('What do you think?').run()
                    self.assertEqual(len(at.session_state.chat_history),2)
                at.selectbox(key='post_attack_detected').select('No').run()
                self.assertFalse(any(w.key == 'post_attack_type' for w in at.selectbox))
                next(b for b in at.button if b.label=='Submit Final Assessment').click().run()
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state.page,'episode_complete')
                saved_record = dict(at.session_state.feedback_record)
                with patch('decision.random.choice', side_effect=AssertionError('Tie redrawn')):
                    at.run()
                self.assertEqual(dict(at.session_state.feedback_record), saved_record)
                self.assertEqual(len(at.dataframe),0)
                self.assertEqual(len(at.table),0)
                self.assertEqual(len(at.expander),0)
                self.assertEqual(len(at.button),1)
                at.button(key='reveal_results').click().run()
                self.assertEqual(at.session_state.page,'feedback')
                with patch('decision.random.choice', side_effect=AssertionError('Feedback tie redrawn')):
                    at.run()
                self.assertEqual(dict(at.session_state.feedback_record), saved_record)
                self.assertEqual(len(at.table),1)
                self.assertEqual(at.expander[0].label,'Review labeled IDS events')
                self.assertFalse(at.expander[0].proto.expanded)
                self.assertFalse(any('saved to:' in element.value for element in at.markdown))
                self.assertFalse(at.exception)
                self.assertEqual(len(at.dataframe[-1].value),total)
                self.assertIn('malicious',at.dataframe[-1].value.columns)
                settings_for_trial=utils.load_settings()['trials'][trial_id]
                record=at.session_state.feedback_record
                self.assertEqual(record['human_attack_type_post'], 'None')
                self.assertEqual(record['human_attack_type_correct_post'], int(not settings_for_trial['attack_present']))
                self.assertEqual(record['pool_human_coefficient'], 0.5)
                self.assertEqual(record['pool_llm_coefficient'], 0.5)
                self.assertEqual(record['team_detection_tie_break'], condition == 'pool' and
                                 record['human_attack_detected_post'] != record['llm_attack_detected_post'])
                self.assertEqual(record['team_category_tie_break'], condition == 'pool' and
                                 record['human_attack_type_post'] != record['llm_attack_type_post'])
                self.assertEqual(record['human_category_confidence_post'], record['human_detection_confidence_post'])
                self.assertTrue(record['human_category_confidence_inferred_post'])
                self.assertEqual(record['team_score'], int(record['team_decision'] == record['attack_detected_correct_response']) + int(record['team_attack_type'] == record['attack_type_correct_response']))
                self.assertEqual(record['human_attack_detection_correct_pre'],int(settings_for_trial['attack_present']))
                self.assertEqual(record['human_attack_detection_correct_post'],int(not settings_for_trial['attack_present']))
                self.assertEqual(record['ids_rows_revealed'],total//10-1)
                next(b for b in at.button if b.label in ('Next episode','Finish experiment')).click().run()
                self.assertFalse(at.exception)
            self.assertEqual(at.session_state.page,'done')
            with open(Path(tmp)/'test_participant_answers.csv',newline='') as f:
                records=list(csv.DictReader(f))
            self.assertEqual(len(records),9)
            self.assertEqual(len(set(r['trial_id'] for r in records)),9)
            # The stand-in model always says DoS, so it is right on the attack episodes
            # for detection and on the DoS episode alone for the type.
            settings = utils.load_settings()
            for r in records:
                present = settings['trials'][r['trial_id']]['attack_present']
                self.assertEqual(r['llm_assessment_status_pre'], 'ok')
                self.assertEqual(r['llm_post_source'], 'final')
                self.assertEqual(int(r['llm_attack_detection_correct_pre']), int(present))
                self.assertEqual(int(r['llm_attack_type_correct_post']), int(r['trial_id'] == 'dos'))
            with open(Path(tmp)/'test_participant_chat.csv',newline='') as f:
                self.assertEqual(len(list(csv.DictReader(f))),2)


ASSESSMENT = ('Attack: Yes\nAttack type: DoS\nDetection confidence: 80\nCategory confidence: 80\n'
              'Explanation: Rows 41 to 80 flood the web server.')


def fake_reply(content, finish_reason='stop'):
    """The chat server's reply as llm.request_reply returns it."""
    return {'choices': [{'message': {'content': content, 'reasoning_content': '...'},
                         'finish_reason': finish_reason}],
            'usage': {'completion_tokens': 812}, 'hat_mode': 'client'}


def before_reminder(content):
    """A request's text without the style reminder that closes it."""
    return content.rsplit('\n\n', 1)[0]


class FakeModel:
    """Stands in for the server. Answers assessment turns in the format and chat turns
    in prose, and keeps every request it was sent."""

    def __init__(self, assessment=ASSESSMENT, chat='Look at rows 41 to 80.', fail=False):
        self.assessment, self.chat, self.fail = assessment, chat, fail
        self.payloads = []

    def __call__(self, endpoint, payload, timeout):
        self.payloads.append(payload)
        if self.fail:
            raise llm.urllib.error.URLError('connection refused')
        last = payload['messages'][-1]['content']
        return fake_reply(self.assessment if last.startswith(('Phase 1', 'Phase 3')) else self.chat)

    def phase(self, name):
        return [p for p in self.payloads if p['messages'][-1]['content'].startswith(name)]


class CutReplyTest(unittest.TestCase):
    markers = llm.DEFAULTS['turn_end_markers']

    def cut(self, text):
        return llm.cut_reply(text, self.markers)

    def test_invented_participant_turn_is_cut(self):
        text = ('Row 9 failed.\n\n**Participant:** I see. So what now?\n\n**You:** Exactly!')
        self.assertEqual(self.cut(text), ('Row 9 failed.', '**Participant:** I see. So what now?\n\n**You:** Exactly!'))

    def test_other_markers_are_cut_whatever_the_case_or_markdown(self):
        for line in ('Discussion: The participant should focus on rows 48-65.',
                     '### PHASE 2: Discussion', '*(Word count: 119)*',
                     '(Not shown to the participant: keep it short.)', 'you: yes'):
            self.assertEqual(self.cut(f'Rows 1 to 5 are normal.\n{line}'),
                             ('Rows 1 to 5 are normal.', line))

    def test_ordinary_replies_are_left_alone(self):
        for text in ('The participant asked about row 9, and you were right: it failed.',
                     'Look at rows 4 to 6.\nYour point about row 9 is fair.\n- Phase one of a scan is mapping.',
                     ASSESSMENT):
            self.assertEqual(self.cut(text), (text.strip(), ''))

    def test_the_first_line_is_never_cut(self):
        self.assertEqual(self.cut('Participant: is row 9 odd?\nYes.'), ('Participant: is row 9 odd?\nYes.', ''))


class ParseAssessmentTest(unittest.TestCase):
    categories = utils.load_settings()['attack_type_options']

    def parse(self, text):
        return llm.parse_assessment(text, self.categories)

    def test_plain_format(self):
        self.assertEqual(self.parse(ASSESSMENT), {
            'attack_detected': 'Yes', 'attack_type': 'DoS', 'detection_confidence': 80,
            'category_confidence': 80, 'explanation': 'Rows 41 to 80 flood the web server.'})

    def test_markdown_percent_and_out_of_100(self):
        p = self.parse('### Assessment\n**Attack:** Yes\n**Attack type:** Recon\n'
                       '**Detection confidence:** 85%\n**Category confidence:** 70/100\n'
                       '**Explanation:** Rows 3 to 9 sweep ports.\n\nMore detail.')
        self.assertEqual((p['attack_type'], p['detection_confidence'], p['category_confidence']),
                         ('Recon', 85, 70))
        self.assertEqual(p['explanation'], 'Rows 3 to 9 sweep ports.\n\nMore detail.')

    def test_category_wording_is_mapped_to_the_study_label(self):
        for said, label in (('Reconnaissance', 'Recon'), ('DoS (HTTP flood)', 'DoS'),
                            ('c&c beaconing', 'C&C beaconing'), ('Data exfiltration', 'Exfiltration')):
            text = ASSESSMENT.replace('Attack type: DoS', f'Attack type: {said}')
            self.assertEqual(self.parse(text)['attack_type'], label)

    def test_no_attack_forces_none_and_inherits_confidence(self):
        p = self.parse('Attack: No\nAttack type: Recon\nDetection confidence: 65\n'
                       'Category confidence: 20\nExplanation: Ordinary browsing.')
        self.assertEqual((p['attack_type'], p['category_confidence']), ('None', 65))

    def test_unusable_replies_are_rejected(self):
        bad = [
            ASSESSMENT.replace('Attack type: DoS', 'Attack type: Phishing'),
            ASSESSMENT.replace('Detection confidence: 80', 'Detection confidence: 0'),
            ASSESSMENT.replace('Detection confidence: 80', 'Detection confidence: 150'),
            # The format line echoed back unfilled must not read as confidence 1.
            ASSESSMENT.replace('Detection confidence: 80',
                               'Detection confidence: how sure you are, from 1 (barely sure) to 100'),
            ASSESSMENT.replace('Attack type: DoS', 'Attack type: None'),
            ASSESSMENT.split('\nExplanation')[0],
            'Attack: Yes or No\nAttack type: one of DoS, Recon\nDetection confidence: 80',
            'The traffic looks malicious, I am fairly sure.',
        ]
        for text in bad:
            with self.assertRaises(llm.AssessmentFormatError, msg=text):
                self.parse(text)

    def test_every_study_category_is_defined_for_the_model(self):
        turn = (llm.PROMPTS_DIR / 'turn_initial.txt').read_text(encoding='utf-8')
        for category in self.categories:
            if category != 'None':
                self.assertIn(f'- {category}:', turn)


class EpisodeSessionTest(unittest.TestCase):
    def setUp(self):
        self.settings = utils.load_settings()
        self.trial = utils.load_trial('dos')
        self.pre = {'attack_detected': 'No', 'attack_type': 'None',
                    'detection_confidence': 70, 'category_confidence': 70}

    def session(self):
        return llm.EpisodeSession(self.settings, self.trial, 'p1')

    def test_initial_request(self):
        model = FakeModel()
        with patch('llm.request_reply', side_effect=model):
            result = self.session().initial('low_fidelity')
        payload = model.payloads[0]
        self.assertNotIn('mode', payload)
        self.assertEqual(payload['max_tokens'], 4096)
        system, turn = payload['messages']
        self.assertEqual(system['content'], llm.load_prompts()['system_low_fidelity']['text'])
        self.assertTrue(turn['content'].startswith('Phase 1'))
        self.assertIn(f"all {len(self.trial['ids_events'])} rows", turn['content'])
        self.assertIn(self.trial['ids_events'][-1]['ts'], turn['content'])
        self.assertEqual((result['status'], result['attempts'], result['attack_type']), ('ok', 1, 'DoS'))
        self.assertEqual(result['prompt_sha256'], llm.load_prompts()['system_low_fidelity']['sha256'])

    def test_every_request_ends_with_the_reminder_for_its_fidelity(self):
        prompts = llm.load_prompts()
        model = FakeModel()
        with patch('llm.request_reply', side_effect=model):
            session = self.session()
            session.initial('low_fidelity')
            session.chat('Why?', self.pre, 'low_fidelity')
            session.chat('And then?', self.pre, 'high_fidelity')
            session.final('high_fidelity')
        ends = [p['messages'][-1]['content'] for p in model.payloads]
        expected = ['reminder_assessment_low_fidelity', 'reminder_chat_low_fidelity',
                    'reminder_chat_high_fidelity', 'reminder_assessment_high_fidelity']
        for content, name in zip(ends, expected):
            self.assertTrue(content.endswith(prompts[name]['text']), name)
        self.assertIn('And then?', ends[2])

    def test_text_after_the_turn_is_cut_and_kept_for_the_record(self):
        tail = 'Discussion: The participant should focus on rows 41 to 80.'
        model = FakeModel(assessment=f'{ASSESSMENT}\n{tail}',
                          chat='Look at rows 41 to 80.\n\n**Participant:** Why?\n**You:** Because.')
        with patch('llm.request_reply', side_effect=model):
            session = self.session()
            initial = session.initial('low_fidelity')
            reply = session.chat('Why DoS?', self.pre, 'low_fidelity')
        self.assertEqual((initial['status'], initial['attack_type'], initial['cut_text']), ('ok', 'DoS', tail))
        self.assertNotIn('Discussion:', initial['explanation'])
        self.assertEqual(reply['message'], 'Look at rows 41 to 80.')
        self.assertEqual(reply['cut_text'], '**Participant:** Why?\n**You:** Because.')
        # The history the model sees next holds only what the participant saw.
        self.assertEqual(session.messages[-1]['content'], 'Look at rows 41 to 80.')
        self.assertEqual(session.messages[1]['content'], ASSESSMENT.strip())

    def test_unreadable_assessment_is_retried_with_a_new_seed(self):
        replies = iter([fake_reply('I think it is an attack.'), fake_reply(ASSESSMENT)])
        with patch('llm.request_reply', side_effect=lambda *a: next(replies)) as call:
            result = self.session().initial('high_fidelity')
        seeds = [c.args[1]['seed'] for c in call.call_args_list]
        self.assertEqual((result['status'], result['attempts']), ('ok', 2))
        self.assertNotEqual(seeds[0], seeds[1])

    def test_three_failures_give_a_failed_assessment(self):
        with patch('llm.request_reply', return_value=fake_reply('Not the format.')):
            result = self.session().initial('high_fidelity')
        self.assertEqual((result['status'], result['attempts']), ('failed', 3))
        self.assertIn('format', result['error'])
        self.assertEqual(result['raw_message'], 'Not the format.')

    def test_server_down_gives_a_failed_assessment(self):
        with patch('llm.request_reply', side_effect=FakeModel(fail=True)):
            result = self.session().initial('high_fidelity')
        self.assertEqual(result['status'], 'failed')
        self.assertIn('refused', result['error'])

    def test_discussion_then_final(self):
        model = FakeModel()
        session = self.session()
        with patch('llm.request_reply', side_effect=model):
            session.initial('high_fidelity')
            first = session.chat('Why DoS?', self.pre, 'high_fidelity')
            session.chat('And row 50?', self.pre, 'high_fidelity')
            final = session.final('high_fidelity')
        opening = model.payloads[1]['messages'][-1]['content']
        self.assertTrue(opening.startswith('Phase 2'))
        self.assertIn('Attack: No', opening)          # the participant's initial answer
        self.assertEqual(before_reminder(opening).rsplit('\n\n', 1)[-1], 'Why DoS?')
        self.assertEqual(before_reminder(model.payloads[2]['messages'][-1]['content']), 'And row 50?')
        self.assertEqual(first['status'], 'ok')
        final_request = model.phase('Phase 3')[0]['messages']
        # The whole episode so far, in order, and nothing about the final submission.
        self.assertEqual([m['role'] for m in final_request],
                         ['system', 'user', 'assistant', 'user', 'assistant', 'user', 'assistant', 'user'])
        self.assertIn('not shown to you', final_request[-1]['content'])
        self.assertEqual((final['status'], final['attack_detected']), ('ok', 'Yes'))

    def test_failed_chat_reply_is_carried_into_the_next_message(self):
        session = self.session()
        with patch('llm.request_reply', side_effect=FakeModel()):
            session.initial('high_fidelity')
        with patch('llm.request_reply', side_effect=FakeModel(fail=True)):
            failed = session.chat('First question', self.pre, 'high_fidelity')
        model = FakeModel()
        with patch('llm.request_reply', side_effect=model):
            session.chat('Second question', self.pre, 'high_fidelity')
        self.assertEqual((failed['status'], failed['message']), ('error', llm.UNAVAILABLE))
        sent = model.payloads[0]['messages']
        self.assertEqual([m['role'] for m in sent], ['system', 'user', 'assistant', 'user'])
        self.assertTrue(before_reminder(sent[-1]['content']).endswith('First question\n\nSecond question'))

    def test_long_discussion_is_trimmed_but_the_table_is_kept(self):
        model = FakeModel(chat='word ' * 3000)
        session = self.session()
        with patch('llm.request_reply', side_effect=model):
            session.initial('high_fidelity')
            for i in range(12):
                session.chat(f'question {i}', self.pre, 'high_fidelity')
        last = model.payloads[-1]['messages']
        self.assertTrue(last[1]['content'].startswith('Phase 1'))
        self.assertTrue(last[3]['content'].startswith('Phase 2'))
        self.assertEqual(before_reminder(last[-1]['content']), 'question 11')
        self.assertLess(sum(len(m['content']) for m in last), 12000 * 3)
        self.assertLess(len(last), 2 + 2 * 13)


class TeammateInAppTest(unittest.TestCase):
    def start(self, at, consent=True):
        if consent:
            at.text_input[0].set_value('llm_test')
            at.checkbox[0].check()
            at.button[0].click().run()
        at.selectbox(key='initial_attack_detected').select('No').run()
        next(b for b in at.button if b.label == 'Submit Initial Assessment').click().run()

    def submit_and_advance(self, at):
        next(b for b in at.button if b.label == 'Submit Final Assessment').click().run()
        record = dict(at.session_state.feedback_record)
        at.button(key='reveal_results').click().run()
        next(b for b in at.button if b.label == 'Next episode').click().run()
        return record

    def test_two_episodes_two_fresh_sessions(self):
        model = FakeModel()
        with tempfile.TemporaryDirectory(dir='.') as tmp, patch.object(utils, 'DATA_DIR', tmp), \
                patch('llm.request_reply', side_effect=model):
            at = AppTest.from_file('app.py', default_timeout=15).run()
            self.start(at)
            self.assertFalse(at.exception)
            self.assertTrue(any('Rows 41 to 80 flood' in m.value for m in at.markdown))
            self.assertEqual(at.radio(key='fidelity_toggle').value, 'high_fidelity')
            at.radio(key='fidelity_toggle').set_value('low_fidelity').run()
            at.chat_input[0].set_value('Explain please').run()
            self.assertEqual(at.session_state.chat_history[-1]['message'], 'Look at rows 41 to 80.')
            first = self.submit_and_advance(at)
            self.start(at, consent=False)
            second = self.submit_and_advance(at)
            self.assertFalse(at.exception)
            low = llm.load_prompts()['system_low_fidelity']['text']
            self.assertEqual(model.payloads[1]['messages'][0]['content'], low)
            # Each table's first request holds that table and nothing from another episode.
            # A third has already started: advancing loads episode 3, which begins at once.
            initials = model.phase('Phase 1')
            self.assertEqual([len(p['messages']) for p in initials], [2, 2, 2])
            tables = [utils.load_trial(r['trial_id'])['ids_events'] for r in (first, second)]
            for payload, rows in zip(initials, tables):
                self.assertIn(llm.table_csv(rows), payload['messages'][1]['content'])
            self.assertEqual(len(model.phase('Phase 3')), 2)
            for record in (first, second):
                self.assertEqual(record['llm_post_source'], 'final')
                self.assertEqual(record['llm_attack_detected_post'], 'Yes')
                self.assertEqual(record['llm_assessment_status_pre'], 'ok')
            self.assertEqual(first['llm_fidelity_pre'], 'high_fidelity')
            self.assertEqual(first['llm_fidelity_post'], 'low_fidelity')
            self.assertEqual(second['llm_fidelity_pre'], 'low_fidelity')
            with open(Path(tmp) / 'llm_test_chat.csv', newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([r['fidelity'] for r in rows], ['', 'low_fidelity'])
            self.assertEqual(rows[1]['prompt_sha256'], llm.load_prompts()['system_low_fidelity']['sha256'])

    def test_model_unavailable_leaves_the_decision_to_the_participant(self):
        with tempfile.TemporaryDirectory(dir='.') as tmp, patch.object(utils, 'DATA_DIR', tmp), \
                patch('llm.request_reply', side_effect=FakeModel(fail=True)), \
                patch('utils.get_next_condition', return_value='pool'):
            at = AppTest.from_file('app.py', default_timeout=15).run()
            self.start(at)
            self.assertTrue(any('could not give an assessment' in m.value for m in at.markdown))
            self.assertTrue(at.chat_input[0].disabled)
            next(b for b in at.button if b.label == 'Submit Final Assessment').click().run()
            self.assertFalse(at.exception)
            record = at.session_state.feedback_record
            self.assertEqual(record['llm_post_source'], 'unavailable')
            self.assertEqual(record['aggregation_method'], 'human_only_llm_unavailable')
            self.assertEqual(record['team_decision'], 'No')
            at.button(key='reveal_results').click().run()
            self.assertTrue(any('teammate was unavailable' in m.value for m in at.markdown))

    def test_failed_final_call_falls_back_to_the_initial_assessment(self):
        model = FakeModel()
        with tempfile.TemporaryDirectory(dir='.') as tmp, patch.object(utils, 'DATA_DIR', tmp), \
                patch('llm.request_reply', side_effect=model):
            at = AppTest.from_file('app.py', default_timeout=15).run()
            self.start(at)
            model.assessment = 'No format at all.'
            next(b for b in at.button if b.label == 'Submit Final Assessment').click().run()
            record = at.session_state.feedback_record
            self.assertEqual(record['llm_post_source'], 'initial')
            self.assertEqual(record['llm_assessment_status_post'], 'failed')
            self.assertEqual(record['llm_attack_detected_post'], 'Yes')
            self.assertEqual(record['llm_attempts_post'], 3)


if __name__=='__main__':
    unittest.main()
