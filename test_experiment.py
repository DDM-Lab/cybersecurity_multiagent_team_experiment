import tempfile
from pathlib import Path
from unittest.mock import patch
import csv
import unittest
import utils
from decision import round_probability_to_decision
from streamlit.testing.v1 import AppTest

class ExperimentTest(unittest.TestCase):
    def test_plan_and_tables(self):
        settings=utils.load_settings()
        for _ in range(20):
            order, ai=utils.create_trial_plan(settings)
            self.assertEqual(set(order),set(settings['trial_order']))
            self.assertEqual(sum(a['attack_probability']>50 for a in ai.values()),3)
            self.assertEqual(sum(a['attack_type']==settings['trials'][i]['attack_type'] for i,a in ai.items()),3)
        self.assertEqual(round_probability_to_decision(50),'No')
        self.assertEqual(round_probability_to_decision(51),'Yes')
        for i in settings['trial_order']:
            rows=utils.load_trial(i)['ids_events']
            self.assertNotIn('malicious', rows[0])
            self.assertEqual(len(rows),len(utils.load_labeled_table(i)))
        with patch('utils.random.choice',return_value='pool'):
            self.assertEqual(utils.get_next_condition(),'pool')

    def test_feedback_outcomes_and_sources(self):
        settings = utils.load_settings()
        order, assessments = utils.create_trial_plan(settings)
        record = {f"{source}_{measure}_correct_{stage}": 1
                  for source in ("human", "llm")
                  for measure in ("attack_detection", "attack_type")
                  for stage in ("pre", "post")}
        cases = [
            ("leader", "human", "human", "Your final judgment determined"),
            ("pool", "human", "human", "your confidence was higher"),
            ("pool", "llm", "llm", "its confidence was higher"),
            ("pool", "tie_breaker", "human", "selected your judgment"),
            ("pool", "tie_breaker", "llm", "selected the AI teammate's judgment"),
        ]
        for condition, chosen, selected, expected in cases:
            for detection_correct, type_correct in ((0, 0), (0, 1), (1, 0), (1, 1)):
                correct = detection_correct
                score = detection_correct + type_correct
                record.update(team_score=score, team_attack_detection_correct=detection_correct,
                              team_attack_type_correct=type_correct, team_attack_type="Recon")
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
                self.assertTrue(any(("Attack detected" if correct else "Missed attack") in element.value
                                    for element in at.markdown))

    def test_six_trial_flow(self):
        with tempfile.TemporaryDirectory(dir='.') as tmp, patch.object(utils,'DATA_DIR',tmp):
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
                    at.selectbox(key='initial_attack_type').select('Other').run()
                    next(b for b in at.button if b.label=='Submit Initial Assessment').click().run()
                    self.assertTrue(at.error)
                    at.text_input(key='initial_other').set_value('Recon')
                else:
                    at.selectbox(key='initial_attack_type').select(utils.load_settings()['trials'][trial_id]['attack_type'])
                at.slider(key='initial_attack_probability').set_value(51)
                next(b for b in at.button if b.label=='Submit Initial Assessment').click().run()
                self.assertFalse(at.exception)
                if n==0:
                    self.assertEqual(at.text_input(key='post_other').value,'Recon')
                    at.chat_input[0].set_value('What do you think?').run()
                    self.assertEqual(len(at.session_state.chat_history),2)
                at.slider(key='post_attack_probability').set_value(50)
                next(b for b in at.button if b.label=='Submit Final Assessment').click().run()
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state.page,'episode_complete')
                self.assertEqual(len(at.dataframe),0)
                self.assertEqual(len(at.table),0)
                self.assertEqual(len(at.expander),0)
                self.assertEqual(len(at.button),1)
                at.button(key='reveal_results').click().run()
                self.assertEqual(at.session_state.page,'feedback')
                self.assertEqual(len(at.table),1)
                self.assertEqual(at.expander[0].label,'Review labeled IDS events')
                self.assertFalse(at.expander[0].proto.expanded)
                self.assertFalse(any('saved to:' in element.value for element in at.markdown))
                self.assertFalse(at.exception)
                self.assertEqual(len(at.dataframe[-1].value),total)
                self.assertIn('malicious',at.dataframe[-1].value.columns)
                record=at.session_state.feedback_record
                source = record['team_selected_source']
                self.assertEqual(record['team_score'], record[f'{source}_attack_detection_correct_post'] + record[f'{source}_attack_type_correct_post'])
                self.assertEqual(record['human_attack_detection_correct_pre'],1)
                self.assertEqual(record['human_attack_detection_correct_post'],0)
                self.assertEqual(record['ids_rows_revealed'],total//10-1)
                next(b for b in at.button if b.label in ('Next episode','Finish experiment')).click().run()
                self.assertFalse(at.exception)
            self.assertEqual(at.session_state.page,'done')
            with open(Path(tmp)/'test_participant_answers.csv',newline='') as f:
                records=list(csv.DictReader(f))
            self.assertEqual(len(records),6)
            self.assertEqual(len(set(r['trial_id'] for r in records)),6)
            self.assertEqual(sum(int(r['llm_attack_detection_correct_pre']) for r in records),3)
            self.assertEqual(sum(int(r['llm_attack_type_correct_pre']) for r in records),3)
            with open(Path(tmp)/'test_participant_chat.csv',newline='') as f:
                self.assertEqual(len(list(csv.DictReader(f))),2)

if __name__=='__main__':
    unittest.main()
