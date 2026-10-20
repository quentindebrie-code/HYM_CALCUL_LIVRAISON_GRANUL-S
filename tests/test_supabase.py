import copy
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests
from streamlit.testing.v1 import AppTest

from granules_store import ConflictError, StoreError, SupabaseStore, encode_state, decode_state

COLUMNS = ['date', 'acteur', 'type_acteur', 'conditionnement', 'produit', 'palier_t', 'unite', 'prix_ht', 'taux_tva', 'prix_ttc']


def test_roundtrip_dates_prices_and_missing_tonnage():
    state = dict(date_grille=date(2026, 10, 20), palettes={'Piveteau': {'ht': 411.7, 'ttc': 452.87}},
                 vrac={2: {'ht': 397.27, 'ttc': 437.0}}, zones=[], tva_march=.1, tva_livr=.1,
                 franchise_km=35, prix_km_ht=1.27, prix_km_ttc=1.4, base_saisie='TTC', source_grille='Test',
                 historique=pd.DataFrame([[pd.Timestamp('2026-10-20'), 'Hympyr', 'Interne', 'Palette', 'Piveteau', float('nan'), 'palette', 411.7, .1, 452.87]], columns=COLUMNS))
    payload = encode_state(state)
    assert payload['historique'][0]['palier_t'] is None
    decoded = decode_state(payload, COLUMNS)
    assert decoded['vrac'] == state['vrac']
    assert decoded['palettes'] == state['palettes']
    assert decoded['date_grille'] == state['date_grille']
    assert decoded['historique'].iloc[0]['prix_ttc'] == 452.87
    assert pd.isna(decoded['historique'].iloc[0]['palier_t'])


def response(status, data):
    return Mock(status_code=status, json=Mock(return_value=data))


def test_rest_headers_and_compare_and_swap():
    with patch('granules_store.requests.request', return_value=response(200, 4)) as request:
        store = SupabaseStore('https://example.supabase.co', 'sb_secret_test')
        assert store.save({'schema_version': 1}, 3) == 4
        kwargs = request.call_args.kwargs
        assert kwargs['json']['p_expected_revision'] == 3
        assert 'Authorization' not in kwargs['headers']
        assert kwargs['allow_redirects'] is False


def test_conflict_and_network_error_are_safe():
    store = SupabaseStore('https://example.supabase.co', 'sb_secret_test')
    with patch('granules_store.requests.request', return_value=response(409, {})):
        with pytest.raises(ConflictError):
            store.save({}, 0)
    with patch('granules_store.requests.request', side_effect=requests.ConnectionError('secret diagnostic')):
        with pytest.raises(StoreError, match='injoignable') as error:
            store.load()
        assert 'secret diagnostic' not in str(error.value)


def test_missing_row_and_unknown_payload_rejected():
    store = SupabaseStore('https://example.supabase.co', 'sb_secret_test')
    with patch('granules_store.requests.request', return_value=response(200, [])):
        with pytest.raises(StoreError, match='absente'):
            store.load()
    with pytest.raises(StoreError, match='Version'):
        decode_state({'schema_version': 2}, COLUMNS)


def test_app_without_secrets_runs_in_explicit_local_mode():
    at = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app_gran.py', default_timeout=30).run()
    assert not at.exception
    assert any('Mode session seule' in w.value for w in at.warning)


def configured_app(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SECRET_KEY', 'sb_secret_test')
    monkeypatch.setenv('GRANULES_APP_PASSWORD', 'test-password-for-team')
    return AppTest.from_file(Path(__file__).resolve().parents[1] / 'app_gran.py', default_timeout=30)


def login(at):
    at.run()
    at.text_input[0].set_value('test-password-for-team')
    at.button[0].click().run()
    assert not at.exception


def button(at, label):
    return next(b for b in at.button if b.label == label)


def test_app_authentication_precedes_database_access(monkeypatch):
    at = configured_app(monkeypatch)
    with patch.object(SupabaseStore, 'load') as load:
        at.run()
        assert not at.exception
        assert len(at.tabs) == 0
        load.assert_not_called()
        at.text_input[0].set_value('wrong')
        at.button[0].click().run()
        load.assert_not_called()
        assert any('incorrect' in e.value for e in at.error)


def test_app_saves_and_new_session_reloads_without_price_drift(monkeypatch):
    at = configured_app(monkeypatch)
    remote = {'payload': None, 'revision': 0}
    def save(payload, revision):
        assert revision == remote['revision']
        remote.update(payload=copy.deepcopy(payload), revision=revision + 1)
        return remote['revision']
    with patch.object(SupabaseStore, 'load', side_effect=lambda: copy.deepcopy(remote)), patch.object(SupabaseStore, 'save', side_effect=save):
        login(at)
        button(at, "💾 Enregistrer l'état actuel").click().run()
        assert not at.exception
        button(at, "📌 Archiver cette grille dans l'historique").click().run()
        assert not at.exception
        assert remote['revision'] == 2
        assert len(remote['payload']['historique']) == 10
        at2 = configured_app(monkeypatch)
        login(at2)
        assert len(at2.session_state['historique']) == 10
        assert at2.session_state['palettes']['Piveteau']['ttc'] == 452.87
        # A date is committed only by Apply, never by merely editing the widget.
        next(d for d in at2.date_input if d.label == "Date d'effet").set_value(date(2026, 11, 1)).run()
        assert at2.session_state['date_grille'] == date(2026, 10, 20)
        button(at2, '💾 Appliquer les modifications').click().run()
        assert remote['payload']['grille']['date_grille'] == '2026-11-01'


def test_app_failure_preserves_pending_work_and_never_claims_success(monkeypatch):
    at = configured_app(monkeypatch)
    with patch.object(SupabaseStore, 'load', return_value={'payload': None, 'revision': 0}), patch.object(SupabaseStore, 'save', side_effect=ConflictError('Conflit de session')):
        login(at)
        button(at, "📌 Archiver cette grille dans l'historique").click().run()
        assert not at.exception
        assert at.session_state['supabase_non_sauve']
        assert len(at.session_state['historique']) == 10
        assert any('Sauvegarde non confirmée' in e.value for e in at.error)
        assert not any('lignes archivées' in s.value for s in at.success)


def test_configured_database_failure_does_not_use_defaults(monkeypatch):
    at = configured_app(monkeypatch)
    with patch.object(SupabaseStore, 'load', side_effect=StoreError('Indisponible')):
        login(at)
        assert len(at.tabs) == 0
        assert any('Chargement de la base impossible' in e.value for e in at.error)
