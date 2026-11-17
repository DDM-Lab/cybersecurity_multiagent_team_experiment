import tempfile
from pathlib import Path
from unittest.mock import patch
import csv
import unittest
from itertools import product
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
            order, ai=utils.create_trial_plan(settings)
            self.assertEqual(set(order),set(settings['trial_order']))
            self.assertIn(sum((a['attack_detected']=='Yes')==settings['trials'][i]['attack_present'] for i,a in ai.items()),(4,5))
            self.assertEqual(sum(a['attack_type']==settings['trials'][i]['attack_type'] for i,a in ai.items()), sum((a['attack_detected']=='Yes')==settings['trials'][i]['attack_present'] for i,a in ai.items()))
        for i in settings['trial_order']:
            rows=utils.load_trial(i)['ids_events']
            self.assertNotIn('malicious', rows[0])
            self.assertEqual(len(rows),len(utils.load_labeled_table(i)))
        with patch('utils.random.choice',return_value='pool'):
            self.assertEqual(utils.get_next_condition(),'pool')

    def test_feedback_outcomes_and_sources(self):
        settings = utils.load_settings()
        order, assessments = utils.create_trial_plan(settings)
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
                    llm_assessments=assessments, feedback_record=record,
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
        with tempfile.TemporaryDirectory(dir='.') as tmp, patch.object(utils, 'DATA_DIR', tmp):
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
        with tempfile.TemporaryDirectory(dir='.') as tmp, patch.object(utils,'DATA_DIR',tmp), patch('utils.get_next_condition', return_value=assigned_condition):
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
            self.assertIn(sum(int(r['llm_attack_detection_correct_pre']) for r in records),(4,5))
            self.assertEqual(sum(int(r['llm_attack_type_correct_pre']) for r in records),sum(int(r['llm_attack_detection_correct_pre']) for r in records))
            with open(Path(tmp)/'test_participant_chat.csv',newline='') as f:
                self.assertEqual(len(list(csv.DictReader(f))),2)

if __name__=='__main__':
    unittest.main()
