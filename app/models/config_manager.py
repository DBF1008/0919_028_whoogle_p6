import copy
import json
import logging
import os
import threading

from flask import current_app

from app.models.config import Config

logger = logging.getLogger(__name__)


class ConfigManager:
    """Builds validated user configs and caches instance defaults.

    Responsibilities:
      * cache the on-disk default config (DEFAULT_CONFIG) so it is not
        re-read from disk on every request
      * construct per-user Config instances from session config and
        request parameters, with all user-supplied values validated and
        sanitized by Config
      * keep instance-level (immutable) configuration separated from
        user-mutable configuration
    """

    def __init__(self, default_config_path: str = None):
        self._default_config_path = default_config_path
        self._cache = None
        self._cache_mtime = None
        self._lock = threading.Lock()

    @property
    def default_config_path(self):
        if self._default_config_path:
            return self._default_config_path
        try:
            return current_app.config['DEFAULT_CONFIG']
        except RuntimeError:
            return None

    def get_default_config(self) -> dict:
        """Returns a copy of the default config.

        The parsed file is cached and only re-read when the file's mtime
        changes. Returns an empty dict if the file is missing or invalid.
        """
        path = self.default_config_path
        if not path or not os.path.exists(path):
            return {}

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return {}

        with self._lock:
            if self._cache is None or self._cache_mtime != mtime:
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        logger.warning(
                            'Default config at %s is not a JSON object; '
                            'ignoring it', path)
                        data = {}
                except (OSError, ValueError) as e:
                    logger.warning(
                        'Failed to load default config from %s: %s', path, e)
                    data = {}
                self._cache = data
                self._cache_mtime = mtime
            # Return a deep copy so callers can never mutate the cache
            return copy.deepcopy(self._cache)

    def reset_cache(self):
        """Drops the cached default config (mainly useful for tests)."""
        with self._lock:
            self._cache = None
            self._cache_mtime = None

    def build_user_config(self, session_config: dict = None,
                          request_params=None) -> Config:
        """Creates a validated per-user Config.

        Args:
            session_config (dict) -- config values persisted in the user
                session (originally seeded from the default config)
            request_params -- URL/form parameters for search-by-search
                config overrides

        Returns:
            Config -- a config with validated user values applied
        """
        config = Config()
        if session_config:
            # Mirror the historical Config(**session_config) semantics:
            # user bool options absent from the session config are treated
            # as disabled (e.g. unchecked checkboxes in the config form).
            # Instance-level (immutable) options always keep their
            # environment-derived values.
            for attr, attr_type in config.get_mutable_attrs().items():
                if (attr_type is bool
                        and attr not in session_config
                        and attr not in Config.IMMUTABLE_ATTRS):
                    setattr(config, attr, False)
            config.apply_user_config(session_config)
        if request_params:
            config.from_params(request_params)
        return config


# Shared singleton used by the request handlers
config_manager = ConfigManager()
