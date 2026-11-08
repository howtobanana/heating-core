"""Konstanten für Heating Core."""

DOMAIN = "heating_core"

CONF_MANUFACTURER = "manufacturer"
MANUFACTURERS = ["vaillant", "oekofen"]

# Subentry-Typen
SUB_CIRCUIT = "circuit"
SUB_ROOM = "room"

# Globale Optionen (Defaults wie im Vaillant-Blueprint)
OPT_ECO = "eco_temp"
OPT_AWAY_TEMP = "away_temp"
OPT_MIN_TRV = "min_trv_temp"
OPT_HYSTERESIS = "hysteresis"
OPT_BUDGET = "budget_per_hour"
OPT_ACTIVATION_MIN = "presence_activation_min"
OPT_DEACTIVATION_MIN = "presence_deactivation_min"
OPT_WINDOW_DELAY_S = "window_delay_s"
OPT_WINDOW_SETTLE_S = "window_settle_s"
OPT_AWAY_ENTITIES = "away_entities"
OPT_GUEST_ENTITY = "guest_entity"
OPT_SUMMER_ENTITY = "summer_entity"
OPT_OUTDOOR_SENSOR = "outdoor_sensor"
OPT_WEATHER_ENABLED = "weather_enabled"
OPT_WEATHER_ZONE1 = "weather_zone1"
OPT_WEATHER_ZONE2 = "weather_zone2"
OPT_WEATHER_ZONE3 = "weather_zone3"
OPT_BOOST_ENABLED = "boost_enabled"
OPT_BOOST_AMOUNT = "boost_amount"
OPT_BOOST_THRESHOLD = "boost_threshold"
OPT_HUMIDITY_ENABLED = "humidity_enabled"
OPT_HUMIDITY_DROP = "humidity_drop"
OPT_PRE_HEAT_TIMEOUT_MIN = "pre_heat_timeout_min"

DEFAULTS = {
    OPT_ECO: 19.0,
    OPT_AWAY_TEMP: 16.0,
    OPT_MIN_TRV: 12.0,
    OPT_HYSTERESIS: 0.6,
    OPT_BUDGET: 10,
    OPT_ACTIVATION_MIN: 2,
    OPT_DEACTIVATION_MIN: 30,
    OPT_WINDOW_DELAY_S: 30,
    OPT_WINDOW_SETTLE_S: 180,
    OPT_AWAY_ENTITIES: [],
    OPT_WEATHER_ENABLED: False,
    OPT_WEATHER_ZONE1: 0.0,
    OPT_WEATHER_ZONE2: 0.0,
    OPT_WEATHER_ZONE3: 0.0,
    OPT_BOOST_ENABLED: True,
    OPT_BOOST_AMOUNT: 2.0,
    OPT_BOOST_THRESHOLD: 1.0,
    OPT_HUMIDITY_ENABLED: False,
    OPT_HUMIDITY_DROP: 0.5,
    OPT_PRE_HEAT_TIMEOUT_MIN: 90,
}

# Felder in Heizkreis- und Raum-Subentries
F_NAME = "name"
F_KIND = "kind"  # radiator | floor
F_MASTER = "master_climate"
F_CLIMATE = "climate"
F_CIRCUIT = "circuit"
F_ROLE = "role"  # isolated | follower
F_OFFSET = "offset"
F_COMFORT = "comfort"
F_COMFORT_ENTITY = "comfort_entity"
F_PRESENCE = "presence_sensors"
F_SCHEDULE = "schedule"
F_WINDOW = "window"
F_TEMP = "temp_sensor"
F_HUMIDITY = "humidity_sensor"
# Fußboden extern (Sonderfall Perg)
KIND_FLOOR_EXTERNAL = "floor_external"
ROLE_FLOOR_ZONE = "floor_zone"
F_PUMP = "pump_switch"
F_SOURCE_TEMP = "source_temp_sensor"
F_SOURCE_ON = "source_on"
F_SOURCE_OFF = "source_off"
F_VALVE_DELAY = "valve_delay_s"
F_VALVES = "valves"

STARTUP_GUARD_S = 120
UPDATE_INTERVAL_S = 180

MODES = ["eco", "presence", "schedule", "pre_heat", "manual", "boost", "away", "window", "temperature_drop", "summer", "follower", "unavailable", "floor_heating", "floor_idle", "source_cold", "sensor_missing"]
