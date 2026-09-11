import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[3]/'scripts'/'evaluate_qa.py'
spec=importlib.util.spec_from_file_location('evaluate_qa',path)
evaluation=importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class EvaluationTests(unittest.TestCase):
    def test_automatic_checks_do_not_claim_accuracy(self):
        report=evaluation.metrics([{'id':'a','answerable':True}],
                                  [{'id':'a','response':{'answer_status':'answered','answer':'答案'}}])
        self.assertEqual(report['automatic_check_rate'],1)
        self.assertIsNone(report['expert_end_to_end_accuracy'])
        self.assertFalse(report['accepted'])

    def test_refusal_does_not_inflate_answerable_accuracy(self):
        response={'answer_status':'insufficient','answer':'不知道'}
        report=evaluation.metrics([{'id':'a','answerable':True}], [{'id':'a','response':response}],
            [{'id':'a','correct':True,'reviewer':'专家','answer_hash':evaluation.answer_hash(response)}],minimum=1)
        self.assertEqual(report['expert_end_to_end_accuracy'],0)

    def test_stale_annotation_cannot_pass_changed_answer(self):
        original={'answer_status':'answered','answer':'100元'}
        changed={**original,'answer':'200元'}
        report=evaluation.metrics([{'id':'a','answerable':True}], [{'id':'a','response':changed}],
            [{'id':'a','correct':True,'reviewer':'专家','answer_hash':evaluation.answer_hash(original)}],minimum=1)
        self.assertEqual(report['expert_reviewed'],0)

    def test_strictly_above_90_percent_on_at_least_100_cases(self):
        response={'answer_status':'answered','answer':'答案'}
        cases=[{'id':str(i),'answerable':True} for i in range(100)]
        results=[{'id':c['id'],'response':response} for c in cases]
        grades=[{'id':str(i),'correct':i<90,'reviewer':'专家','answer_hash':evaluation.answer_hash(response)} for i in range(100)]
        self.assertFalse(evaluation.metrics(cases,results,grades)['accepted'])
        grades[90]['correct']=True
        self.assertTrue(evaluation.metrics(cases,results,grades)['accepted'])


if __name__=='__main__':
    unittest.main()
