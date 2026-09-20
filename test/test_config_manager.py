import json
import logging
import os

from app import app
from app.models.config import Config
from app.models.config_manager import ConfigManager


def make_config(**kwargs):
    with app.app_context():
        return Config(**kwargs)


def test_from_params_accepts_valid_tbs():
    config = make_config()
    config.from_params({'tbs': 'qdr:d'})
    assert config.tbs == 'qdr:d'


def test_from_params_rejects_malformed_tbs():
    config = make_config()
    config.from_params({'tbs': 'qdr:evil'})
    assert config.tbs == ''


def test_from_params_rejects_invalid_theme():
    config = make_config()
    config.from_params({'theme': 'neon'})
    assert config.theme == 'system'


def test_from_params_bool_parsing():
    config = make_config()
    config.from_params({'new_tab': '1', 'view_image': 'off'})
    assert config.new_tab is True
    assert config.view_image is False

    config.from_params({'new_tab': 'not-a-bool'})
    assert config.new_tab is True


def test_from_params_strips_control_characters():
    config = make_config()
    config.from_params({'block': 'example.com\x00\x07'})
    assert config.block == 'example.com'


def test_from_params_ignores_unsafe_keys():
    config = make_config()
    config.from_params({'cse_api_key': 'leaked', 'url': 'http://evil'})
    assert config.cse_api_key == ''
    assert config.url == ''


def test_immutable_attrs_not_settable_via_kwargs():
    config = make_config(cse_api_key='user-supplied', preferences_key='x')
    assert config.cse_api_key == ''
    assert config.preferences_key == ''


def test_apply_user_config_skips_immutable_attrs():
    config = make_config()
    config.apply_user_config({'use_cse': True, 'near': 'Seattle'})
    assert config.use_cse is False
    assert config.near == 'Seattle'


def test_apply_user_config_rejects_invalid_values():
    config = make_config()
    config.apply_user_config({'tbs': 'bogus', 'theme': 'dark'})
    assert config.tbs == ''
    assert config.theme == 'dark'


def test_decode_preferences_invalid_token_warns(caplog):
    config = make_config()
    with caplog.at_level(logging.WARNING, logger='app.models.config'):
        result = config._decode_preferences('unot-a-valid-token')
    assert result == {}
    assert any('preferences' in r.message.lower() for r in caplog.records)


def test_decode_preferences_empty_token():
    config = make_config()
    assert config._decode_preferences('') == {}


def test_decode_preferences_encrypted_without_key_warns(caplog):
    with app.app_context():
        enc_config = Config()
        enc_config.preferences_encrypted = True
        enc_config.preferences_key = 'secret'
        token = enc_config.preferences
    assert token.startswith('e')

    config = make_config()
    assert config.preferences_key == ''
    with caplog.at_level(logging.WARNING, logger='app.models.config'):
        result = config._decode_preferences(token)
    assert result == {}
    assert any('key' in r.message.lower() for r in caplog.records)


def test_preferences_round_trip_unencrypted():
    with app.app_context():
        config = Config()
        config.preferences_encrypted = False
        config.near = 'Seattle'
        config.theme = 'dark'
        token = config.preferences

        decoded = Config()._decode_preferences(token)
    assert decoded['near'] == 'Seattle'
    assert decoded['theme'] == 'dark'


def test_preferences_round_trip_encrypted():
    with app.app_context():
        config = Config()
        config.preferences_encrypted = True
        config.preferences_key = 'round-trip-key'
        config.near = 'Portland'
        token = config.preferences
        assert token.startswith('e')

        decoded_config = Config()
        decoded_config.preferences_key = 'round-trip-key'
        decoded = decoded_config._decode_preferences(token)
    assert decoded['near'] == 'Portland'


def test_from_params_with_valid_preferences_token():
    with app.app_context():
        source = Config()
        source.preferences_encrypted = False
        source.theme = 'light'
        source.tbs = 'qdr:w'
        token = source.preferences

        config = Config()
        config.from_params({'preferences': token})
        assert config.theme == 'light'
        assert config.tbs == 'qdr:w'


def test_from_params_with_broken_preferences_keeps_defaults(caplog):
    config = make_config()
    with caplog.at_level(logging.WARNING, logger='app.models.config'):
        config.from_params({'preferences': 'egarbage'})
    assert config.theme == 'system'
    assert any('preferences' in r.message.lower() for r in caplog.records)


def test_default_config_is_cached(tmp_path):
    config_file = tmp_path / 'config.json'
    config_file.write_text(json.dumps({'theme': 'dark'}))
    manager = ConfigManager(default_config_path=str(config_file))

    first = manager.get_default_config()
    assert first == {'theme': 'dark'}

    # Mutating the returned dict must not affect the cache
    first['theme'] = 'light'
    assert manager.get_default_config() == {'theme': 'dark'}

    # A changed file (new mtime) is picked up
    os.utime(config_file, (0, 0))
    config_file.write_text(json.dumps({'theme': 'light'}))
    os.utime(config_file, None)
    manager.reset_cache()
    assert manager.get_default_config() == {'theme': 'light'}


def test_default_config_missing_or_invalid(tmp_path):
    manager = ConfigManager(
        default_config_path=str(tmp_path / 'missing.json'))
    assert manager.get_default_config() == {}

    bad_file = tmp_path / 'config.json'
    bad_file.write_text('{not json')
    manager = ConfigManager(default_config_path=str(bad_file))
    assert manager.get_default_config() == {}


def test_build_user_config_validates_session_and_params():
    manager = ConfigManager(default_config_path='/nonexistent')
    with app.app_context():
        config = manager.build_user_config(
            session_config={'near': 'Seattle', 'tbs': 'bogus',
                            'cse_api_key': 'nope'},
            request_params={'theme': 'dark', 'safe': '1'})
    assert config.near == 'Seattle'
    assert config.tbs == ''
    assert config.cse_api_key == ''
    assert config.theme == 'dark'
    assert config.safe is True
