"""GeoRide Trips sensors - VERSION COMPLETE SIMPLE."""
import logging
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfElectricPotential, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, DEFAULT_TRIPS_DAYS_BACK as TRIPS_DAYS_BACK, METERS_TO_KM, KNOTS_TO_KMH

_LOGGER = logging.getLogger(__name__)

# Constantes de conversion
MILLISECONDS_TO_MINUTES = 60000
MILLISECONDS_TO_HOURS = 3600000


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GeoRide Trips sensors from a config entry."""
    _LOGGER.info("Setting up GeoRide Trips sensors from config entry")

    data = hass.data[DOMAIN][entry.entry_id]
    trackers = data["trackers"]
    coordinators = data["coordinators"]
    lifetime_coordinators = data["lifetime_coordinators"]
    tracker_status_coordinators = data["tracker_status_coordinators"]
    socket_manager = data.get("socket_manager")

    sensors = []
    for tracker in trackers:
        tracker_id = str(tracker.get("trackerId"))
        coordinator = coordinators[tracker_id]
        lifetime_coordinator = lifetime_coordinators[tracker_id]
        status_coordinator = tracker_status_coordinators[tracker_id]

        sensors.extend([
            GeoRideLastTripSensor(coordinator, entry, tracker),
            GeoRideLastTripDetailsSensor(coordinator, entry, tracker),
            GeoRideTotalDistanceSensor(coordinator, entry, tracker),
            GeoRideTripCountSensor(coordinator, entry, tracker),
            GeoRideLifetimeOdometerSensor(lifetime_coordinator, entry, tracker),
            GeoRideRealOdometerSensor(lifetime_coordinator, entry, tracker, hass),
            # Sensors alimentés par le coordinator status (données /user/trackers)
            GeoRideTrackerStatusSensor(status_coordinator, entry, tracker),
            GeoRideExternalBatterySensor(status_coordinator, entry, tracker),
            GeoRideInternalBatterySensor(status_coordinator, entry, tracker),
            # Sensor dernière alarme (alimenté par Socket.IO)
            GeoRideLastAlarmSensor(entry, tracker),
        ])

    async_add_entities(sensors)
    _LOGGER.info("Added %d sensors for %d trackers", len(sensors), len(trackers))

    # Enregistrer les callbacks last_alarm une fois les entités créées
    # Le socket_manager peut être None si Socket.IO est désactivé ou pas encore démarré
    # Les entités GeoRideLastAlarmSensor s'enregistrent elles-mêmes via async_added_to_hass


# ════════════════════════════════════════════════════════════════════════════
# COORDINATORS
# ════════════════════════════════════════════════════════════════════════════

class GeoRideTripsCoordinator(DataUpdateCoordinator):
    """Coordinator to manage fetching GeoRide trips data (30 days)."""

    def __init__(self, hass, api, tracker_id, tracker_name, scan_interval=3600, trips_days_back=30):
        self.api = api
        self.tracker_id = tracker_id
        self.tracker_name = tracker_name
        self.trips_days_back = trips_days_back

        super().__init__(
            hass,
            _LOGGER,
            name=f"GeoRide Trips {tracker_name}",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self):
        try:
            from_date = datetime.now() - timedelta(days=self.trips_days_back)
            to_date = datetime.now()

            trips = await self.api.get_trips(self.tracker_id, from_date, to_date)

            if trips:
                trips.sort(key=lambda x: x.get("startTime", ""), reverse=True)

            _LOGGER.debug("Fetched %d trips for tracker %s", len(trips), self.tracker_id)
            return trips

        except Exception as err:
            raise UpdateFailed(f"Error fetching trips: {err}")


class GeoRideLifetimeTripsCoordinator(DataUpdateCoordinator):
    """Coordinator to manage fetching ALL trips since tracker creation."""

    def __init__(self, hass, api, tracker_id, tracker_name, activation_date, lifetime_scan_interval=86400):
        self.api = api
        self.tracker_id = tracker_id
        self.tracker_name = tracker_name
        self.activation_date = activation_date

        super().__init__(
            hass,
            _LOGGER,
            name=f"GeoRide Lifetime {tracker_name}",
            update_interval=timedelta(seconds=lifetime_scan_interval),
        )

    async def _async_update_data(self):
        try:
            if self.activation_date:
                try:
                    from_date = datetime.fromisoformat(self.activation_date.replace('Z', '+00:00'))
                except Exception:
                    from_date = datetime.now() - timedelta(days=1825)
            else:
                from_date = datetime.now() - timedelta(days=1825)

            to_date = datetime.now()

            _LOGGER.info(
                "Fetching lifetime trips for %s from %s to %s",
                self.tracker_name, from_date.date(), to_date.date()
            )

            trips = await self.api.get_trips(self.tracker_id, from_date, to_date)

            if trips:
                trips.sort(key=lambda x: x.get("startTime", ""))

            _LOGGER.info("Fetched %d lifetime trips for tracker %s", len(trips), self.tracker_id)

            return {
                "trips": trips,
                "from_date": from_date,
                "to_date": to_date,
            }

        except Exception as err:
            raise UpdateFailed(f"Error fetching lifetime trips: {err}")


class GeoRideTrackerStatusCoordinator(DataUpdateCoordinator):
    """Coordinator polling /user/trackers every 5 min.

    Provides: battery voltages, eco mode, moving, stolen, crashed, status (online/offline),
    isLocked, latitude/longitude — used as fallback when Socket.IO is unavailable.
    """

    def __init__(self, hass, api, tracker_id: str, tracker_name: str, scan_interval: int = 300):
        self.api = api
        self.tracker_id = tracker_id
        self.tracker_name = tracker_name

        super().__init__(
            hass,
            _LOGGER,
            name=f"GeoRide Status {tracker_name}",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict:
        """Return the raw tracker dict for this tracker_id."""
        try:
            trackers = await self.api.get_trackers()
            for tracker in trackers:
                if str(tracker.get("trackerId")) == self.tracker_id:
                    _LOGGER.debug(
                        "Status update for tracker %s: moving=%s eco=%s status=%s",
                        self.tracker_id,
                        tracker.get("moving"),
                        tracker.get("isInEco"),
                        tracker.get("status"),
                    )
                    return tracker
            _LOGGER.warning("Tracker %s not found in /user/trackers response", self.tracker_id)
            return {}
        except Exception as err:
            raise UpdateFailed(f"Error fetching tracker status: {err}")


# ════════════════════════════════════════════════════════════════════════════
# SENSORS — TRIPS
# ════════════════════════════════════════════════════════════════════════════

class GeoRideLastTripSensor(CoordinatorEntity, SensorEntity):
    """Sensor for last trip (simple)."""

    def __init__(self, coordinator, entry, tracker):
        super().__init__(coordinator)
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._attr_name = f"{self.tracker_name} Last Trip"
        self._attr_unique_id = f"{self.tracker_id}_last_trip"
        self._attr_icon = "mdi:map-marker-path"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def native_value(self):
        trips = self.coordinator.data
        if not trips:
            return None
        return trips[0].get("startTime")


class GeoRideLastTripDetailsSensor(CoordinatorEntity, SensorEntity):
    """Sensor for last trip with detailed info."""

    def __init__(self, coordinator, entry, tracker):
        super().__init__(coordinator)
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._attr_name = f"{self.tracker_name} Last Trip Details"
        self._attr_unique_id = f"{self.tracker_id}_last_trip_details"
        self._attr_icon = "mdi:map-marker-star"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def native_value(self):
        trips = self.coordinator.data
        if not trips:
            return "Aucun trajet"
        trip = trips[0]
        distance_km = trip.get("distance", 0) / METERS_TO_KM
        duration_min = trip.get("duration", 0) / MILLISECONDS_TO_MINUTES
        return f"{distance_km:.1f} km - {duration_min:.0f} min"

    @property
    def extra_state_attributes(self):
        trips = self.coordinator.data
        if not trips:
            return {}
        trip = trips[0]

        distance_m = trip.get("distance", 0)
        distance_km = distance_m / METERS_TO_KM
        duration_ms = trip.get("duration", 0)
        duration_min = duration_ms / MILLISECONDS_TO_MINUTES
        duration_hours = duration_ms / MILLISECONDS_TO_HOURS
        avg_speed_kmh = trip.get("averageSpeed", 0) * KNOTS_TO_KMH
        max_speed_kmh = trip.get("maxSpeed", 0) * KNOTS_TO_KMH

        start_time = trip.get("startTime", "")
        end_time = trip.get("endTime", "")

        try:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            date_formatted = start_dt.strftime("%d/%m/%Y")
            start_hour = start_dt.strftime("%H:%M")
        except Exception:
            date_formatted = ""
            start_hour = ""

        try:
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            end_hour = end_dt.strftime("%H:%M")
        except Exception:
            end_hour = ""

        time_range = f"{start_hour} - {end_hour}" if start_hour and end_hour else ""
        distance_formatted = f"{distance_km:.1f} km"
        duration_formatted = f"{int(duration_min)} min" if duration_min < 60 else f"{duration_hours:.1f}h"
        speed_formatted = f"{avg_speed_kmh:.1f} km/h"
        summary = f"{distance_formatted} en {duration_formatted} à {speed_formatted}"

        return {
            "trip_id": trip.get("id"),
            "nice_name": trip.get("niceName", ""),
            "start_time": start_time,
            "end_time": end_time,
            "date_formatted": date_formatted,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "time_range": time_range,
            "distance_km": round(distance_km, 2),
            "distance_formatted": distance_formatted,
            "duration_minutes": round(duration_min, 1),
            "duration_formatted": duration_formatted,
            "average_speed_kmh": round(avg_speed_kmh, 1),
            "max_speed_kmh": round(max_speed_kmh, 1),
            "speed_formatted": speed_formatted,
            "summary": summary,
            "trip_summary": f"{date_formatted} {time_range}",
            "start_address": trip.get("startAddress", ""),
            "end_address": trip.get("endAddress", ""),
            "start_latitude": trip.get("startLatitude") or trip.get("startLat"),
            "start_longitude": trip.get("startLongitude") or trip.get("startLon"),
            "end_latitude": trip.get("endLatitude") or trip.get("endLat"),
            "end_longitude": trip.get("endLongitude") or trip.get("endLon"),
        }


class GeoRideTotalDistanceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for total distance over period."""

    def __init__(self, coordinator, entry, tracker):
        super().__init__(coordinator)
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._attr_name = f"{self.tracker_name} Total Distance"
        self._attr_unique_id = f"{self.tracker_id}_total_distance"
        self._attr_icon = "mdi:map-marker-distance"
        self._attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
        self._attr_device_class = SensorDeviceClass.DISTANCE

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def native_value(self):
        trips = self.coordinator.data
        if not trips:
            return 0
        total_m = sum(trip.get("distance", 0) for trip in trips)
        return round(total_m / METERS_TO_KM, 2)


