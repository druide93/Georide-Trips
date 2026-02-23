"""GeoRide Trips buttons - Refresh buttons and maintenance record buttons."""
import logging
from datetime import datetime

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GeoRide Trips buttons from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    trackers = data["trackers"]
    coordinators = data["coordinators"]
    lifetime_coordinators = data["lifetime_coordinators"]

    buttons = []
    for tracker in trackers:
        tracker_id = str(tracker.get("trackerId"))

        buttons.extend([
            GeoRideRefreshTripsButton(
                entry, tracker,
                coordinators[tracker_id]
            ),
            GeoRideRefreshOdometerButton(
                entry, tracker,
                lifetime_coordinators[tracker_id]
            ),
            GeoRideRecordMaintenanceButton(
                hass, entry, tracker, "chaine",
                icon="mdi:link-variant",
                odometer_entity=f"sensor.{tracker.get('trackerName', tracker_id).lower().replace(' ', '_')}_odometer",
                km_entity=f"number.{tracker.get('trackerName', tracker_id).lower().replace(' ', '_')}_entretien_chaine_km_au_dernier_entretien",
                dt_entity=f"datetime.{tracker.get('trackerName', tracker_id).lower().replace(' ', '_')}_entretien_chaine_date_dernier_entretien",
            ),
            GeoRideRecordMaintenanceButton(
                hass, entry, tracker, "vidange",
                icon="mdi:oil",
                odometer_entity=f"sensor.{tracker.get('trackerName', tracker_id).lower().replace(' ', '_')}_odometer",
                km_entity=f"number.{tracker.get('trackerName', tracker_id).lower().replace(' ', '_')}_vidange_km_a_la_derniere_vidange",
                dt_entity=f"datetime.{tracker.get('trackerName', tracker_id).lower().replace(' ', '_')}_vidange_date_derniere_vidange",
            ),
            GeoRideRecordMaintenanceButton(
                hass, entry, tracker, "revision",
                icon="mdi:wrench",
                odometer_entity=f"sensor.{tracker.get('trackerName', tracker_id).lower().replace(' ', '_')}_odometer",
                km_entity=f"number.{tracker.get('trackerName', tracker_id).lower().replace(' ', '_')}_revision_km_a_la_derniere_revision",
                dt_entity=f"datetime.{tracker.get('trackerName', tracker_id).lower().replace(' ', '_')}_revision_date_derniere_revision",
            ),
        ])

    async_add_entities(buttons)
    _LOGGER.info("Added %d buttons for %d trackers", len(buttons), len(trackers))


class GeoRideRefreshTripsButton(ButtonEntity):
    """Button to manually refresh recent trips."""

    def __init__(self, entry, tracker, coordinator):
        """Initialize the button."""
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._coordinator = coordinator

        self._attr_name = f"{self.tracker_name} Refresh Trips"
        self._attr_unique_id = f"{self.tracker_id}_refresh_trips"
        self._attr_icon = "mdi:refresh"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    async def async_press(self) -> None:
        """Handle the button press - refresh recent trips."""
        _LOGGER.info("Manual refresh triggered for trips: %s", self.tracker_name)
        await self._coordinator.async_request_refresh()


class GeoRideRefreshOdometerButton(ButtonEntity):
    """Button to manually refresh lifetime odometer."""

    def __init__(self, entry, tracker, coordinator):
        """Initialize the button."""
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._coordinator = coordinator

        self._attr_name = f"{self.tracker_name} Refresh Odometer"
        self._attr_unique_id = f"{self.tracker_id}_refresh_odometer"
        self._attr_icon = "mdi:counter"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    async def async_press(self) -> None:
        """Handle the button press - refresh lifetime odometer."""
        _LOGGER.info("Manual refresh triggered for odometer: %s", self.tracker_name)
        await self._coordinator.async_request_refresh()


class GeoRideRecordMaintenanceButton(ButtonEntity):
    """Button to record a maintenance event (chain, oil change, revision)."""

    LABEL = {
        "chaine":   "Enregistrer entretien chaîne",
        "vidange":  "Enregistrer vidange",
        "revision": "Enregistrer révision",
    }

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tracker: dict,
        maintenance_type: str,
        icon: str,
        odometer_entity: str,
        km_entity: str,
        dt_entity: str,
    ) -> None:
        """Initialize the maintenance record button."""
        self._hass = hass
        self._entry = entry
        self._tracker = tracker
        self._maintenance_type = maintenance_type
        self._odometer_entity = odometer_entity
        self._km_entity = km_entity
        self._dt_entity = dt_entity

        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")

        label = self.LABEL.get(maintenance_type, maintenance_type)
        self._attr_name = f"{self.tracker_name} {label}"
        self._attr_unique_id = f"{self.tracker_id}_record_{maintenance_type}"
        self._attr_icon = icon

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    async def async_press(self) -> None:
        """Record maintenance: snapshot odometer KM + current datetime."""
        odometer_state = self._hass.states.get(self._odometer_entity)
        if odometer_state is None or odometer_state.state in ("unknown", "unavailable"):
            _LOGGER.warning(
                "Cannot record %s for %s: odometer entity '%s' unavailable",
                self._maintenance_type, self.tracker_name, self._odometer_entity,
            )
            return

        try:
            odometer_km = float(odometer_state.state)
        except ValueError:
            _LOGGER.error(
                "Cannot parse odometer value '%s' for %s",
                odometer_state.state, self.tracker_name,
            )
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Mise à jour du KM
        await self._hass.services.async_call(
            "number", "set_value",
            {"entity_id": self._km_entity, "value": odometer_km},
            blocking=True,
        )

        # Mise à jour de la date
        await self._hass.services.async_call(
            "datetime", "set_value",
            {"entity_id": self._dt_entity, "datetime": now_str},
            blocking=True,
        )

        _LOGGER.info(
            "Recorded %s for %s: %.1f km on %s",
            self._maintenance_type, self.tracker_name, odometer_km, now_str,
        )