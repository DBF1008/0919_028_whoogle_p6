import json
import logging
import os

import pytest

from app import app
from app.models.config import Config, MAX_PARAM_VALUE_LENGTH
from app.models.config_manager import ConfigManager


@pytest.fixture
def config():
    with app.app_context():
        yield Config(**{})


@pytest.fixture
def manager(tmp_path):
    return ConfigManager(str(tmp_path / 'config.json'))


def write_default_config(path, data, mtime=None):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_from_params_applies_valid_values(config):
    config.from_params({'theme': 'dark', 'tbs': 'qdr:d', 'safe': '1'})
    assert config.theme == 'dark'
    assert config.tbs == 'qdr:d'
    assert config.safe is True


def test_from_params_rejects_malformed_tbs(config, caplog):
    with caplog.at_level(logging.WARNING):
        config.from_params({'tbs': 'qdr:zz";<script>alert(1)</script>'})
    assert config.tbs == ''
    assert 'tbs' in caplog.text


def test_from_params_accepts_tbs_with_filter_segments(config):
    config.from_params({'tbs': 'qdr:h,lr:lang_1pl'})
    assert config.tbs == 'qdr:h,lr:lang_1pl'


def test_from_params_ignores_unsafe_keys(config):
    config.from_params({
        'preferences_key': 'attacker-key',
        'cse_api_key': 'attacker-cse-key',
        'not_a_real_key': 'value',
    })
    assert config.preferences_key == ''
    assert config.cse_api_key == ''
    assert not hasattr(config, 'not_a_real_key')


def test_from_params_bool_coercion(config):
    config.from_params({'alts': 'off', 'new_tab': 'true', 'nojs': '0'})
    assert config.alts is False
    assert config.new_tab is True
    assert config.nojs is False


def test_from_params_rejects_oversized_string(config, caplog):
    with caplog.at_level(logging.WARNING):
        config.from_params({'block': 'a' * (MAX_PARAM_VALUE_LENGTH + 1)})
    assert config.block == ''
    assert 'block' in caplog.text


def test_from_params_malformed_preferences_falls_back(config, caplog):
    config.theme = 'dark'
    with caplog.at_level(logging.WARNING):
        config.from_params({'preferences': 'not-a-valid-token'})
    # Existing (default) config values are kept, nothing is propagated
    assert config.theme == 'dark'
    assert 'preferences' in caplog.text


def test_decode_preferences_roundtrip_unencrypted(config):
    config.theme = 'dark'
    config.country = 'US'
    token = config.preferences
    assert token.startswith('u')

    with app.app_context():
        decoded = Config(**{})._decode_preferences(token)
    assert decoded['theme'] == 'dark'
    assert decoded['country'] == 'US'


def test_decode_preferences_roundtrip_encrypted(config):
    config.preferences_key = 'test-secret'
    config.preferences_encrypted = True
    config.theme = 'dark'
    token = config.preferences
    assert token.startswith('e')

    with app.app_context():
        other = Config(**{})
        other.preferences_key = 'test-secret'
        decoded = other._decode_preferences(token)
    assert decoded['theme'] == 'dark'


def test_decode_preferences_wrong_key_returns_empty(config, caplog):
    config.preferences_key = 'correct-key'
    config.preferences_encrypted = True
    token = config.preferences

    with app.app_context():
        other = Config(**{})
        other.preferences_key = 'wrong-key'
        with caplog.at_level(logging.WARNING):
            decoded = other._decode_preferences(token)
    assert decoded == {}
    assert 'decrypt' in caplog.text.lower()


def test_decode_preferences_encrypted_without_key(config, caplog):
    config.preferences_key = 'test-secret'
    config.preferences_encrypted = True
    token = config.preferences

    with app.app_context():
        other = Config(**{})
        assert other.preferences_key == ''
        with caplog.at_level(logging.WARNING):
            decoded = other._decode_preferences(token)
    assert decoded == {}
    assert 'no' in caplog.text.lower()


def test_decode_preferences_malformed_returns_empty(config, caplog):
    with caplog.at_level(logging.WARNING):
        assert config._decode_preferences('') == {}
        assert config._decode_preferences('e') == {}
        assert config._decode_preferences('u!!!not-base64!!!') == {}
    assert caplog.text != ''


def test_instance_attrs_are_not_mutable(config):
    assert 'preferences_key' not in config.get_mutable_attrs()
    assert 'theme' in config.get_mutable_attrs()

    with app.app_context():
        cfg = Config(**{'preferences_key': 'injected', 'theme': 'dark'})
    assert cfg.preferences_key == ''
    assert cfg.theme == 'dark'


def test_config_manager_missing_file(manager):
    assert manager.get_default_config() == {}


def test_config_manager_caches_default_config(manager):
    write_default_config(manager.config_path, {'theme': 'dark'}, mtime=1000)
    assert manager.get_default_config()['theme'] == 'dark'

    # Same mtime: file is not re-read, cached value is returned
    write_default_config(manager.config_path, {'theme': 'light'}, mtime=1000)
    assert manager.get_default_config()['theme'] == 'dark'

    # Changed mtime: cache is invalidated and the file is re-read
    write_default_config(manager.config_path, {'theme': 'light'}, mtime=2000)
    assert manager.get_default_config()['theme'] == 'light'


def test_config_manager_returns_copies(manager):
    write_default_config(manager.config_path, {'theme': 'dark'})
    first = manager.get_default_config()
    first['theme'] = 'mutated'
    assert manager.get_default_config()['theme'] == 'dark'


def test_config_manager_invalid_json(manager, caplog):
    with open(manager.config_path, 'w', encoding='utf-8') as f:
        f.write('{not json')
    with caplog.at_level(logging.WARNING):
        assert manager.get_default_config() == {}
    assert caplog.text != ''


def test_config_manager_sanitize_config():
    sanitized = ConfigManager.sanitize_config({
        'theme': 'dark',
        'safe': 'on',
        'alts': 'off',
        'new_tab': True,
        'preferences_key': 'injected',
        'unknown_key': 'value',
        'country': 12345,
    })
    assert sanitized == {
        'theme': 'dark',
        'safe': True,
        'alts': False,
        'new_tab': True,
    }


def test_config_manager_build_user_config(manager):
    with app.app_context():
        config = manager.build_user_config(
            {'theme': 'dark', 'safe': 'on'},
            {'tbs': 'malformed value!', 'country': 'US'})
    assert isinstance(config, Config)
    assert config.theme == 'dark'
    assert config.safe is True
    assert config.country == 'US'
    # Malformed tbs from the URL params is rejected
    assert config.tbs == ''
