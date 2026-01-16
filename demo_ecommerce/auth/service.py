import hashlib
import time
from typing import Optional

class AuthService:
    """
    Handles user authentication and session management.
    """
    def __init__(self):
        self._user_db = {}
        self._sessions = {}

    def register(self, username, password):
        """Registers a new user with a hashed password."""
        if username in self._user_db:
            raise ValueError("User already exists")
        salt = str(time.time())
        hashed = hashlib.sha256((password + salt).encode()).hexdigest()
        self._user_db[username] = {"hash": hashed, "salt": salt}
        return True

    def login(self, username, password) -> Optional[str]:
        """Authenticates a user and returns a session token."""
        user = self._user_db.get(username)
        if not user:
            return None
        
        check_hash = hashlib.sha256((password + user["salt"]).encode()).hexdigest()
        if check_hash == user["hash"]:
            token = f"sess_{int(time.time())}_{username}"
            self._sessions[token] = username
            return token
        return None

    def validate_session(self, token: str) -> bool:
        """Checks if a session token is valid."""
        return token in self._sessions
