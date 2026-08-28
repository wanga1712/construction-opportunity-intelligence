import unittest
from streamlit.testing.v1 import AppTest

class TestStreamlitRoute(unittest.TestCase):
    def test_app_compilation_and_rendering(self):
        at = AppTest.from_file("app.py", default_timeout=30)
        at.run()
        if at.exception:
            raise RuntimeError(f"Streamlit AppTest Exception: {at.exception}")
        print("Streamlit AppTest PASSED successfully.")

if __name__ == "__main__":
    unittest.main()