class GeoRideTripCountSensor(CoordinatorEntity, SensorEntity):
    """Sensor for trip count over period."""

    def __init__(self, coordinator, entry, tracker):
        super().__init__(coordinator)
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._attr_name = f"{self.tracker_name} Trip Count"
        self._attr_unique_id = f"{self.tracker_id}_trip_count"
        self._attr_icon = "mdi:counter"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def native_value(self):
        trips = self.coordinator.data
        return len(trips) if trips else 0


# ════════════════════════════════════════════════════════════════════════════
# SENSORS — LIFETIME ODOMETER
# ════════════════════════════════════════════════════════════════════════════

class GeoRideLifetimeOdometerSensor(CoordinatorEntity, SensorEntity):
    """Sensor for lifetime odometer."""

    def __init__(self, coordinator, entry, tracker):
        super().__init__(coordinator)
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._attr_name = f"{self.tracker_name} Lifetime Odometer"
        self._attr_unique_id = f"{self.tracker_id}_lifetime_odometer"
        self._attr_icon = "mdi:counter"
        self._attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
        self._attr_device_class = SensorDeviceClass.DISTANCE
        self._attr_state_class = "total_increasing"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data or "trips" not in data:
            return 0
        trips = data["trips"]
        total_m = sum(trip.get("distance", 0) for trip in trips)
        return round(total_m / METERS_TO_KM, 2)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        if not data or "trips" not in data:
            return {}
        trips = data["trips"]

        total_distance_m = sum(trip.get("distance", 0) for trip in trips)
        total_duration_ms = sum(trip.get("duration", 0) for trip in trips)
        total_duration_hours = round(total_duration_ms / MILLISECONDS_TO_HOURS, 2)

        if trips:
            sorted_trips = sorted(trips, key=lambda x: x.get("startTime", ""))
            first_trip_date = sorted_trips[0].get("startTime", "")
            last_trip_date = sorted_trips[-1].get("startTime", "")
        else:
            first_trip_date = ""
            last_trip_date = ""

        from_date = data.get("from_date")
        to_date = data.get("to_date")
        if from_date and to_date:
            try:
                if from_date.tzinfo is None:
                    from_date = from_date.replace(tzinfo=to_date.tzinfo)
                elif to_date.tzinfo is None:
                    to_date = to_date.replace(tzinfo=from_date.tzinfo)
                days_tracked = (to_date - from_date).days
            except Exception:
                days_tracked = 0
        else:
            days_tracked = 0

        return {
            "total_trips": len(trips),
            "total_distance_m": total_distance_m,
            "total_duration_hours": total_duration_hours,
            "total_duration_days": round(total_duration_hours / 24, 2),
            "average_distance_per_trip_km": round(total_distance_m / METERS_TO_KM / len(trips), 2) if trips else 0,
            "average_distance_per_day_km": round(total_distance_m / METERS_TO_KM / days_tracked, 2) if days_tracked > 0 else 0,
            "first_trip_date": first_trip_date,
            "last_trip_date": last_trip_date,
            "days_tracked": days_tracked,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
        }


