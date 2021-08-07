import logging

from custom_components.nvenergy.thesimple import (
    TheSimpleClient,
    TheSimpleThermostat,
    TheSimpleError,
)

from homeassistant.components.climate import ClimateEntity

from homeassistant.components.climate.const import (
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_FAN,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_IDLE,
    CURRENT_HVAC_OFF,
    FAN_AUTO,
    FAN_ON,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_OFF,
    PRESET_AWAY,
    PRESET_NONE,
    SUPPORT_AUX_HEAT,
    SUPPORT_FAN_MODE,
    SUPPORT_PRESET_MODE,
    SUPPORT_TARGET_HUMIDITY,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_TARGET_TEMPERATURE_RANGE,
)

from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_PASSWORD,
    CONF_USERNAME,
    TEMP_CELSIUS,
    CONF_NAME,
    TEMP_FAHRENHEIT,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://nve.ecofactor.com/ws/v1.0/"


def setup_platform(hass, config, add_entities, discovery_info=None):
    _LOGGER.debug("Creating NVE Thermostats")

    if CONF_USERNAME not in config or len(config[CONF_USERNAME]) == 0:
        raise NVEThermostatConfigError(
            "No " + str(CONF_USERNAME) + " config parameter provided."
        )

    if CONF_PASSWORD not in config or len(config[CONF_PASSWORD]) == 0:
        raise NVEThermostatConfigError(
            "No " + str(CONF_PASSWORD) + " config parameter provided."
        )

    base_url = BASE_URL
    if "base_url" in config and len(config["base_url"]) > 0:
        base_url = config["base_url"]

    client = TheSimpleClient(base_url)
    _LOGGER.info("Authenticating")
    client.auth(config[CONF_USERNAME], config[CONF_PASSWORD])

    thermostat_ids = client.getThermostatIds()
    nve_thermostats = []

    for thermostat_id in thermostat_ids:
        simple_thermostat = client.createThermostat(thermostat_id)
        nve_thermostat = NVEThermostat(simple_thermostat)
        nve_thermostats.append(nve_thermostat)

    add_entities(nve_thermostats)


class NVEThermostatError(Exception):
    pass


class NVEThermostatConfigError(NVEThermostatError):
    pass


class NVEThermostat(ClimateEntity):
    def __init__(self, thesimplethermostat, name=None):
        _LOGGER.debug("Init NVE Thermostat class")
        self._thermostat = thesimplethermostat
        self._name = name

    @property
    def current_temperature(self):
        return self._thermostat.current_temp

    @property
    def extra_state_attributes(self):
        data = {
            "setpoint_reason": self._thermostat.setpoint_reason,
            "nve_thermostat_id": self._thermostat.id,
        }
        return data

    @property
    def fan_mode(self):
        if self._thermostat.fan_mode == "on":
            return FAN_ON
        elif self._thermostat.fan_mode == "auto":
            return FAN_AUTO
        else:
            return None
    
    @property
    def fan_modes(self):
        return [FAN_ON, FAN_AUTO]

    @property
    def hvac_action(self):
        simpletherm_state = self._thermostat.hvacState
        simpletherm_mode = self._thermostat.hvacMode

        if simpletherm_mode == "off" and simpletherm_state == "off":
            return CURRENT_HVAC_OFF
        if simpletherm_state == "cool":
            return CURRENT_HVAC_COOL
        elif simpletherm_state == "heat":
            return CURRENT_HVAC_HEAT
        elif simpletherm_state == "off":
            return CURRENT_HVAC_IDLE
        else:
            return None

    @property
    def hvac_mode(self):
        if self._thermostat.hvacMode == "cool":
            return HVAC_MODE_COOL
        elif self._thermostat.hvacMode == "heat":
            return HVAC_MODE_HEAT
        elif self._thermostat.hvacMode == "off":
            return HVAC_MODE_OFF
        else:
            return None

    @property
    def hvac_modes(self):
        return [HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_OFF]

    @property
    def max_temp(self):
        return self._thermostat.maxTemp

    @property
    def min_temp(self):
        return self._thermostat.minTemp

    @property
    def name(self):
        if self._name is None:
            return self._thermostat.name
        else:
            return self._name

    @property
    def precision(self):
        return float("0.1")

    @property
    def supported_features(self):
        return SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE

    @property
    def target_temperature(self):
        if self.hvac_mode == HVAC_MODE_COOL:
            return self._thermostat.cool_setpoint
        if self.hvac_mode == HVAC_MODE_HEAT:
            return self._thermostat.heat_setpoint
        return None

    @property
    def temperature_unit(self):
        return TEMP_FAHRENHEIT
    
    @property
    def unique_id(self):
        return self._thermostat.thermostat_id

    def set_hvac_mode(self, hvac_mode: str):
        simpletherm_mode = ""

        if hvac_mode == HVAC_MODE_COOL:
            simpletherm_mode = "cool"
        elif hvac_mode == HVAC_MODE_HEAT:
            simpletherm_mode = "heat"
        elif hvac_mode == HVAC_MODE_OFF:
            simpletherm_mode = "off"
        else:
            raise NVEThermostatError("Unsupported HVAC mode: %s", hvac_mode)

        self._thermostat.set_mode(simpletherm_mode)

    def set_fan_mode(self, fan_mode):
        if fan_mode == FAN_AUTO:
            self._thermostat.set_fan_mode('auto')
        elif fan_mode == FAN_ON:
            self._thermostat.set_fan_mode('on')

    def set_temperature(self, **kwargs):
        _LOGGER.debug("Setting temperature")
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        _LOGGER.debug("Setting current temp to %f", temperature)
        self._thermostat.set_temp(temperature)

    def update(self):
        _LOGGER.debug("Refreshing thermostat")
        retries = 3
        success = False
        while retries > 0:
            try:
                self._thermostat.refresh()
                success = True
                break
            except Exception as ex:
                _LOGGER.warn("Refresh exception: %s", str(ex))
                _LOGGER.debug("Attempting refresh token")
                self._thermostat.client.getToken()

            retries -= 1

        if success == False:
            raise NVEThermostatError("Refresh failed after three attempts.")