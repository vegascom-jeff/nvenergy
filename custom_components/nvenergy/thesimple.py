from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64
import hashlib
import re
import datetime
import logging
import random
from types import resolve_bases
import requests
import time

_LOGGER = logging.getLogger(__name__)

FAN_MODES = ["on", "auto"]
HVAC_MODES = ["COOL", "HEAT"]
HVAC_STATE = ["cool", "heat", "off"]
SETPOINT_REASONS = ["mo", "schedule"]
HTTP_SUCCESS_START = 200
HTTP_SUCCESS_END = 299
HTTP_FORBIDDEN_START = 401
HTTP_FORBIDDEN_END = 401

MAX_TEMP_DEFAULT = 89
MIN_TEMP_DEFAULT = 50


class TheSimpleError(Exception):
    pass


class APIError(TheSimpleError):
    pass


class AuthError(TheSimpleError):
    pass


class TheSimpleClient:
    def __init__(self, base_url):
        self._base_url = base_url
        self._token = ""
        self._authinfo = {
            "nonce": "",
            "response": "",
            "opaque": "",
            "encryptedpass": "",
        }
        self._username = ""
        self._http_sess = None
        self.userid = ""
        self._refreshToken = ""
        self._publicKey = None
        self._noCacheNum = random.randint(1, 200000000000)

    @property
    def httpSess(self):
        if self._http_sess is None:
            self._http_sess = requests.Session()
            self._http_sess.headers.update({"X-Requested-With": "XMLHttpRequest"})

        return self._http_sess

    def auth(self, username, password):
        self.getPublicKey()
        self.getNonce()

        resp = self.buildResponse(username, password, self._realm, self._nonce)
        encrypted_pw = self.encryptPassword(password)

        self.authwithdetails(username, encrypted_pw, self._nonce, resp, self._opaque)

    def authwithdetails(self, user, encpass, nonce, resp, opaque):
        self._authinfo["nonce"] = nonce
        self._authinfo["response"] = resp
        self._authinfo["opaque"] = opaque
        self._authinfo["encryptedpass"] = encpass
        self._username = user

        self.getToken()

    def buildResponse(self, username, password, realm, nonce):
        pwhash = hashlib.sha1(password.encode("utf-8")).hexdigest()
        step2 = hashlib.sha1(
            (username + ":" + realm + ":" + pwhash).encode("utf-8")
        ).hexdigest()
        response = hashlib.sha1((step2 + ":" + nonce).encode("utf-8")).hexdigest()

        return response

    def clearToken(self):
        self._token = ""
        self._refreshToken = ""
        self._http_sess = None

    def createThermostat(self, thermostat_id):
        return TheSimpleThermostat(self, thermostat_id)

    def encryptPassword(self, password):
        encryptedPwBytes = self._publicKey.encrypt(
            password.encode("utf-8"), padding.PKCS1v15()
        )

        encrypted_pw = base64.b64encode(encryptedPwBytes).decode("utf-8")
        return encrypted_pw

    def getNonce(self):
        url = "authenticate/nonce"

        r = self.http_request("GET", url)

        www_auth = r.json()["WWW-Authenticate"]

        p = re.compile('DigestE realm="(\w+)", nonce="(\w+)", opaque="(\w+)"')
        m = p.match(www_auth)

        if m:
            self._realm = m.group(1)
            self._nonce = m.group(2)
            self._opaque = m.group(3)
        else:
            raise TheSimpleError("Unable to parse nonce response: %s", www_auth)

    def getPublicKey(self):
        url = "public_key"
        r = self.http_request("GET", url)

        pubkey_pem = r.json()["public_key"]
        self._publicKey = load_pem_public_key(pubkey_pem.encode("utf-8"))

    def getThermostatIds(self, locationIndex=0):
        url = "user"
        r = self.http_request("GET", url, None, True)

        location_id = r.json()["location_id_list"][locationIndex]

        url = "location/" + str(location_id)
        r = self.http_request("GET", url, None, True)

        return r.json()["thermostatIdList"]

    def getToken(self):
        _LOGGER.debug("getToken")

        self.clearToken()
        authstr = 'DigestE username="%s", realm="Consumer", nonce="%s", response="%s", opaque="%s"' % (
            self._username,
            self._authinfo["nonce"],
            self._authinfo["response"],
            self._authinfo["opaque"],
        )

        url = self._base_url + "authenticate"

        r = self.httpSess.post(
            url,
            headers={"Authorization": authstr},
            json={
                "username": self._username,
                "password": self._authinfo["encryptedpass"],
            },
        )

        _LOGGER.debug("response code: %s, response text: %s", r.status_code, r.text)
        if r.status_code >= HTTP_SUCCESS_START and r.status_code <= HTTP_SUCCESS_END:
            r_json = r.json()
            self._token = r_json["access_token"]
            self._userid = r_json["user_id"]
            self._refreshToken = r_json["refresh_token"]
        elif r.stat >= HTTP_FORBIDDEN_START and r.status_code <= HTTP_FORBIDDEN_END:
            raise AuthError(
                "Authentication Error (code: %s) (response: %s)"
                % (r.status_code, r.text)
            )
        else:
            raise APIError(
                "Invalid HTTP response (code: %s) (response: %s)"
                % (r.status_code, r.text)
            )

    def http_request(self, method, req_url, json_req_body=None, authenticated=False):
        _LOGGER.debug(
            "HTTP  request (method: %s, url: %s, json: %s, authenticated: %s)", method, req_url, 
                json_req_body, authenticated
        )
        if authenticated and len(self._token) == 0:
            raise AuthError("No token, authentication required")

        url = self._base_url + req_url

        reqheaders = {}
        if authenticated:
            reqheaders["Authorization"] = "Bearer " + self._token

        if method == "GET":
            r = self.httpSess.get(url, json=json_req_body, headers=reqheaders)
        elif method == "PATCH":
            r = self.httpSess.patch(url, json=json_req_body, headers=reqheaders)

        _LOGGER.debug(
            "HTTP Response (status code: %s, response: %s)", r.status_code, r.text 
        ) 

        if r.status_code >= HTTP_SUCCESS_START and r.status_code <= HTTP_SUCCESS_END:
            return r
        elif (
            r.status_code >= HTTP_FORBIDDEN_START
            and r.status_code <= HTTP_FORBIDDEN_END
        ):
            self.clearToken()
            raise APIError(
                "HTTP response forbidden (code: %s) (response: %s)", r.status_code, r.text
            )
        else:
            raise APIError(
                "Invalid HTTP response (code: %s) (response: %s)", r.status_code, r.text
            )


