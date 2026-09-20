from inspect import Attribute
from typing import Optional
from app.utils.misc import read_config_bool
from flask import current_app
import os
import re
from base64 import urlsafe_b64encode, urlsafe_b64decode
from cryptography.fernet import Fernet, InvalidToken
import hashlib
import brotli
import logging
import json

import cssutils
from cssutils.css.cssstylesheet import CSSStyleSheet
from cssutils.css.cssstylerule import CSSStyleRule

# removes warnings from cssutils
cssutils.log.setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

# Sentinel used to signal that a parameter value failed validation and
# must be discarded instead of being applied to the config.
INVALID_PARAM = object()

# Valid values for the 'tbs' (time period) search parameter, optionally
# followed by additional comma-separated filter segments (e.g. lr:lang_1).
TBS_PATTERN = re.compile(r'^(qdr:[hdwmy](,[a-z]+:[A-Za-z0-9_-]+)*)?$')

# Maximum accepted length for string parameters coming from the URL or
# from decoded preferences. Anything longer is rejected as malformed.
MAX_PARAM_VALUE_LENGTH = 512

# String values that should be interpreted as a falsy boolean when they
# arrive as URL parameters.
FALSE_STRINGS = ('', '0', 'off', 'false', 'no')


def get_rule_for_selector(stylesheet: CSSStyleSheet,
                          selector: str) -> Optional[CSSStyleRule]:
    """Search for a rule that matches a given selector in a stylesheet.

    Args:
        stylesheet (CSSStyleSheet) -- the stylesheet to search
        selector (str) -- the selector to search for

    Returns:
        Optional[CSSStyleRule] -- the rule that matches the selector or None
    """
    for rule in stylesheet.cssRules:
        if hasattr(rule, "selectorText") and selector == rule.selectorText:
            return rule
    return None


