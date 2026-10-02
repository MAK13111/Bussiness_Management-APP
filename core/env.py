"""Loads variables from the project's .env file into os.environ.

Real environment variables always win over values in .env, so a value set in
the shell (or by a hosting panel) is never overwritten by the file.
"""
import os

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH, override=False)
except ImportError:
    if os.path.exists(ENV_PATH):
        print("[env] .env found but python-dotenv is not installed -- it was ignored. "
              "Install with: pip install python-dotenv")