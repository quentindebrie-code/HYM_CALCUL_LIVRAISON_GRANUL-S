"""Server-only Supabase persistence. No credentials or Streamlit state are cached."""

import json
from datetime import date
from urllib.parse import urlparse

import pandas as pd
import requests


GRID_KEYS = (
    "date_grille", "palettes", "vrac", "zones", "tva_march", "tva_livr",
    "franchise_km", "prix_km_ht", "prix_km_ttc", "base_saisie", "source_grille",
)


class StoreError(RuntimeError):
    pass


class ConflictError(StoreError):
    pass


def encode_state(state):
    grid = {key: state[key] for key in GRID_KEYS}
    grid["date_grille"] = pd.Timestamp(grid["date_grille"]).date().isoformat()
    # pandas converts NaN/NaT to JSON null and timestamps to ISO strings.
    history = json.loads(state["historique"].to_json(orient="records", date_format="iso"))
    payload = {"schema_version": 1, "grille": grid, "historique": history}
    return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))


def decode_state(payload, columns):
    if payload.get("schema_version") != 1:
        raise StoreError("Version des données Supabase non prise en charge.")
    grid = {key: payload["grille"][key] for key in GRID_KEYS}
    grid["date_grille"] = date.fromisoformat(grid["date_grille"])
    grid["vrac"] = {int(k): v for k, v in grid["vrac"].items()}
    history = pd.DataFrame(payload["historique"], columns=columns)
    history["date"] = pd.to_datetime(history["date"], errors="raise")
    for key in ("palier_t", "prix_ht", "taux_tva", "prix_ttc"):
        history[key] = pd.to_numeric(history[key], errors="raise")
    grid["historique"] = history
    return grid


class SupabaseStore:
    def __init__(self, url, key):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise StoreError("SUPABASE_URL doit être une URL HTTPS valide.")
        if not key or key.startswith("sb_publishable_"):
            raise StoreError("Une clé serveur Supabase est requise (SUPABASE_SECRET_KEY).")
        self.url = url.rstrip("/") + "/rest/v1"
        self.headers = {"apikey": key, "Content-Type": "application/json"}
        # Modern secret keys are not JWTs; do not send them as Bearer tokens.
        if not key.startswith("sb_secret_"):
            self.headers["Authorization"] = "Bearer " + key

    def _request(self, method, path, **kwargs):
        try:
            response = requests.request(
                method, self.url + path, headers=self.headers, timeout=(5, 20),
                allow_redirects=False, **kwargs,
            )
        except requests.RequestException:
            raise StoreError("Supabase est injoignable. Les changements restent en session.") from None
        if response.status_code == 409:
            raise ConflictError(
                "Une autre session a enregistré des modifications. Exportez votre travail "
                "en Excel, puis rechargez la base avant de réappliquer vos changements."
            )
        if not 200 <= response.status_code < 300:
            raise StoreError(
                f"Échec Supabase (HTTP {response.status_code}). Vérifiez la clé serveur, "
                "la migration et l'accès à la Data API. Aucune sauvegarde confirmée."
            )
        try:
            return response.json()
        except ValueError:
            raise StoreError("Réponse Supabase illisible. Aucune sauvegarde confirmée.") from None

    def load(self):
        rows = self._request("GET", "/granules_state", params={
            "id": "eq.cockpit", "select": "payload,revision,updated_at", "limit": "1",
        })
        if not isinstance(rows, list) or len(rows) != 1:
            raise StoreError("La ligne cockpit est absente. Appliquez la migration Supabase.")
        return rows[0]

    def save(self, payload, expected_revision):
        revision = self._request("POST", "/rpc/granules_save_state", json={
            "p_payload": payload, "p_expected_revision": expected_revision,
        })
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise StoreError("Révision Supabase invalide. Rechargez la base pour vérifier.")
        return revision