class Config:
    # Instance-level attributes that are derived from the server
    # environment only. They are immutable for end users: they can never
    # be overridden through session config (kwargs) or URL parameters.
    # Everything not listed here (and of type bool/str) is considered
    # user-mutable configuration.
    INSTANCE_ATTRS = frozenset([
        'preferences_key',
    ])

    # Declarative types for all user-mutable (bool/str) config attributes.
    # Allows validating user-supplied config data without instantiating
    # a Config first.
    MUTABLE_ATTR_TYPES = {
        'user_agent': str,
        'custom_user_agent': str,
        'use_custom_user_agent': bool,
        'show_user_agent': bool,
        'url': str,
        'lang_search': str,
        'lang_interface': str,
        'style_modified': str,
        'block': str,
        'block_title': str,
        'block_url': str,
        'country': str,
        'tbs': str,
        'theme': str,
        'safe': bool,
        'alts': bool,
        'nojs': bool,
        'tor': bool,
        'near': str,
        'new_tab': bool,
        'view_image': bool,
        'get_only': bool,
        'anon_view': bool,
        'preferences_encrypted': bool,
        'cse_api_key': str,
        'cse_id': str,
        'use_cse': bool,
        'accept_language': bool,
    }

    def __init__(self, **kwargs):
        # User agent configuration - default to env_conf if environment variables exist, otherwise default
        env_user_agent = os.getenv('WHOOGLE_USER_AGENT', '')
        env_mobile_agent = os.getenv('WHOOGLE_USER_AGENT_MOBILE', '')
        default_ua_option = 'env_conf' if (env_user_agent or env_mobile_agent) else 'default'
        
        self.user_agent = kwargs.get('user_agent', default_ua_option)
        self.custom_user_agent = kwargs.get('custom_user_agent', '')
        self.use_custom_user_agent = kwargs.get('use_custom_user_agent', False)
        self.show_user_agent = read_config_bool('WHOOGLE_CONFIG_SHOW_USER_AGENT')

        # Add user agent related keys to safe_keys
        # Note: CSE credentials (cse_api_key, cse_id) are intentionally NOT included
        # in safe_keys for security - they should not be shareable via URL
        self.safe_keys = [
            'lang_search',
            'lang_interface',
            'country',
            'theme',
            'alts',
            'new_tab',
            'view_image',
            'block',
            'safe',
            'nojs',
            'anon_view',
            'preferences_encrypted',
            'tbs',
            'user_agent',
            'custom_user_agent',
            'use_custom_user_agent',
            'show_user_agent'
        ]

        app_config = current_app.config
        self.url = os.getenv('WHOOGLE_CONFIG_URL', '')
        self.lang_search = os.getenv('WHOOGLE_CONFIG_SEARCH_LANGUAGE', '')
        self.lang_interface = os.getenv('WHOOGLE_CONFIG_LANGUAGE', '')
        self.style_modified = os.getenv(
            'WHOOGLE_CONFIG_STYLE', '')
        self.block = os.getenv('WHOOGLE_CONFIG_BLOCK', '')
        self.block_title = os.getenv('WHOOGLE_CONFIG_BLOCK_TITLE', '')
        self.block_url = os.getenv('WHOOGLE_CONFIG_BLOCK_URL', '')
        self.country = os.getenv('WHOOGLE_CONFIG_COUNTRY', '')
        self.tbs = os.getenv('WHOOGLE_CONFIG_TIME_PERIOD', '')
        self.theme = os.getenv('WHOOGLE_CONFIG_THEME', 'system')
        self.safe = read_config_bool('WHOOGLE_CONFIG_SAFE')
        self.alts = read_config_bool('WHOOGLE_CONFIG_ALTS')
        self.nojs = read_config_bool('WHOOGLE_CONFIG_NOJS')
        self.tor = read_config_bool('WHOOGLE_CONFIG_TOR')
        self.near = os.getenv('WHOOGLE_CONFIG_NEAR', '')
        self.new_tab = read_config_bool('WHOOGLE_CONFIG_NEW_TAB')
        self.view_image = read_config_bool('WHOOGLE_CONFIG_VIEW_IMAGE')
        self.get_only = read_config_bool('WHOOGLE_CONFIG_GET_ONLY')
        self.anon_view = read_config_bool('WHOOGLE_CONFIG_ANON_VIEW')
        self.preferences_encrypted = read_config_bool('WHOOGLE_CONFIG_PREFERENCES_ENCRYPTED')
        self.preferences_key = os.getenv('WHOOGLE_CONFIG_PREFERENCES_KEY', '')

        # Google Custom Search Engine (CSE) BYOK settings
        self.cse_api_key = os.getenv('WHOOGLE_CSE_API_KEY', '')
        self.cse_id = os.getenv('WHOOGLE_CSE_ID', '')
        self.use_cse = read_config_bool('WHOOGLE_USE_CSE')

        self.accept_language = False

        # Skip setting custom config if there isn't one
        if kwargs:
            mutable_attrs = self.get_mutable_attrs()
            for attr in mutable_attrs:
                if attr == 'show_user_agent':
                    # Handle show_user_agent as boolean
                    self.show_user_agent = bool(kwargs.get(attr))
                elif attr in kwargs.keys():
                    setattr(self, attr, kwargs[attr])
                elif attr not in kwargs.keys() and mutable_attrs[attr] == bool:
                    setattr(self, attr, False)

    def __getitem__(self, name):
        return getattr(self, name)

    def __setitem__(self, name, value):
        return setattr(self, name, value)

    def __delitem__(self, name):
        return delattr(self, name)

    def __contains__(self, name):
        return hasattr(self, name)

    def get_mutable_attrs(self):
        return {name: type(attr) for name, attr in self.__dict__.items()
                if not name.startswith("__")
                and name not in self.INSTANCE_ATTRS
                and (type(attr) is bool or type(attr) is str)}

    def get_attrs(self):
        return {name: attr for name, attr in self.__dict__.items()
                if not name.startswith("__")
                and (type(attr) is bool or type(attr) is str)}

    @property
    def style(self) -> str:
        """Returns the default style updated with specified modifications.

        Returns:
            str -- the new style
        """
        vars_path = os.path.join(current_app.config['STATIC_FOLDER'], 'css/variables.css')
        with open(vars_path, 'r', encoding='utf-8') as f:
            style_sheet = cssutils.parseString(f.read())

        modified_sheet = cssutils.parseString(self.style_modified)
        for rule in modified_sheet:
            rule_default = get_rule_for_selector(style_sheet,
                                                 rule.selectorText)
            # if modified rule is in default stylesheet, update it
            if rule_default is not None:
                # TODO: update this in a smarter way to handle :root better
                # for now if we change a varialbe in :root all other default
                # variables need to be also present
                rule_default.style = rule.style
            # else add the new rule to the default stylesheet
            else:
                style_sheet.add(rule)
        return str(style_sheet.cssText, 'utf-8')

    @property
    def preferences(self) -> str:
        # if encryption key is not set will uncheck preferences encryption
        if self.preferences_encrypted:
            self.preferences_encrypted = bool(self.preferences_key)

        # add a tag for visibility if preferences token startswith 'e' it means
        # the token is encrypted, 'u' means the token is unencrypted and can be
        # used by other whoogle instances
        encrypted_flag = "e" if self.preferences_encrypted else 'u'
        preferences_digest = self._encode_preferences()
        return f"{encrypted_flag}{preferences_digest}"

    def is_safe_key(self, key) -> bool:
        """Establishes a group of config options that are safe to set
        in the url.

        Args:
            key (str) -- the key to check against

        Returns:
            bool -- True/False depending on if the key is in the "safe"
            array
        """

        return key in self.safe_keys

    def get_localization_lang(self):
        """Returns the correct language to use for localization, but falls
        back to english if not set.

        Returns:
            str -- the localization language string
        """
        if (self.lang_interface and
                self.lang_interface in current_app.config['TRANSLATIONS']):
            return self.lang_interface

        return 'lang_en'

    def from_params(self, params) -> 'Config':
        """Modify user config with search parameters. This is primarily
        used for specifying configuration on a search-by-search basis on
        public instances.

        Args:
            params -- the url arguments (can be any deemed safe by is_safe())

        Returns:
            Config -- a modified config object
        """
        if 'preferences' in params:
            params_new = self._decode_preferences(params['preferences'])
            # if preferences leads to an empty dictionary it means preferences
            # parameter was not decrypted successfully
            if len(params_new):
                params = params_new
            else:
                logger.warning(
                    'Ignoring malformed or undecryptable preferences '
                    'parameter, falling back to default config values')
                params = {k: v for k, v in params.items()
                          if k != 'preferences'}

        for param_key in params.keys():
            if not self.is_safe_key(param_key):
                continue
            param_val = self._sanitize_param(param_key,
                                             params.get(param_key))
            if param_val is INVALID_PARAM:
                continue

            self[param_key] = param_val
        return self

    def _sanitize_param(self, key, value):
        """Validates and coerces a single config parameter value against
        the type of the existing config attribute. Malformed values are
        rejected (logged and skipped) instead of being silently propagated
        to search requests.

        Args:
            key (str) -- the config attribute name
            value -- the raw value from the URL params or preferences

        Returns:
            The sanitized value, or INVALID_PARAM if the value is malformed
        """
        current = getattr(self, key, None)

        if isinstance(current, bool):
            if isinstance(value, str):
                return value.strip().lower() not in FALSE_STRINGS
            return bool(value)

        if isinstance(current, str):
            if not isinstance(value, str):
                logger.warning(
                    f'Rejecting config param "{key}": expected string, '
                    f'got {type(value).__name__}')
                return INVALID_PARAM
            if len(value) > MAX_PARAM_VALUE_LENGTH:
                logger.warning(
                    f'Rejecting config param "{key}": value exceeds '
                    f'{MAX_PARAM_VALUE_LENGTH} characters')
                return INVALID_PARAM
            if key == 'tbs' and not TBS_PATTERN.match(value):
                logger.warning(
                    f'Rejecting malformed tbs value: {value!r}')
                return INVALID_PARAM
            return value

        # Legacy behavior for values targeting attributes of other types:
        # convert digit strings to ints and pass everything else through.
        if value == 'off':
            return False
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return value

    def to_params(self, keys: list = []) -> str:
        """Generates a set of safe params for using in Whoogle URLs

        Args:
            keys (list) -- optional list of keys of URL parameters

        Returns:
            str -- a set of URL parameters
        """
        if not len(keys):
            keys = self.safe_keys

        param_str = ''
        for safe_key in keys:
            if not self[safe_key]:
                continue
            param_str = param_str + f'&{safe_key}={self[safe_key]}'

        return param_str

    def _get_fernet_key(self, password: str) -> bytes:
        """Derive a Fernet-compatible key from a password using PBKDF2.
        
        Note: This uses a static salt for simplicity. This is a breaking change
        from the previous MD5-based implementation. Existing encrypted preferences
        will need to be re-encrypted.
        
        Args:
            password: The password to derive the key from
            
        Returns:
            bytes: A URL-safe base64 encoded 32-byte key suitable for Fernet
        """
        # Use a static salt derived from app context
        # In a production system, you'd want to store per-user salts
        salt = b'whoogle-preferences-salt-v2'
        
        # Derive a 32-byte key using PBKDF2 with SHA256
        # 100,000 iterations is a reasonable balance of security and performance
        kdf_key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            100000,
            dklen=32
        )
        
        # Fernet requires a URL-safe base64 encoded key
        return urlsafe_b64encode(kdf_key)

    def _encode_preferences(self) -> str:
        preferences_json = json.dumps(self.get_attrs()).encode()
        compressed_preferences = brotli.compress(preferences_json)

        if self.preferences_encrypted and self.preferences_key:
            key = self._get_fernet_key(self.preferences_key)
            encrypted_preferences = Fernet(key).encrypt(compressed_preferences)
            compressed_preferences = brotli.compress(encrypted_preferences)

        return urlsafe_b64encode(compressed_preferences).decode()

    def _decode_preferences(self, preferences: str) -> dict:
        if not preferences or len(preferences) < 2:
            logger.warning(
                'Received empty or truncated preferences token, '
                'falling back to default config values')
            return {}

        mode = preferences[0]
        preferences = preferences[1:]

        try:
            decoded_data = brotli.decompress(urlsafe_b64decode(preferences.encode() + b'=='))

            if mode == 'e':
                # preferences are encrypted
                if not self.preferences_key:
                    logger.warning(
                        'Received encrypted preferences but no '
                        'preferences key is configured, falling back to '
                        'default config values')
                    return {}
                key = self._get_fernet_key(self.preferences_key)
                decrypted_data = Fernet(key).decrypt(decoded_data)
                decoded_data = brotli.decompress(decrypted_data)

            config = json.loads(decoded_data)
        except InvalidToken:
            logger.warning(
                'Failed to decrypt preferences (invalid token or wrong '
                'key), falling back to default config values')
            config = {}
        except Exception:
            logger.warning(
                'Failed to decode malformed preferences parameter, '
                'falling back to default config values')
            config = {}

        if not isinstance(config, dict):
            logger.warning(
                'Decoded preferences are not a config dictionary, '
                'falling back to default config values')
            return {}

        return config

