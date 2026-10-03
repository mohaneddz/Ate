"""Small client matching the observed official Android app requests.

Credentials only go to the two fixed HTTPS origins below. Requests are never
automatically retried and response bodies are not included in exception text.
"""
import hashlib
import hmac
import json
import time
import uuid

import requests

WEBETU = "https://api-webetu.mesrs.dz/api"
ONOU = "https://gs-api.onou.dz/api"


class ApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def compact_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def signed_headers(key: str, body: str, *, timestamp=None, nonce=None) -> dict:
    timestamp = str(int(time.time())) if timestamp is None else str(timestamp)
    nonce = str(uuid.uuid4()) if nonce is None else nonce
    signature = hmac.new(key.encode(), f"{timestamp}|{nonce}|{body}".encode(), hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Timestamp": timestamp,
            "X-Nonce": nonce, "X-Signature": signature}


class Client:
    def __init__(self, profile: dict):
        self.profile = profile
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "ReserveMealsCLI/0.1"
        self.context = None
        self.meal_token = None

    def close(self):
        self.session.close()

    def _request(self, method: str, base: str, path: str, **kwargs):
        if base not in (WEBETU, ONOU) or not path.startswith("/") or "?" in path:
            raise ApiError("Unsupported API route.")
        try:
            response = self.session.request(method, base + path, timeout=(15, 35),
                                            allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise ApiError("Network request failed; no automatic retry was made.") from None
        if not 200 <= response.status_code < 300:
            raise ApiError(f"The service returned HTTP {response.status_code}; response content withheld.", response.status_code)
        try:
            return response.json()
        except ValueError:
            if path == "/reservemeal" and response.text.strip() == "Reserved":
                return "Reserved"
            raise ApiError("The service returned an unexpected response format.") from None

    def _web(self, path: str):
        return self._request("GET", WEBETU, path, headers={"authorization": self.web_token})

    def _onou(self, method: str, path: str, *, body=None, params=None, token=None):
        raw = compact_json(body) if body is not None else ""
        headers = signed_headers(self.profile["signing_key"], raw)
        headers["authorization"] = token or self.web_token
        return self._request(method, ONOU, path, headers=headers, params=params,
                             data=raw.encode("utf-8") if body is not None else None)

    def login(self):
        auth = self._request("POST", WEBETU, "/authentication/v1/", json={
            "username": self.profile["student"], "password": self.profile["password"]})
        if not isinstance(auth, dict) or not auth.get("token") or not auth.get("uuid"):
            raise ApiError("Login did not return a session. Check credentials or MFA in the official app.")
        self.web_token = auth["token"]
        # Treat the authenticated account identifier as a single path component.
        account = requests.utils.quote(str(auth["uuid"]), safe="")
        year = self._web("/infos/AnneeAcademiqueEncours")
        dia = self._web(f"/infos/bac/{account}/anneeAcademique/{int(year['id'])}/dia")
        housing = self._web(f"/infos/bac/{account}/demandesHebregement")
        matches = [row for row in housing if row.get("idAnneeAcademique") == year["id"]]
        if len(matches) != 1 or not matches[0].get("idResidance"):
            raise ApiError("Could not identify one current residence. No reservation was submitted.")
        wilaya = self._web(f"/infos/wilayaInscription/{int(dia['id'])}")
        if isinstance(wilaya, dict):
            wilaya = wilaya.get("id")
        if wilaya is None or wilaya == "":
            raise ApiError("The account has no booking region.")
        self.context = {"uuid": auth["uuid"], "wilaya": wilaya,
                        "residence": matches[0]["idResidance"], "token": self.web_token}
        meal_auth = self._onou("POST", "/loginpwebetu", body=self.context)
        if not isinstance(meal_auth, dict) or not meal_auth.get("token"):
            raise ApiError("The meal service did not return a session.")
        self.meal_token = meal_auth["token"]

    def depots(self):
        data = self._onou("GET", "/getdepotres", params=self.context, token="Bearer " + self.web_token)
        if not isinstance(data, dict) or not isinstance(data.get("depots"), list):
            raise ApiError("Unexpected restaurant list format.")
        return data["depots"]

    def reservations(self):
        rows = []
        for page in range(1, 101):
            data = self._onou("GET", "/meal-reservations/student",
                              params={**self.context, "page": page}, token="Bearer " + self.web_token)
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise ApiError("Unexpected reservation list format.")
            if int(data.get("meta", {}).get("current_page", page)) != page:
                raise ApiError("Reservation pagination did not advance; stopped for duplicate protection.")
            rows.extend(data["data"])
            if not data.get("links", {}).get("next"):
                total = data.get("meta", {}).get("total")
                if total is not None and int(total) != len(rows):
                    raise ApiError("Reservation list changed while reading; try again before booking.")
                return rows
        raise ApiError("Reservation history exceeded the safe pagination limit.")

    def reserve(self, day: str, menu_type: int, depot_id: int):
        detail = {"date_reserve": day, "menu_type": menu_type, "idDepot": depot_id}
        # The official app sends details as JSON strings inside the JSON body.
        body = {**self.context, "details": [compact_json(detail)]}
        return self._onou("POST", "/reservemeal", body=body, token="Bearer " + self.meal_token)
