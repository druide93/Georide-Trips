"""GeoRide Trips device tracker - Position GPS de la moto via Socket.IO.

Entité device_tracker rattachée au device de chaque moto :
- Position GPS en temps réel via événements Socket.IO (event "position")
- Fallback : récupération initiale via API REST au démarrage
- Pas de polling : les mises à jour arrivent dès que GeoRide envoie une position
"""
import logging

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GeoRideTripsAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GeoRide Trips device tracker from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    trackers = data["trackers"]
    api: GeoRideTripsAPI = data["api"]
    socket_manager = data.get("socket_manager")

    entities = []
    for tracker in trackers:
        entities.append(
            GeoRidePositionTracker(hass, entry, tracker, api, socket_manager)
        )

    async_add_entities(entities)
    _LOGGER.info("Added %d device_tracker entities for %d trackers", len(entities), len(trackers))


class GeoRidePositionTracker(TrackerEntity):
    """Device tracker représentant la position GPS d'une moto GeoRide.

    Mises à jour via Socket.IO event "position" — temps réel, sans polling.
    Fallback initial via API REST pour avoir une position dès le démarrage.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tracker: dict,
        api: GeoRideTripsAPI,
        socket_manager,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._tracker = tracker
        self._api = api
        self._socket_manager = socket_manager

        self._tracker_id = str(tracker.get("trackerId"))
        self._tracker_name = tracker.get("trackerName", f"Tracker {self._tracker_id}")

        self._attr_unique_id = f"{self._tracker_id}_position"
        self._attr_name = f"{self._tracker_name} Position"
        self._attr_icon = "mdi:motorbike"

        # Position
        self._latitude: float | None = None
        self._longitude: float | None = None
        self._gps_accuracy: int = 0
        self._fix_time: str | None = None
        self._speed: float | None = None
        self._heading: float | None = None
        self._altitude: float | None = None
        self._is_moving: bool = False

        # Désenregistrement Socket.IO
        self._unsub_socket: list = []

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._tracker_id)},
            name=f"{self._tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    # ── TrackerEntity properties ─────────────────────────────────────────────

    @property
    def latitude(self) -> float | None:
        return self._latitude

    @property
    def longitude(self) -> float | None:
        return self._longitude

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def gps_accuracy(self) -> int:
        return self._gps_accuracy

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            "tracker_id": self._tracker_id,
            "is_moving": self._is_moving,
            "source": "socket.io",
        }
        if self._fix_time:
            attrs["fix_time"] = self._fix_time
        if self._speed is not None:
            attrs["speed_kmh"] = round(self._speed * 1.852, 1)  # knots → km/h
        if self._heading is not None:
            attrs["heading"] = self._heading
        if self._altitude is not None:
            attrs["altitude"] = self._altitude
        return attrs

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Démarrage : position initiale + abonnement Socket.IO."""
        await super().async_added_to_hass()

        # Abonnement aux événements position via Socket.IO
        if self._socket_manager:
            unsub = self._socket_manager.register_callback(
                self._tracker_id, "position", self._handle_position_event
            )
            self._unsub_socket.append(unsub)
            _LOGGER.info(
                "Device tracker '%s' abonné aux événements position Socket.IO",
                self._tracker_name,
            )
        else:
            _LOGGER.warning(
                "Pas de socket_manager disponible pour '%s' — pas de mises à jour temps réel",
                self._tracker_name,
            )

        # Position initiale via API REST (pour avoir quelque chose dès le démarrage)
        await self._async_fetch_initial_position()

    async def async_will_remove_from_hass(self) -> None:
        """Nettoyage des abonnements."""
        for unsub in self._unsub_socket:
            unsub()
        self._unsub_socket.clear()

    # ── Handlers Socket.IO ───────────────────────────────────────────────────

    @callback
    def _handle_position_event(self, data: dict) -> None:
        """Reçoit un événement 'position' depuis Socket.IO et met à jour l'état."""
        _LOGGER.debug("Position Socket.IO pour %s : %s", self._tracker_name, data)

        lat = data.get("latitude")
        lon = data.get("longitude")
        if lat is None or lon is None:
            _LOGGER.warning("Événement position sans lat/lon pour %s : %s", self._tracker_name, data)
            return

        self._latitude = float(lat)
        self._longitude = float(lon)
        self._gps_accuracy = int(data.get("radius", 0) or 0)
        self._fix_time = data.get("fixtime") or data.get("fixTime")
        self._speed = data.get("speed")
        self._heading = data.get("heading")
        self._altitude = data.get("altitude")
        self._is_moving = bool(data.get("moving", False))

        self.async_write_ha_state()
        _LOGGER.debug(
            "Position mise à jour pour %s : lat=%.5f lon=%.5f moving=%s",
            self._tracker_name, self._latitude, self._longitude, self._is_moving,
        )

    # ── Fallback API REST ────────────────────────────────────────────────────

    async def _async_fetch_initial_position(self) -> None:
        """Récupère la dernière position connue via API REST au démarrage."""
        try:
            position = await self._api.get_last_position(self._tracker_id)
            if position:
                self._latitude = position.get("latitude")
                self._longitude = position.get("longitude")
                self._gps_accuracy = int(position.get("radius", 0) or 0)
                self._fix_time = position.get("fixtime") or position.get("fixTime")
                self._speed = position.get("speed")
                self._heading = position.get("heading")
                self._altitude = position.get("altitude")
                self.async_write_ha_state()
                _LOGGER.info(
                    "Position initiale (API) pour %s : lat=%s lon=%s",
                    self._tracker_name, self._latitude, self._longitude,
                )
            else:
                _LOGGER.debug("Pas de position initiale disponible pour %s", self._tracker_name)
        except Exception as err:
            _LOGGER.error(
                "Erreur récupération position initiale pour %s : %s",
                self._tracker_name, err,
            )