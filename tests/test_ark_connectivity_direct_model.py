import asyncio
import unittest
from types import SimpleNamespace

from tests.test_ark_connectivity import _create_completion


class ConnectivityDirectModelTests(unittest.TestCase):
    def test_create_completion_uses_endpoint_id(self):
        class FakeCompletions:
            def __init__(self):
                self.kwargs = None

            async def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(choices=[])

        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        asyncio.run(_create_completion(client, "ep-production", "data:image/png;base64,abc"))

        self.assertEqual(completions.kwargs["model"], "ep-production")


if __name__ == "__main__":
    unittest.main()
