import os
import sys
import hashlib
import hmac


class AuthManager:
    USERNAME_ENV_KEYS = ("VISION_ADMIN_USERNAME", "ADMIN_USERNAME")
    PASSWORD_ENV_KEYS = ("VISION_ADMIN_PASSWORD", "ADMIN_PASSWORD")
    DEV_USERNAME_ENV_KEYS = ("VISION_DEV_USERNAME", "DEV_USERNAME")
    DEV_PASSWORD_ENV_KEYS = ("VISION_DEV_PASSWORD", "DEV_PASSWORD")

    ROLE_ADMIN = "admin"
    ROLE_DEV = "dev"

    def __init__(self):
        env_overrides = self._load_dotenv()
        self.username = self._read_env(self.USERNAME_ENV_KEYS, env_overrides) or "admin"
        raw_password = self._read_env(self.PASSWORD_ENV_KEYS, env_overrides)
        self.password_hash = self._hash_text(raw_password) if raw_password else None
        self.dev_username = self._read_env(self.DEV_USERNAME_ENV_KEYS, env_overrides)
        raw_dev = self._read_env(self.DEV_PASSWORD_ENV_KEYS, env_overrides)
        self.dev_password_hash = self._hash_text(raw_dev) if raw_dev else None

    def _env_path(self):
        if getattr(sys, "frozen", False):
            if sys.platform == "darwin":
                # macOS .app: Contents/MacOS/INNOVIS → go up 4 levels to reach folder next to .app
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.dirname(sys.executable)
                )))
            else:
                # Windows/Linux: dist/INNOVIS/INNOVIS.exe → .env lives next to .exe
                base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, ".env")

    def _load_dotenv(self):
        env_path = self._env_path()
        if not os.path.exists(env_path):
            return {}

        overrides = {}
        try:
            with open(env_path, "r", encoding="utf-8") as file:
                for raw_line in file:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue

                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key:
                        overrides[key] = value
        except OSError:
            return overrides
        return overrides

    def _read_env(self, keys, overrides):
        for key in keys:
            value = os.getenv(key)
            if value:
                return value
            value = overrides.get(key)
            if value:
                return value
        return None

    def _hash_text(self, text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def is_configured(self):
        return self.password_hash is not None

    def verify(self, username, password):
        """Return role string ('admin' or 'dev') on success, None on failure."""
        if not self.is_configured():
            return None
        pw_hash = self._hash_text(password)
        username_stripped = username.strip()

        if hmac.compare_digest(username_stripped, self.username) and \
                hmac.compare_digest(pw_hash, self.password_hash):
            return self.ROLE_ADMIN

        if self.dev_username and self.dev_password_hash and \
                hmac.compare_digest(username_stripped, self.dev_username) and \
                hmac.compare_digest(pw_hash, self.dev_password_hash):
            return self.ROLE_DEV

        return None

    def set_admin_credentials(self, username, password=None):
        """Update admin username and/or password in .env. Returns (ok, message)."""
        env_path = self._env_path()
        try:
            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            lines = self._set_env_line(lines, "VISION_ADMIN_USERNAME", username)
            if password:
                lines = self._set_env_line(lines, "VISION_ADMIN_PASSWORD", password)

            tmp_path = env_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(tmp_path, env_path)

            self.username = username
            if password:
                self.password_hash = self._hash_text(password)
            return True, "OK"
        except OSError as exc:
            return False, str(exc)

    @staticmethod
    def _set_env_line(lines, key, value):
        new_line = f"{key}={value}\n"
        for i, line in enumerate(lines):
            if line.startswith(key + "=") or line.startswith(key + " ="):
                lines[i] = new_line
                return lines
        lines.append(new_line)
        return lines
