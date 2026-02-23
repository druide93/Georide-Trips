"""GeoRide Trips integration."""
import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_SCAN_INTERVAL,
    CONF_LIFETIME_SCAN_INTERVAL,
    CONF_TRIPS_DAYS_BACK,
    CONF_SOCKETIO_ENABLED,
    CONF_TRACKER_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_LIFETIME_SCAN_INTERVAL,
    DEFAULT_TRIPS_DAYS_BACK,
    DEFAULT_SOCKETIO_ENABLED,
    DEFAULT_TRACKER_SCAN_INTERVAL,
)
from .api import GeoRideTripsAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.DATETIME,
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
]

SERVICE_SET_ODOMETER = "set_odometer"

SET_ODOMETER_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("value"): vol.Coerce(float),
    }
)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the GeoRide Trips component from YAML (legacy)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GeoRide Trips from a config entry."""
    _LOGGER.info("Setting up GeoRide Trips for %s", entry.data[CONF_EMAIL])

    # Read options
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    lifetime_scan_interval = entry.options.get(CONF_LIFETIME_SCAN_INTERVAL, DEFAULT_LIFETIME_SCAN_INTERVAL)
    trips_days_back = entry.options.get(CONF_TRIPS_DAYS_BACK, DEFAULT_TRIPS_DAYS_BACK)
    socketio_enabled = entry.options.get(CONF_SOCKETIO_ENABLED, DEFAULT_SOCKETIO_ENABLED)
    tracker_scan_interval = entry.options.get(CONF_TRACKER_SCAN_INTERVAL, DEFAULT_TRACKER_SCAN_INTERVAL)

    _LOGGER.info(
        "Options: scan_interval=%ss, lifetime=%ss, days_back=%s, socketio=%s, tracker_scan=%ss",
        scan_interval, lifetime_scan_interval, trips_days_back, socketio_enabled, tracker_scan_interval,
    )

    # Create API client
    session = async_get_clientsession(hass)
    api = GeoRideTripsAPI(
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        session
    )

    # Login
    if not await api.login():
        _LOGGER.error("Failed to login to GeoRide API")
        return False

    # Get trackers
    trackers = await api.get_trackers()
    _LOGGER.info("Found %d GeoRide trackers", len(trackers))

    # Create coordinators
    from .sensor import GeoRideTripsCoordinator, GeoRideLifetimeTripsCoordinator, GeoRideTrackerStatusCoordinator

    coordinators = {}
    lifetime_coordinators = {}
    tracker_status_coordinators = {}

    for tracker in trackers:
        tracker_id = str(tracker.get("trackerId"))
        tracker_name = tracker.get("trackerName", f"Tracker {tracker_id}")

        coordinator = GeoRideTripsCoordinator(
            hass, api, tracker_id, tracker_name,
            scan_interval, trips_days_back,
        )

        lifetime_coordinator = GeoRideLifetimeTripsCoordinator(
            hass, api, tracker_id, tracker_name,
            tracker.get("activationDate"),
            lifetime_scan_interval,
        )

        status_coordinator = GeoRideTrackerStatusCoordinator(
            hass, api, tracker_id, tracker_name,
            scan_interval=tracker_scan_interval,
        )

        await coordinator.async_config_entry_first_refresh()
        await lifetime_coordinator.async_config_entry_first_refresh()
        await status_coordinator.async_config_entry_first_refresh()

        coordinators[tracker_id] = coordinator
        lifetime_coordinators[tracker_id] = lifetime_coordinator
        tracker_status_coordinators[tracker_id] = status_coordinator

    # Store all data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "trackers": trackers,
        "email": entry.data[CONF_EMAIL],
        "coordinators": coordinators,
        "lifetime_coordinators": lifetime_coordinators,
        "tracker_status_coordinators": tracker_status_coordinators,
        "socket_manager": None,  # initialisé ci-dessous si activé
    }

    # Register devices
    device_registry = dr.async_get(hass)
    for tracker in trackers:
        tracker_id = str(tracker.get("trackerId"))
        tracker_name = tracker.get("trackerName", f"Tracker {tracker_id}")

        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, tracker_id)},
            manufacturer="GeoRide",
            model=tracker.get("model", "GeoRide Tracker"),
            name=f"{tracker_name} Trips",
            sw_version=str(tracker.get("softwareVersion", "")),
        )

    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Démarrer Socket.IO APRÈS le setup des plateformes
    # (les entités doivent être prêtes à recevoir les callbacks)
    if socketio_enabled:
        from .socket_manager import GeoRideSocketManager

        tracker_ids = [str(t.get("trackerId")) for t in trackers]
        socket_manager = GeoRideSocketManager(hass, api, tracker_ids)
        hass.data[DOMAIN][entry.entry_id]["socket_manager"] = socket_manager

        await socket_manager.start()
        _LOGGER.info("GeoRide Socket.IO manager started")
    else:
        _LOGGER.info("GeoRide Socket.IO disabled by option")

    # Register service set_odometer
    async def handle_set_odometer(call: ServiceCall):
        """Handle set_odometer service."""
        entity_id = call.data["entity_id"]
        value = call.data["value"]

        entity = hass.data["entity_components"]["sensor"].get_entity(entity_id)
        if entity and hasattr(entity, "set_odometer"):
            entity.set_odometer(value)
        else:
            _LOGGER.error("Entity %s not found or doesn't support set_odometer", entity_id)

    hass.services.async_register(DOMAIN, SERVICE_SET_ODOMETER, handle_set_odometer, schema=SET_ODOMETER_SCHEMA)

    # Reload on options change
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change."""
    _LOGGER.info("Options changed, reloading GeoRide Trips")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading GeoRide Trips")

    # Arrêter Socket.IO proprement avant le unload des plateformes
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    socket_manager = entry_data.get("socket_manager")
    if socket_manager:
        await socket_manager.stop()
        _LOGGER.info("GeoRide Socket.IO manager stopped")

    if len(hass.data.get(DOMAIN, {})) <= 1:
        hass.services.async_remove(DOMAIN, SERVICE_SET_ODOMETER)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok