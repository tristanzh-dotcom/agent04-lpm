import unittest


class BackendMainCompatTests(unittest.TestCase):
    def test_backend_main_exports_current_fastapi_app(self):
        from backend import ark_main
        from backend import main

        self.assertIs(main.app, ark_main.app)


if __name__ == "__main__":
    unittest.main()
