import unittest

from tests.test_ark_connectivity import extract_usage, is_red_answer, render_failure_guide


class ArkConnectivityUnitTests(unittest.TestCase):
    def test_is_red_answer_accepts_red_variants(self):
        self.assertTrue(is_red_answer("红色"))
        self.assertTrue(is_red_answer("红"))
        self.assertTrue(is_red_answer("主色调：红色"))

    def test_extract_usage_reads_token_counts(self):
        usage = type("Usage", (), {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15})()
        response = type("Response", (), {"usage": usage})()

        self.assertEqual(extract_usage(response), (12, 3, 15))

    def test_failure_guide_mentions_auth_and_rate_limit(self):
        self.assertIn("认证", render_failure_guide(Exception("401 Unauthorized")))
        self.assertIn("限流", render_failure_guide(Exception("429 Rate Limit Exceeded")))


if __name__ == "__main__":
    unittest.main()