class GeoRideRealOdometerSensor(CoordinatorEntity, SensorEntity):
    """Sensor for real odometer = lifetime + offset from number entity."""

    def __init__(self, coordinator, entry, tracker, hass):
        super().__init__(coordinator)
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._hass = hass
        self._attr_name = f"{self.tracker_name} Odometer"
        self._attr_unique_id = f"{self.tracker_id}_real_odometer"
        self._attr_icon = "mdi:counter"
        self._attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
        self._attr_device_class = SensorDeviceClass.DISTANCE
        self._attr_state_class = "total_increasing"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        offset_entity_id = f"number.{self.tracker_name.lower().replace(' ', '_')}_odometer_offset"
        from homeassistant.helpers.event import async_track_state_change_event
        self.async_on_remove(
            async_track_state_change_event(
                self._hass,
                [offset_entity_id],
                self._handle_offset_state_change,
            )
        )

    async def _handle_offset_state_change(self, event) -> None:
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data or "trips" not in data:
            return 0
        trips = data["trips"]
        tracker_km = sum(trip.get("distance", 0) for trip in trips) / METERS_TO_KM
        offset_entity_id = f"number.{self.tracker_name.lower().replace(' ', '_')}_odometer_offset"
        offset = self._hass.states.get(offset_entity_id)
        offset_km = float(offset.state) if offset and offset.state not in ("unknown", "unavailable") else 0
        return round(tracker_km + offset_km, 2)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        if not data or "trips" not in data:
            return {}
        trips = data["trips"]
        tracker_km = sum(trip.get("distance", 0) for trip in trips) / METERS_TO_KM
        offset_entity_id = f"number.{self.tracker_name.lower().replace(' ', '_')}_odometer_offset"
        offset = self._hass.states.get(offset_entity_id)
        offset_km = float(offset.state) if offset and offset.state not in ("unknown", "unavailable") else 0
        total_duration_ms = sum(trip.get("duration", 0) for trip in trips)
        total_duration_hours = round(total_duration_ms / MILLISECONDS_TO_HOURS, 2)

        if trips:
            sorted_trips = sorted(trips, key=lambda x: x.get("startTime", ""))
            first_trip_date = sorted_trips[0].get("startTime", "")
            last_trip_date = sorted_trips[-1].get("startTime", "")
        else:
            first_trip_date = ""
            last_trip_date = ""

        return {
            "total_trips": len(trips),
            "total_duration_hours": total_duration_hours,
            "first_trip_date": first_trip_date,
            "last_trip_date": last_trip_date,
            "tracker_km": round(tracker_km, 2),
            "offset_km": round(offset_km, 2),
            "offset_entity": offset_entity_id,
        }

    def set_odometer(self, value: float):
        """Set the odometer to a specific value by calculating offset."""
        data = self.coordinator.data
        if not data or "trips" not in data:
            _LOGGER.error("Cannot set odometer: no trip data available")
            return
        trips = data["trips"]
        tracker_km = sum(trip.get("distance", 0) for trip in trips) / METERS_TO_KM
        offset_km = value - tracker_km
        offset_entity_id = f"number.{self.tracker_name.lower().replace(' ', '_')}_odometer_offset"
        self._hass.async_create_task(
            self._hass.services.async_call(
                "number", "set_value",
                {"entity_id": offset_entity_id, "value": offset_km},
            )
        )
        _LOGGER.info(
            "Odometer set for %s: %s km (tracker=%s km, offset=%s km)",
            self.tracker_name, value, tracker_km, offset_km
        )


