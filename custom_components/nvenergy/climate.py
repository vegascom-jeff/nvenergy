import logging
from custom_components.nvenergy.thesimple import (
    TheSimpleClient,
    TheSimpleThermostat,
    TheSimpleError,
)

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)

from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_ON,
    PRESET_AWAY,
    PRESET_NONE,
)

from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_NAME,
    UnitOfTemperature,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://nve.ecofactor.com/ws/v1.0/"


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
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
    await hass.async_add_executor_job(client.auth, config[CONF_USERNAME], config[CONF_PASSWORD])

    thermostat_ids = await hass.async_add_executor_job(client.getThermostatIds)
    nve_thermostats = []

    for thermostat_id in thermostat_ids:
        simple_thermostat = await hass.async_add_executor_job(client.createThermostat, thermostat_id)
        nve_thermostat = NVEThermostat(simple_thermostat)
        nve_thermostats.append(nve_thermostat)

    async_add_entities(nve_thermostats)


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
            return HVACAction.OFF
        if simpletherm_state == "cool":
            return HVACAction.COOLING
        elif simpletherm_state == "heat":
            return HVACAction.HEATING
        elif simpletherm_state == "off":
            return HVACAction.IDLE
        else:
            return None

    @property
    def hvac_mode(self):
        if self._thermostat.hvacMode == "cool":
            return HVACMode.COOL
        elif self._thermostat.hvacMode == "heat":
            return HVACMode.HEAT
        elif self._thermostat.hvacMode == "off":
            return HVACMode.OFF
        else:
            return None

    @property
    def hvac_modes(self):
        return [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF]

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
        return ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON

    @property
    def target_temperature(self):
        if self.hvac_mode == HVACMode.COOL:
            return self._thermostat.cool_setpoint
        if self.hvac_mode == HVACMode.HEAT:
            return self._thermostat.heat_setpoint
        return None

    @property
    def temperature_unit(self):
        return UnitOfTemperature.FAHRENHEIT
    
    @property
    def unique_id(self):
        return self._thermostat.thermostat_id

    async def async_set_hvac_mode(self, hvac_mode: str):
        simpletherm_mode = ""

        if hvac_mode == HVACMode.COOL:
            simpletherm_mode = "cool"
        elif hvac_mode == HVACMode.HEAT:
            simpletherm_mode = "heat"
        elif hvac_mode == HVACMode.OFF:
            simpletherm_mode = "off"
        else:
            raise NVEThermostatError("Unsupported HVAC mode: %s", hvac_mode)

        await self.hass.async_add_executor_job(self._thermostat.set_mode, simpletherm_mode)

    async def async_set_fan_mode(self, fan_mode):
        if fan_mode == FAN_AUTO:
            await self.hass.async_add_executor_job(self._thermostat.set_fan_mode, 'auto')
        elif fan_mode == FAN_ON:
            await self.hass.async_add_executor_job(self._thermostat.set_fan_mode, 'on')

    async def async_set_temperature(self, **kwargs):
        _LOGGER.debug("Setting temperature")
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        _LOGGER.debug("Setting current temp to %f", temperature)
        await self.hass.async_add_executor_job(self._thermostat.set_temp, temperature)

    async def async_update(self):
        _LOGGER.debug("Refreshing thermostat")
        retries = 3
        success = False
        while retries > 0:
            try:
                await self.hass.async_add_executor_job(self._thermostat.refresh)
                success = True
                break
            except Exception as ex:
                _LOGGER.warn("Refresh exception: %s", str(ex))
                _LOGGER.debug("Attempting refresh token")
                await self.hass.async_add_executor_job(self._thermostat.client.getToken)

            retries -= 1

        if success == False:
            raise NVEThermostatError("Refresh failed after three attempts.")
