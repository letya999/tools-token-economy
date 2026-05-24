import pytest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.features.google_oauth_service import GoogleOAuthService

@pytest.fixture
def google_oauth_service():
    return GoogleOAuthService()