class TheSimpleThermostat:
    def __init__(self, client, thermostat_id):
        self._thermostat_id = thermostat_id
        self._client = client
        self._fan_mode = None
        self._fan_state = None
        self._hvac_mode = None
        self._hvac_state = None
        self._hold_mode = None
        self._cool_setpoint = None
        self._heat_setpoint = None
        self._setpoint_reason = None
        self._current_temp = None
        self._last_update = None
        self._connected = None
        self._name = None
        self._max_temp = MAX_TEMP_DEFAULT
        self._min_temp = MIN_TEMP_DEFAULT
        self._schedule_mode = None
        self._supported_modes = []
        self._away_enddts = None

        self.get_metadata()
        self.refresh()

    @property
    def client(self):
        return self._client

    @property
    def connected(self):
        return self._connected

    @property
    def cool_setpoint(self):
        return self._cool_setpoint

    @property
    def current_temp(self):
        return self._current_temp

    @property
    def fan_mode(self):
        return self._fan_mode

    @property
    def fan_state(self):
        return self.fan_state

    @property
    def heat_setpoint(self):
        return self._heat_setpoint

    @property
    def hvacMode(self):
        return self._hvac_mode

    @property
    def hvacState(self):
        return self._hvac_state

    @property
    def id(self):
        return self._thermostat_id

    @property
    def last_update(self):
        return self._last_update

    @property
    def maxTemp(self):
        return self._max_temp

    @property
    def minTemp(self):
        return self._min_temp

    @property
    def name(self):
        return self._name

    @property
    def setpoint_reason(self):
        return self._setpoint_reason

    @property
    def supportedModes(self):
        return self._supported_modes

    @property
    def thermostat_id(self):
        return self._thermostat_id

    def get_metadata(self):
        url = "thermostat/" + str(self._thermostat_id)

        r = self._client.http_request("GET", url, None, True)

        r_json = r.json()

        self._name = r_json["name"]
        self._schedule_mode = r_json["schedule_mode"]
        self._min_temp = float(r_json["model"]["min_temperature"])
        self._max_temp = float(r_json["model"]["max_temperature"])
        self._supported_modes = r_json["hvac_control"]

    def set_fan_mode(self, fan_mode):

        if fan_mode != "on" and fan_mode != "auto":
            raise TheSimpleError("Invalid fan mode: %s", fan_mode)

        url = "thermostat/" + str(self._thermostat_id) + "/state"

        json_req = {"fan_mode": fan_mode}

        self._client.http_request("PATCH", url, json_req, True)

        self._fan_mode = fan_mode

    def set_mode(self, mode):
        if mode != "cool" and mode != "heat" and mode != "off":
            raise TheSimpleError("Invalid HVAC mode: %s", mode)

        url = "thermostat/" + str(self._thermostat_id) + "/state"

        json_req = {"hvac_mode": mode}

        self._client.http_request("PATCH", url, json_req, True)

    def set_temp(self, temp):
        if temp < self._min_temp or temp > self._max_temp:
            return

        url = "thermostat/" + str(self._thermostat_id) + "/state"

        json_req = {}

        if self.hvacMode == "cool":
            json_req["cool_setpoint"] = int(temp)
            self._cool_setpoint = int(temp)
        elif self.hvacMode == "heat":
            json_req["heat_setpoint"] = int(temp)
            self._heat_setpoint = int(temp)
        elif self.hvacMode == "off":
            return
        else:
            raise TheSimpleError(
                "set_temp: Unable to determine current HVAC Mode: %s", self.hvacMode
            )

        self._client.http_request("PATCH", url, json_req, True)

        # if successful, set internal state so we don't have to wait on a refresh
        if self.hvacMode == "cool":
            self._cool_setpoint = int(temp)
        elif self.hvacMode == "heat":
            self._heat_setpoint = int(temp)

    def refresh(self):
        url = "thermostat/" + str(self._thermostat_id) + "/state"

        r = self._client.http_request("GET", url, None, True)

        r_json = r.json()
        self._connected = r_json["connected"]
        self._setpoint_reason = r_json["setpoint_reason"]

        thermostat_info = 'best_known_current_state_thermostat_data'
        #thermostat_info = "last_collected_thermostat_data"
        self._current_temp = round(float(r_json[thermostat_info]["temperature"]), 1)
        self._hold_mode = r_json[thermostat_info]["hold_mode"]
        self._fan_mode = r_json[thermostat_info]["fan_mode"]
        self._fan_state = r_json[thermostat_info]["fan_state"]
        self._hvac_mode = r_json[thermostat_info]["hvac_mode"]
        self._hvac_state = r_json[thermostat_info]["hvac_state"]
        self._cool_setpoint = r_json[thermostat_info]["cool_setpoint"]
        self._heat_setpoint = r_json[thermostat_info]["heat_setpoint"]
        self._last_update = time.time()

        if (
            "away_details" in r_json[thermostat_info]
            and "end_ts" in r_json[thermostat_info]["away_details"]
        ):
            self._away_enddts = r_json[thermostat_info]["away_details"]["end_ts"]
        else:
            self._away_enddts = None