# ════════════════════════════════════════════════════════════════════════════
# SENSORS — TRACKER STATUS (alimentés par GeoRideTrackerStatusCoordinator)
# ════════════════════════════════════════════════════════════════════════════

class GeoRideTrackerStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposant le statut réseau du tracker (online / offline)."""

    def __init__(self, coordinator: GeoRideTrackerStatusCoordinator, entry, tracker):
        super().__init__(coordinator)
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._attr_name = f"{self.tracker_name} Status"
        self._attr_unique_id = f"{self.tracker_id}_tracker_status"
        self._attr_icon = "mdi:signal"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if not data:
            return None
        return data.get("status")

    @property
    def icon(self) -> str:
        if self.coordinator.data and self.coordinator.data.get("status") == "online":
            return "mdi:signal"
        return "mdi:signal-off"


class GeoRideExternalBatterySensor(CoordinatorEntity, SensorEntity):
    """Sensor pour la tension de la batterie externe (GeoRide 3 only)."""

    def __init__(self, coordinator: GeoRideTrackerStatusCoordinator, entry, tracker):
        super().__init__(coordinator)
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._attr_name = f"{self.tracker_name} Batterie externe"
        self._attr_unique_id = f"{self.tracker_id}_external_battery"
        self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:battery-charging"
        self._attr_suggested_display_precision = 2

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if not data:
            return None
        voltage = data.get("externalBatteryVoltage")
        if voltage is None:
            return None
        try:
            return round(float(voltage), 2)
        except (ValueError, TypeError):
            return None

    @property
    def available(self) -> bool:
        """Disponible uniquement si le tracker retourne cette valeur (GeoRide 3)."""
        if not self.coordinator.last_update_success:
            return False
        data = self.coordinator.data
        return bool(data and data.get("externalBatteryVoltage") is not None)


class GeoRideInternalBatterySensor(CoordinatorEntity, SensorEntity):
    """Sensor pour la tension de la batterie interne (GeoRide 3 only)."""

    def __init__(self, coordinator: GeoRideTrackerStatusCoordinator, entry, tracker):
        super().__init__(coordinator)
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._attr_name = f"{self.tracker_name} Batterie interne"
        self._attr_unique_id = f"{self.tracker_id}_internal_battery"
        self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:battery"
        self._attr_suggested_display_precision = 2

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if not data:
            return None
        voltage = data.get("internalBatteryVoltage")
        if voltage is None:
            return None
        try:
            return round(float(voltage), 2)
        except (ValueError, TypeError):
            return None

    @property
    def available(self) -> bool:
        """Disponible uniquement si le tracker retourne cette valeur (GeoRide 3)."""
        if not self.coordinator.last_update_success:
            return False
        data = self.coordinator.data
        return bool(data and data.get("internalBatteryVoltage") is not None)


# ════════════════════════════════════════════════════════════════════════════
# SENSOR — LAST ALARM (alimenté par Socket.IO)
# ════════════════════════════════════════════════════════════════════════════

class GeoRideLastAlarmSensor(RestoreEntity, SensorEntity):
    """Sensor exposant le type de la dernière alarme reçue via Socket.IO."""

    def __init__(self, entry, tracker):
        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._entry = entry
        self._tracker = tracker
        self._attr_name = f"{self.tracker_name} Last Alarm"
        self._attr_unique_id = f"{self.tracker_id}_last_alarm"
        self._attr_icon = "mdi:alarm-light"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._state: str | None = None
        self._alarm_timestamp: str | None = None
        self._device_name: str | None = None
        self._unregister_alarm: callable | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    @property
    def native_value(self) -> str | None:
        return self._state

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "timestamp": self._alarm_timestamp,
            "device_name": self._device_name,
            "tracker_id": self.tracker_id,
        }

    async def async_added_to_hass(self) -> None:
        """Restaurer l'état et s'enregistrer auprès du socket_manager."""
        await super().async_added_to_hass()

        # Restauration depuis le recorder
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable"):
            self._state = last_state.state
            self._alarm_timestamp = last_state.attributes.get("timestamp")
            self._device_name = last_state.attributes.get("device_name")

        # Enregistrement du callback Socket.IO
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        socket_manager = entry_data.get("socket_manager")
        if socket_manager:
            self._unregister_alarm = socket_manager.register_callback(
                self.tracker_id, "alarm", self._handle_alarm
            )
            _LOGGER.debug("LastAlarmSensor %s registered with socket_manager", self.tracker_id)
        else:
            _LOGGER.debug(
                "LastAlarmSensor %s: pas de socket_manager disponible au démarrage "
                "(normal si Socket.IO démarre après les entités)",
                self.tracker_id,
            )

    async def async_will_remove_from_hass(self) -> None:
        """Se désinscrire du socket_manager."""
        if self._unregister_alarm:
            self._unregister_alarm()
            self._unregister_alarm = None

    def _handle_alarm(self, data: dict) -> None:
        """Callback appelé par socket_manager lors d'une alarme."""
        alarm_type = data.get("alarmType") or data.get("type")
        if not alarm_type:
            return

        self._state = alarm_type
        self._alarm_timestamp = data.get("timestamp") or data.get("date")
        self._device_name = data.get("device_name") or self.tracker_name

        self.schedule_update_ha_state()
        _LOGGER.info(
            "LastAlarmSensor %s: nouvelle alarme %s",
            self.tracker_id, alarm_type,
        )