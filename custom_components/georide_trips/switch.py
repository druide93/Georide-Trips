"""GeoRide Trips switch entities.

Switches rattachés au device de chaque moto :
- Mode éco    : reflète et contrôle isInEco via l'API GeoRide.
- Verrouillage : reflète et contrôle isLocked via l'API GeoRide.

Note : Les indicateurs d'entretien (plein requis, chaîne, vidange, révision)
sont désormais des binary_sensor calculés en temps réel (read-only).
Voir binary_sensor.py : GeoRidePleinRequisBinarySensor, etc.
"""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GeoRide Trips switch entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    trackers = data["trackers"]
    tracker_status_coordinators = data["tracker_status_coordinators"]
    api = data["api"]

    entities = []
    for tracker in trackers:
        tracker_id = str(tracker.get("trackerId"))
        status_coordinator = tracker_status_coordinators[tracker_id]
        entities.extend([
            GeoRideEcoModeSwitch(status_coordinator, entry, tracker, api),
            GeoRideLockSwitch(status_coordinator, entry, tracker, api),
        ])

    async_add_entities(entities)
    _LOGGER.info("Added %d switches for %d trackers", len(entities), len(trackers))


class GeoRideEcoModeSwitch(CoordinatorEntity, SwitchEntity):
    """Switch pour activer/désactiver le mode éco du tracker GeoRide.

    L'état est lu depuis le GeoRideTrackerStatusCoordinator (polling /user/trackers).
    Le changement est envoyé via PUT /tracker/{id}/eco.
    """

    def __init__(self, coordinator, entry: ConfigEntry, tracker: dict, api) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._tracker = tracker
        self._api = api
        self._tracker_id = str(tracker.get("trackerId"))
        self._tracker_name = tracker.get("trackerName", f"Tracker {self._tracker_id}")
        self._attr_unique_id = f"{self._tracker_id}_eco_mode"
        self._attr_name = f"{self._tracker_name} Mode éco"
        self._attr_icon = "mdi:leaf"
        self._attr_entity_category = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._tracker_id)},
            name=f"{self._tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not data:
            return None
        return bool(data.get("isInEco", False))

    @property
    def icon(self) -> str:
        return "mdi:leaf" if self.is_on else "mdi:leaf-off"

    async def async_turn_on(self, **kwargs) -> None:
        """Activer le mode éco."""
        success = await self._api.set_eco_mode(self._tracker_id, True)
        if success:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Désactiver le mode éco."""
        success = await self._api.set_eco_mode(self._tracker_id, False)
        if success:
            await self.coordinator.async_request_refresh()


class GeoRideLockSwitch(CoordinatorEntity, SwitchEntity):
    """Switch pour verrouiller/déverrouiller le tracker GeoRide.

    L'état est lu depuis le GeoRideTrackerStatusCoordinator (champ `isLocked`).
    Le basculement est envoyé via POST /tracker/{id}/toggleLock.
    On = verrouillé, Off = déverrouillé.
    """

    def __init__(self, coordinator, entry: ConfigEntry, tracker: dict, api) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._tracker = tracker
        self._api = api
        self._tracker_id = str(tracker.get("trackerId"))
        self._tracker_name = tracker.get("trackerName", f"Tracker {self._tracker_id}")
        self._attr_unique_id = f"{self._tracker_id}_lock"
        self._attr_name = f"{self._tracker_name} Verrouillage"
        self._attr_icon = "mdi:lock"
        self._attr_entity_category = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._tracker_id)},
            name=f"{self._tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not data:
            return None
        return bool(data.get("isLocked", False))

    @property
    def icon(self) -> str:
        return "mdi:lock" if self.is_on else "mdi:lock-open-variant"

    async def _toggle_if_needed(self, target_locked: bool) -> None:
        """Appelle toggleLock seulement si l'état actuel diffère de la cible."""
        current = self.is_on
        if current is None or current != target_locked:
            new_state = await self._api.toggle_lock(self._tracker_id)
            if new_state is not None:
                await self.coordinator.async_request_refresh()
        else:
            _LOGGER.debug(
                "Tracker %s already %s, skipping toggle",
                self._tracker_id,
                "locked" if target_locked else "unlocked",
            )

    async def async_turn_on(self, **kwargs) -> None:
        """Verrouiller le tracker."""
        await self._toggle_if_needed(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Déverrouiller le tracker."""
        await self._toggle_if_needed(False)