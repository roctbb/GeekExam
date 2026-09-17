import unittest
from types import SimpleNamespace

from routes.attempts import _topic_summary


class TopicSummaryTest(unittest.TestCase):
    def summary(self, topics):
        questions = [SimpleNamespace(
            id=index, title=topic, ui_config={'topic': topic},
            check_type='ai', type='text_input', check_config={}, max_points=10,
        ) for index, topic in enumerate(topics)]
        answers = [SimpleNamespace(
            question_id=question.id, check_state='checked', points=5, value={},
        ) for question in questions]
        return _topic_summary(SimpleNamespace(
            variant=SimpleNamespace(questions=questions), answers=answers,
        ))

    def test_numbered_topics_use_numeric_order(self):
        result = self.summary(['10', '2', '11', '1', '9'])
        self.assertEqual([row['topic'] for row in result], ['1', '2', '9', '10', '11'])

    def test_numbers_inside_titles_and_subtopics(self):
        topics = ['Тема 10', 'Тема 2.10', 'Тема 2.2', 'Тема 1', 'Тема 2']
        result = self.summary(topics)
        self.assertEqual([row['topic'] for row in result], [
            'Тема 1', 'Тема 2', 'Тема 2.2', 'Тема 2.10', 'Тема 10',
        ])

    def test_sorting_preserves_totals_and_percentages(self):
        result = self.summary(['Тема 10', 'Тема 2', 'Тема 2'])
        self.assertEqual(result[0], {
            'topic': 'Тема 2', 'points': 10, 'max_points': 20,
            'percent': 50, 'correct': 0, 'total': 2,
        })
        self.assertEqual(self.summary([]), [])

    def test_exact_text_uses_recorded_grade_after_teacher_override(self):
        question = SimpleNamespace(
            id=1, title='Путь по ступеням', ui_config={'topic': 'Прямая рекурсия'},
            check_type='exact', type='text_input',
            check_config={'answer': '2 1 0 0 1 2', 'normalize_whitespace': True}, max_points=2,
        )
        answer = SimpleNamespace(
            question_id=1, check_state='checked', points=2, value={'text': '210012'},
        )
        attempt = SimpleNamespace(variant=SimpleNamespace(questions=[question]), answers=[answer])
        row = _topic_summary(attempt)[0]
        self.assertEqual((row['points'], row['percent'], row['correct']), (2, 100, 1))

        # A recorded deduction must also survive a literal match with the reference.
        answer.value = {'text': '2 1 0 0 1 2'}
        answer.points = 0
        row = _topic_summary(attempt)[0]
        self.assertEqual((row['points'], row['percent'], row['correct']), (0, 0, 0))


if __name__ == '__main__':
    unittest.main()
