import json
import logging
import os
import threading

from app.models.config import Config, FALSE_STRINGS

logger = logging.getLogger(__name__)

# String values interpreted as truthy booleans in user-supplied config
# data (e.g. HTML checkboxes submit "on" when checked).
TRUE_STRINGS = ('1', 'on', 'true', 'yes')


class ConfigManager:
    """Loads, caches, and sanitizes Whoogle configuration.

    The default configuration (``config.json`` on disk) is cached in
    memory and only re-read when the file changes, which avoids disk IO
    on every request. User-supplied configuration (session config and
    URL parameters) is validated and sanitized before being applied to
    a ``Config`` instance.
    """

    def __init__(self, config_path: str = ''):
        self.config_path = config_path
        self._lock = threading.Lock()
        self._cached_config = None
        self._cached_mtime = None

    def get_default_config(self) -> dict:
        """Returns a copy of the default config, reading it from disk
        only when the file has changed since the last read.

        Returns:
            dict -- the default config (empty dict if none is set)
        """
        if not self.config_path or not os.path.exists(self.config_path):
            return {}

        try:
            mtime = os.path.getmtime(self.config_path)
        except OSError:
            return {}

        with self._lock:
            if self._cached_config is None or mtime != self._cached_mtime:
                self._cached_config = self._read_default_config()
                self._cached_mtime = mtime
            return dict(self._cached_config)

    def reload(self):
        """Invalidates the cached default config, forcing the next read
        to load it from disk again."""
        with self._lock:
            self._cached_config = None
            self._cached_mtime = None

    def build_user_config(self, session_config: dict = None,
                          params=None) -> Config:
        """Builds a validated user config from session config values and
        optional URL parameters.

        Args:
            session_config (dict) -- config values stored in the session
            params -- optional URL parameters to apply on top

        Returns:
            Config -- the sanitized user config
        """
        config = Config(**self.sanitize_config(session_config or {}))
        if params:
            config = config.from_params(params)
        return config

    @staticmethod
    def sanitize_config(config_data: dict) -> dict:
        """Filters a config dictionary down to known, user-mutable keys
        with correctly typed values. Instance-level (immutable) settings
        and malformed entries are dropped with a warning.

        Args:
            config_data (dict) -- raw config values (e.g. from a session
                or a config file)

        Returns:
            dict -- the sanitized config values
        """
        if not isinstance(config_data, dict):
            logger.warning(
                'Ignoring non-dictionary config data: '
                f'{type(config_data).__name__}')
            return {}

        sanitized = {}
        mutable_attrs = Config.MUTABLE_ATTR_TYPES
        for key, value in config_data.items():
            if key in Config.INSTANCE_ATTRS:
                logger.warning(
                    f'Ignoring instance-level config key "{key}" from '
                    'user-supplied config data')
                continue
            expected_type = mutable_attrs.get(key)
            if expected_type is None:
                continue
            if expected_type is bool:
                value = ConfigManager._coerce_bool(key, value)
                if value is None:
                    continue
            elif not isinstance(value, expected_type):
                logger.warning(
                    f'Ignoring config key "{key}": expected '
                    f'{expected_type.__name__}, got '
                    f'{type(value).__name__}')
                continue
            sanitized[key] = value
        return sanitized

    @staticmethod
    def _coerce_bool(key, value):
        """Coerces a user-supplied value to a boolean. Returns None if
        the value cannot be interpreted as a boolean."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in TRUE_STRINGS:
                return True
            if normalized in FALSE_STRINGS:
                return False
        elif isinstance(value, int):
            return bool(value)
        logger.warning(
            f'Ignoring config key "{key}": cannot interpret '
            f'{value!r} as a boolean')
        return None

    def _read_default_config(self) -> dict:
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            logger.warning(
                f'Unable to load default config from '
                f'{self.config_path}: {e}')
            return {}

        if not isinstance(data, dict):
            logger.warning(
                f'Default config at {self.config_path} is not a JSON '
                'object, ignoring it')
            return {}

        return self.sanitize_config(data)
