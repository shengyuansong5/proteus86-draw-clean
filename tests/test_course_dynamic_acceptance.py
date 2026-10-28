"""Check that the native coursework acceptance rejects realistic wrong behavior.

These are offline tests of the assertions, not native simulation evidence.
"""
import unittest

from scripts.verify_course_dynamic import PROBES, evaluate, make_scene
from proteus86.scenarios import timeline


def sample(at, mask, board=True):
    bits = [(mask >> i) & 1 for i in range(8)]
    if not board:
        bits = [1 - value for value in bits]
    return dict(actual_at=at, probes=dict(zip(PROBES, bits)))


class CourseDynamicAssertions(unittest.TestCase):
    def test_all_scenes_preserve_native_timing_guard(self):
        for name in ('03_KeyModes', '04_Debounce', '05_Interactive'):
            with self.subTest(name=name):
                scene, until, step = make_scene(name)
                frames = timeline(scene, until, step, tolerance=.003)
                self.assertEqual(sum(frame['sample'] for frame in frames), round(until / step) + 1)

    def debounce_samples(self, board=True):
        return [sample(i / 50, 1 if i / 50 < .72 else 2 if i / 50 < 1.48 else 4, board)
                for i in range(81)]

    def test_debounce_two_clicks_and_both_polarities(self):
        for board in (False, True):
            result = evaluate('04_Debounce', self.debounce_samples(board), board)
            self.assertTrue(result['passed'])
            self.assertEqual(result['details']['accepted_clicks'], 2)

    def test_short_pulse_response_and_repeated_hold_fail(self):
        for at in (.04, .4, 1.0):
            samples = self.debounce_samples()
            samples[round(at * 50)] = sample(at, 8)
            self.assertFalse(evaluate('04_Debounce', samples, True)['passed'])

    def test_missing_release_response_fails(self):
        samples = [sample(i / 50, 1) for i in range(81)]
        self.assertFalse(evaluate('04_Debounce', samples, True)['passed'])

    def interactive_samples(self, wrong_direction=False, wrong_speed=False):
        times = [0, .1, .25, .4, .55, .7, .85, 1, 1.15, 1.45, 1.75,
                 1.925, 2, 2.075, 2.15, 2.225, 2.3, 2.375, 2.45, 2.525, 2.6,
                 2.75, 2.9, 3.05, 3.2]
        if wrong_speed:
            times[times.index(1.75)] = 1.6
        index, samples = 0, []
        for position, at in enumerate(times):
            if position:
                index = (index + (1 if at < .5 or wrong_direction else -1)) % 8
            samples.append(sample(at, 1 << index))
        return samples

    def test_interactive_requires_direction_and_three_speeds(self):
        self.assertTrue(evaluate('05_Interactive', self.interactive_samples(), True)['passed'])
        self.assertFalse(evaluate('05_Interactive', self.interactive_samples(wrong_direction=True), True)['passed'])
        self.assertFalse(evaluate('05_Interactive', self.interactive_samples(wrong_speed=True), True)['passed'])

    def test_empty_or_nonbinary_observations_never_pass(self):
        for name in ('03_KeyModes', '04_Debounce', '05_Interactive'):
            self.assertFalse(evaluate(name, [], True)['passed'])
        bad = sample(0, 1)
        bad['probes']['Q0'] = '1'
        with self.assertRaises(ValueError):
            evaluate('04_Debounce', [bad], True)


if __name__ == '__main__':
    unittest.main()
