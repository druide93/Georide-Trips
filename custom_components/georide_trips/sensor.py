"""GeoRide Trips sensors - VERSION COMPLETE SIMPLE."""
import logging
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfElectricPotential, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
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

        # Planifier le refresh minuit du coordinator lifetime
        lifetime_coordinator.schedule_midnight_refresh()

        # Dès qu'un arrêt est confirmé (verrouillage) → refresh immédiat du coordinator lifetime
        # on_stop_confirmed est one-shot : on le re-enregistre à chaque déclenchement
        def _register_stop_cb(lc=lifetime_coordinator, coord=coordinator):
            def _on_stop(lc=lc, coord=coord):
                hass.async_create_task(lc.async_request_refresh())
                # Re-enregistrer pour le prochain arrêt
                _register_stop_cb(lc, coord)
            coord.on_stop_confirmed(_on_stop)

        _register_stop_cb(lifetime_coordinator, coordinator)

        odometer_sensor = GeoRideRealOdometerSensor(lifetime_coordinator, coordinator, entry, tracker, hass)
        autonomy_sensor = GeoRideAutonomySensor(entry, tracker, hass, odometer_sensor)

        # Gestionnaire des snapshots minuit — remplace le trigger 'minuit' du blueprint
        midnight_manager = GeoRideMidnightSnapshotManager(hass, entry, tracker, odometer_sensor)
        midnight_manager.setup()
        entry.async_on_unload(midnight_manager.unschedule)

        sensors.extend([
            GeoRideLastTripSensor(coordinator, entry, tracker),
            GeoRideLastTripDetailsSensor(coordinator, entry, tracker),
            GeoRideTotalDistanceSensor(coordinator, entry, tracker),
            GeoRideTripCountSensor(coordinator, entry, tracker),
            GeoRideLifetimeOdometerSensor(lifetime_coordinator, entry, tracker),
            # RealOdometer écoute les deux coordinators : lifetime (base solide)
            # + coordinator récent (nouveaux trajets intra-journaliers)
            odometer_sensor,
            # Sensor autonomie restante (réactif sur odometer + entities carburant)
            autonomy_sensor,
            # Sensors km périodiques — calculés en Python, réactifs sur odometer + snapshot
            GeoRideKmJournaliersSensor(entry, tracker, hass, odometer_sensor),
            GeoRideKmHebdomadairesSensor(entry, tracker, hass, odometer_sensor),
            GeoRideKmMensuelsSensor(entry, tracker, hass, odometer_sensor),
            # Sensors entretien — km restants et jours restants calculés en Python
            GeoRideKmRestantsChaineSensor(entry, tracker, hass, odometer_sensor),
            GeoRideKmRestantsVidangeSensor(entry, tracker, hass, odometer_sensor),
            GeoRideKmRestantsRevisionSensor(entry, tracker, hass, odometer_sensor),
            GeoRideJoursRestantsRevisionSensor(entry, tracker, hass),
            # Sensors alimentés par le coordinator status (données /user/trackers)
            GeoRideTrackerStatusSensor(status_coordinator, entry, tracker),
            GeoRideExternalBatterySensor(status_coordinator, entry, tracker),
            GeoRideInternalBatterySensor(status_coordinator, entry, tracker),
            # Sensor dernière alarme (alimenté par Socket.IO)
            GeoRideLastAlarmSensor(entry, tracker),
        ])

    async_add_entities(sensors)
    _LOGGER.info("Added %d sensors for %d trackers", len(sensors), len(trackers))


# ════════════════════════════════════════════════════════════════════════════
# COORDINATORS
# ════════════════════════════════════════════════════════════════════════════

class GeoRideTripsCoordinator(DataUpdateCoordinator):
    """Coordinator to manage fetching GeoRide trips data (30 days).

    Détecte la fin de trajet via le StatusCoordinator (polling 5 min) :
    dès que isLocked passe à True (transition déverrouillé → verrouillé),
    un refresh est déclenché. Le verrouillage est le seul signal fiable
    de fin de trajet, insensible aux micro-arrêts (feux rouges, etc.).
    """

    def __init__(self, hass, api, tracker_id, tracker_name, scan_interval=3600, trips_days_back=30):
        self.api = api
        self.tracker_id = tracker_id
        self.tracker_name = tracker_name
        self.trips_days_back = trips_days_back
        self._stop_confirmed_callbacks: list = []
        self._status_unsub: callable | None = None
        self._status_coordinator = None
        self._last_locked_state: bool | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"GeoRide Trips {tracker_name}",
            update_interval=timedelta(seconds=scan_interval),
        )

    def on_stop_confirmed(self, callback) -> callable:
        """Enregistrer un callback one-shot appelé lors du verrouillage du tracker.

        Le callback est automatiquement retiré après le premier appel.

        Returns:
            Fonction de désenregistrement (pour annulation anticipée).
        """
        self._stop_confirmed_callbacks.append(callback)
        def unregister():
            try:
                self._stop_confirmed_callbacks.remove(callback)
            except ValueError:
                pass
        return unregister

    def attach_status_coordinator(self, status_coordinator) -> None:
        """S'abonner au StatusCoordinator pour détecter le verrouillage du tracker.

        Déclenche un refresh dès que isLocked passe de False à True
        (transition déverrouillé → verrouillé = fin de trajet confirmée).
        Polling toutes les 5 min — fiable et insensible aux micro-arrêts.

        À appeler après le premier refresh du StatusCoordinator.
        """
        if status_coordinator is None:
            return
        self._status_coordinator = status_coordinator
        # Initialiser l'état locked connu pour éviter un faux déclenchement au démarrage
        data = status_coordinator.data
        if data:
            self._last_locked_state = bool(data.get("isLocked", False))
        self._status_unsub = status_coordinator.async_add_listener(
            self._handle_status_update
        )
        _LOGGER.debug(
            "TripsCoordinator %s: abonné au StatusCoordinator (lock detection active, état initial locked=%s)",
            self.tracker_name, self._last_locked_state,
        )

    def detach_status_coordinator(self) -> None:
        """Se désabonner du StatusCoordinator (appelé au unload)."""
        if self._status_unsub:
            self._status_unsub()
            self._status_unsub = None
        self._status_coordinator = None

    @callback
    def _handle_status_update(self) -> None:
        """Appelé à chaque polling du StatusCoordinator (~5 min).

        Détecte la transition déverrouillé → verrouillé (isLocked False → True)
        comme signal fiable de fin de trajet.
        """
        if self._status_coordinator is None:
            return
        data = self._status_coordinator.data
        if not data:
            return

        is_locked = bool(data.get("isLocked", False))

        # Transition False → True uniquement (évite le déclenchement au démarrage
        # ou sur une valeur True stable)
        if is_locked and self._last_locked_state is False:
            _LOGGER.info(
                "%s: verrouillage détecté (isLocked False→True), refresh trips",
                self.tracker_name,
            )
            self._on_lock_confirmed()

        self._last_locked_state = is_locked

    def _on_lock_confirmed(self) -> None:
        """Appelé lors de la détection du verrouillage — refresh + notifier les abonnés."""
        self.hass.async_create_task(self.async_request_refresh())

        # Notifier les callbacks one-shot (ex: bouton confirmer plein)
        callbacks = list(self._stop_confirmed_callbacks)
        self._stop_confirmed_callbacks.clear()
        for cb in callbacks:
            try:
                cb()
            except Exception as err:
                _LOGGER.error(
                    "%s: erreur dans callback on_stop_confirmed : %s",
                    self.tracker_name, err,
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
    """Coordinator to manage fetching ALL trips since tracker creation.

    Refresh forcé à minuit pour avoir une base lifetime à jour en début de journée.
    Les nouveaux trajets intra-journaliers sont captés par le coordinator récent
    et fusionnés dans GeoRideRealOdometerSensor.
    """

    def __init__(self, hass, api, tracker_id, tracker_name, activation_date, lifetime_scan_interval=86400):
        self.api = api
        self.tracker_id = tracker_id
        self.tracker_name = tracker_name
        self.activation_date = activation_date
        self._midnight_unsub = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"GeoRide Lifetime {tracker_name}",
            update_interval=timedelta(seconds=lifetime_scan_interval),
        )

    def schedule_midnight_refresh(self) -> None:
        """Planifier le refresh automatique à minuit (appelé après async_config_entry_first_refresh)."""
        if self._midnight_unsub:
            self._midnight_unsub()
        self._midnight_unsub = async_track_time_change(
            self.hass,
            self._midnight_callback,
            hour=0, minute=0, second=0,
        )
        _LOGGER.debug("Midnight refresh scheduled for lifetime coordinator %s", self.tracker_name)

    def unschedule_midnight_refresh(self) -> None:
        """Annuler le refresh minuit."""
        if self._midnight_unsub:
            self._midnight_unsub()
            self._midnight_unsub = None

    @callback
    def _midnight_callback(self, now) -> None:
        """Déclencher un refresh du coordinator lifetime à minuit."""
        _LOGGER.info("Midnight refresh triggered for lifetime coordinator %s", self.tracker_name)
        self.hass.async_create_task(self.async_request_refresh())

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
# MANAGER — SNAPSHOTS MINUIT (km_debut_journee / semaine / mois)
# ════════════════════════════════════════════════════════════════════════════

class GeoRideMidnightSnapshotManager:
    """Gestionnaire des snapshots odometer à minuit.

    Remplace le trigger 'minuit' du blueprint : à 00:00:00 chaque nuit,
    met à jour les number.km_debut_journee/semaine/mois directement en Python.

    Le jour de reset mensuel est lu depuis number.<slug>_jour_stats_mensuelles
    (configurable par l'utilisateur via l'UI, défaut = 1).

    Usage :
        manager = GeoRideMidnightSnapshotManager(hass, entry, tracker, odometer_sensor)
        manager.setup()          # à appeler dans async_setup_entry
        manager.unschedule()     # à appeler au unload de l'entrée
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tracker: dict,
        odometer_sensor: "GeoRideRealOdometerSensor",
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._tracker = tracker
        self._odometer_sensor = odometer_sensor

        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._slug = self.tracker_name.lower().replace(" ", "_")

        self._entity_debut_journee = f"number.{self._slug}_km_debut_journee"
        self._entity_debut_semaine = f"number.{self._slug}_km_debut_semaine"
        self._entity_debut_mois    = f"number.{self._slug}_km_debut_mois"
        self._entity_jour_mensuel  = f"number.{self._slug}_jour_stats_mensuelles"

        self._unsub: callable | None = None

    def setup(self) -> None:
        """Programmer le callback minuit."""
        self._unsub = async_track_time_change(
            self._hass,
            self._midnight_callback,
            hour=0, minute=0, second=0,
        )
        _LOGGER.debug(
            "MidnightSnapshotManager %s: programmé (snapshots minuit actifs)",
            self.tracker_name,
        )

    def unschedule(self) -> None:
        """Déprogrammer le callback minuit."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    def _get_float(self, entity_id: str, default: float = 0.0) -> float:
        state = self._hass.states.get(entity_id)
        if state and state.state not in (None, "unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return default

    def _set_number(self, entity_id: str, value: float) -> None:
        """Mettre à jour un number via hass.services.async_call."""
        self._hass.async_create_task(
            self._hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": entity_id, "value": round(value, 2)},
                blocking=False,
            )
        )

    @callback
    def _midnight_callback(self, now) -> None:
        """Appelé à minuit : mettre à jour les snapshots odometer."""
        odometer_km = self._odometer_sensor.native_value
        if odometer_km is None:
            _LOGGER.warning(
                "MidnightSnapshotManager %s: odometer non disponible à minuit, snapshots ignorés",
                self.tracker_name,
            )
            return

        # Snapshot journalier — chaque nuit
        self._set_number(self._entity_debut_journee, odometer_km)
        _LOGGER.info(
            "MidnightSnapshotManager %s: km_debut_journee = %.1f km",
            self.tracker_name, odometer_km,
        )

        # Snapshot hebdomadaire — uniquement le lundi (weekday == 0)
        if now.weekday() == 0:
            self._set_number(self._entity_debut_semaine, odometer_km)
            _LOGGER.info(
                "MidnightSnapshotManager %s: km_debut_semaine = %.1f km (lundi)",
                self.tracker_name, odometer_km,
            )

        # Snapshot mensuel — au jour configuré (number.*_jour_stats_mensuelles)
        jour_mensuel = int(self._get_float(self._entity_jour_mensuel, 1.0))
        if now.day == jour_mensuel:
            self._set_number(self._entity_debut_mois, odometer_km)
            _LOGGER.info(
                "MidnightSnapshotManager %s: km_debut_mois = %.1f km (jour %d)",
                self.tracker_name, odometer_km, jour_mensuel,
            )


# ════════════════════════════════════════════════════════════════════════════
# SENSORS — KM PÉRIODIQUES (journalier, hebdomadaire, mensuel)
# ════════════════════════════════════════════════════════════════════════════

class _GeoRideKmPeriodBase(SensorEntity, RestoreEntity):
    """Classe de base pour les sensors km périodiques.

    Calcul : max(odometer - snapshot_debut, 0)

    S'abonne à :
      - sensor.<moto>_odometer  (via référence directe à GeoRideRealOdometerSensor)
      - number.<moto>_km_debut_<periode>  (snapshot de début de période)
    """

    def __init__(
        self,
        entry,
        tracker,
        hass,
        odometer_sensor: "GeoRideRealOdometerSensor",
        unique_id_suffix: str,
        name_suffix: str,
        icon: str,
        snapshot_entity: str,
    ) -> None:
        self._entry = entry
        self._tracker = tracker
        self._hass = hass
        self._odometer_sensor = odometer_sensor
        self._snapshot_entity = snapshot_entity

        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")

        self._attr_unique_id = f"{self.tracker_id}_{unique_id_suffix}"
        self._attr_name = f"{self.tracker_name} {name_suffix}"
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = None
        self._attr_native_value: float = 0.0

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Restaurer la dernière valeur connue
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                try:
                    self._attr_native_value = float(last_state.state)
                except (ValueError, TypeError):
                    pass

        from homeassistant.helpers.event import async_track_state_change_event

        # S'abonner aux changements de l'odometer ET du snapshot
        watched = [self._odometer_sensor.entity_id, self._snapshot_entity]
        self.async_on_remove(
            async_track_state_change_event(
                self._hass, watched, self._handle_state_change,
            )
        )
        self._recalculate()

    @callback
    def _handle_state_change(self, event) -> None:
        self._recalculate()
        self.async_write_ha_state()

    def _get_float(self, entity_id: str, default: float = 0.0) -> float:
        state = self._hass.states.get(entity_id)
        if state and state.state not in (None, "unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return default

    def _recalculate(self) -> None:
        odometer_km = self._odometer_sensor.native_value or 0.0
        snapshot_km = self._get_float(self._snapshot_entity, 0.0)
        km = max(odometer_km - snapshot_km, 0.0)
        self._attr_native_value = round(km, 1)

        _LOGGER.debug(
            "%s: odometer=%.1f km - snapshot=%.1f km = %.1f km",
            self._attr_name, odometer_km, snapshot_km, km,
        )

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "odometer_actuel": self._odometer_sensor.native_value,
            "snapshot_debut": self._get_float(self._snapshot_entity),
            "snapshot_entity": self._snapshot_entity,
        }


class GeoRideKmJournaliersSensor(_GeoRideKmPeriodBase):
    """Sensor km parcourus aujourd'hui (odometer - snapshot minuit)."""

    def __init__(self, entry, tracker, hass, odometer_sensor) -> None:
        slug = tracker.get("trackerName", f"Tracker {tracker.get('trackerId')}").lower().replace(" ", "_")
        super().__init__(
            entry=entry,
            tracker=tracker,
            hass=hass,
            odometer_sensor=odometer_sensor,
            unique_id_suffix="km_journaliers",
            name_suffix="KM Journaliers",
            icon="mdi:counter",
            snapshot_entity=f"number.{slug}_km_debut_journee",
        )


class GeoRideKmHebdomadairesSensor(_GeoRideKmPeriodBase):
    """Sensor km parcourus cette semaine (odometer - snapshot lundi minuit)."""

    def __init__(self, entry, tracker, hass, odometer_sensor) -> None:
        slug = tracker.get("trackerName", f"Tracker {tracker.get('trackerId')}").lower().replace(" ", "_")
        super().__init__(
            entry=entry,
            tracker=tracker,
            hass=hass,
            odometer_sensor=odometer_sensor,
            unique_id_suffix="km_hebdomadaires",
            name_suffix="KM Hebdomadaires",
            icon="mdi:calendar-week",
            snapshot_entity=f"number.{slug}_km_debut_semaine",
        )


class GeoRideKmMensuelsSensor(_GeoRideKmPeriodBase):
    """Sensor km parcourus ce mois (odometer - snapshot 1er du mois)."""

    def __init__(self, entry, tracker, hass, odometer_sensor) -> None:
        slug = tracker.get("trackerName", f"Tracker {tracker.get('trackerId')}").lower().replace(" ", "_")
        super().__init__(
            entry=entry,
            tracker=tracker,
            hass=hass,
            odometer_sensor=odometer_sensor,
            unique_id_suffix="km_mensuels",
            name_suffix="KM Mensuels",
            icon="mdi:calendar-month",
            snapshot_entity=f"number.{slug}_km_debut_mois",
        )


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
    """Sensor for real odometer = lifetime base + intraday delta + offset.

    Stratégie de calcul :
    ─ Base (coordinator lifetime, rafraîchi à minuit) : somme de TOUS les trajets
      depuis l'activation du tracker. Représente le kilométrage stable de la veille.

    ─ Delta intra-journalier (coordinator récent) : trajets dont la startTime est
      postérieure au dernier trajet de la base lifetime. Permet de capter les
      nouveaux trajets de la journée dès leur apparition dans l'API (interval ~ 1h),
      sans attendre le refresh lifetime du lendemain.

    ─ Offset : valeur saisie via number.*_odometer_offset pour aligner sur le
      compteur physique de la moto.

    Odometer = base_km + delta_km + offset_km

    Le sensor s'abonne aux deux coordinateurs : toute mise à jour de l'un
    ou de l'autre déclenche un recalcul.
    """

    def __init__(self, lifetime_coordinator, recent_coordinator, entry, tracker, hass):
        # CoordinatorEntity s'attache au coordinator lifetime (le coordinator "principal")
        super().__init__(lifetime_coordinator)
        self._recent_coordinator = recent_coordinator
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

        # S'abonner aux updates du coordinator récent pour les trajets intra-journaliers
        self.async_on_remove(
            self._recent_coordinator.async_add_listener(
                self._handle_recent_coordinator_update
            )
        )

        # S'abonner aux changements de l'offset
        from homeassistant.helpers.event import async_track_state_change_event
        offset_entity_id = f"number.{self.tracker_name.lower().replace(' ', '_')}_odometer_offset"
        self.async_on_remove(
            async_track_state_change_event(
                self._hass,
                [offset_entity_id],
                self._handle_offset_state_change,
            )
        )

    @callback
    def _handle_recent_coordinator_update(self) -> None:
        """Déclenché à chaque update du coordinator récent (~ toutes les 1h)."""
        self.async_write_ha_state()

    async def _handle_offset_state_change(self, event) -> None:
        self.async_write_ha_state()

    def _compute_tracker_km(self) -> tuple[float, float, str]:
        """Calculer tracker_km (base lifetime + delta intraday) et retourner les détails.

        Returns:
            (base_km, delta_km, last_lifetime_trip_date)
        """
        # ── Base lifetime ──────────────────────────────────────────────────
        lifetime_data = self.coordinator.data  # coordinator lifetime
        lifetime_trips = lifetime_data.get("trips", []) if lifetime_data else []
        base_km = sum(t.get("distance", 0) for t in lifetime_trips) / METERS_TO_KM

        # Date du dernier trajet connu dans la base lifetime (pour filtrer le delta)
        if lifetime_trips:
            last_lifetime_date = max(
                t.get("endTime") or t.get("startTime", "") for t in lifetime_trips
            )
        else:
            last_lifetime_date = ""

        # ── Delta intra-journalier ─────────────────────────────────────────
        recent_trips = self._recent_coordinator.data or []
        if last_lifetime_date:
            new_trips = [
                t for t in recent_trips
                if (t.get("startTime") or "") > last_lifetime_date
            ]
        else:
            new_trips = recent_trips

        delta_km = sum(t.get("distance", 0) for t in new_trips) / METERS_TO_KM

        if new_trips:
            _LOGGER.debug(
                "Odometer %s: base=%.1f km + delta=%.1f km (%d new trips today)",
                self.tracker_name, base_km, delta_km, len(new_trips),
            )

        return base_km, delta_km, last_lifetime_date

    def _get_offset_km(self) -> float:
        offset_entity_id = f"number.{self.tracker_name.lower().replace(' ', '_')}_odometer_offset"
        offset = self._hass.states.get(offset_entity_id)
        return float(offset.state) if offset and offset.state not in ("unknown", "unavailable") else 0

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
        base_km, delta_km, _ = self._compute_tracker_km()
        offset_km = self._get_offset_km()
        return round(base_km + delta_km + offset_km, 2)

    @property
    def extra_state_attributes(self):
        base_km, delta_km, last_lifetime_date = self._compute_tracker_km()
        offset_km = self._get_offset_km()
        offset_entity_id = f"number.{self.tracker_name.lower().replace(' ', '_')}_odometer_offset"

        lifetime_data = self.coordinator.data
        lifetime_trips = lifetime_data.get("trips", []) if lifetime_data else []
        recent_trips = self._recent_coordinator.data or []
        if last_lifetime_date:
            new_trips = [t for t in recent_trips if (t.get("startTime") or "") > last_lifetime_date]
        else:
            new_trips = recent_trips

        total_duration_ms = sum(t.get("duration", 0) for t in lifetime_trips + new_trips)
        total_duration_hours = round(total_duration_ms / MILLISECONDS_TO_HOURS, 2)

        all_trips = lifetime_trips + new_trips
        if all_trips:
            sorted_all = sorted(all_trips, key=lambda x: x.get("startTime", ""))
            first_trip_date = sorted_all[0].get("startTime", "")
            last_trip_date = sorted_all[-1].get("startTime", "")
        else:
            first_trip_date = ""
            last_trip_date = ""

        return {
            "total_trips": len(all_trips),
            "total_duration_hours": total_duration_hours,
            "first_trip_date": first_trip_date,
            "last_trip_date": last_trip_date,
            "base_km": round(base_km, 2),
            "delta_km_today": round(delta_km, 2),
            "tracker_km": round(base_km + delta_km, 2),
            "offset_km": round(offset_km, 2),
            "offset_entity": offset_entity_id,
            "last_lifetime_sync": last_lifetime_date,
        }

    def set_odometer(self, value: float):
        """Set the odometer to a specific value by calculating offset."""
        base_km, delta_km, _ = self._compute_tracker_km()
        tracker_km = base_km + delta_km
        offset_km = value - tracker_km
        offset_entity_id = f"number.{self.tracker_name.lower().replace(' ', '_')}_odometer_offset"
        self._hass.async_create_task(
            self._hass.services.async_call(
                "number", "set_value",
                {"entity_id": offset_entity_id, "value": offset_km},
            )
        )
        _LOGGER.info(
            "Odometer set for %s: %.1f km (base=%.1f km, delta=%.1f km, offset=%.1f km)",
            self.tracker_name, value, base_km, delta_km, offset_km
        )



# ════════════════════════════════════════════════════════════════════════════
# SENSOR — AUTONOMIE RESTANTE (réactif)
# ════════════════════════════════════════════════════════════════════════════

class GeoRideAutonomySensor(SensorEntity, RestoreEntity):
    """Sensor autonomie restante, mis à jour à chaque changement d'odometer.

    Calcul :
      - Si nb_pleins_enregistres >= 2 : utilise autonomie_moyenne_calculee
      - Sinon                         : utilise autonomie_totale (saisie manuelle)

      km_restants = autonomie_ref - (odometer_actuel - km_dernier_plein)
      (plancher à 0)

    S'abonne aux changements d'état de :
      - sensor.<moto>_odometer        (via référence directe à GeoRideRealOdometerSensor)
      - number.<moto>_km_dernier_plein
      - number.<moto>_autonomie_totale
      - number.<moto>_autonomie_moyenne_calculee
      - number.<moto>_nb_pleins_enregistres
    """

    def __init__(self, entry, tracker, hass, odometer_sensor: "GeoRideRealOdometerSensor"):
        self._entry = entry
        self._tracker = tracker
        self._hass = hass
        self._odometer_sensor = odometer_sensor

        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")

        slug = self.tracker_name.lower().replace(" ", "_")
        # Les slugs HA sont dérivés du name complet incluant le préfixe "Carburant - "
        self._entity_km_dernier_plein   = f"number.{slug}_km_au_dernier_plein"
        self._entity_autonomie_totale   = f"number.{slug}_autonomie_totale"
        self._entity_autonomie_moyenne  = f"number.{slug}_carburant_autonomie_moyenne_calculee"
        self._entity_nb_pleins          = f"number.{slug}_carburant_nombre_de_pleins_enregistres"

        self._attr_unique_id = f"{self.tracker_id}_autonomie_restante"
        self._attr_name = f"{self.tracker_name} Autonomie restante"
        self._attr_icon = "mdi:gas-station-outline"
        self._attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value: float = 0.0

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Restauration
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                try:
                    self._attr_native_value = float(last_state.state)
                except (ValueError, TypeError):
                    pass

        from homeassistant.helpers.event import async_track_state_change_event

        watched = [
            self._odometer_sensor.entity_id,
            self._entity_km_dernier_plein,
            self._entity_autonomie_totale,
            self._entity_autonomie_moyenne,
            self._entity_nb_pleins,
        ]

        self.async_on_remove(
            async_track_state_change_event(
                self._hass,
                watched,
                self._handle_state_change,
            )
        )

        # Calcul initial
        self._recalculate()

    @callback
    def _handle_state_change(self, event) -> None:
        self._recalculate()
        self.async_write_ha_state()

    def _get_float(self, entity_id: str, default: float = 0.0) -> float:
        state = self._hass.states.get(entity_id)
        if state and state.state not in (None, "unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return default

    def _recalculate(self) -> None:
        odometer_km       = self._odometer_sensor.native_value or 0.0
        km_dernier_plein  = self._get_float(self._entity_km_dernier_plein)
        autonomie_totale  = self._get_float(self._entity_autonomie_totale, 150.0)
        autonomie_moyenne = self._get_float(self._entity_autonomie_moyenne)
        nb_pleins         = self._get_float(self._entity_nb_pleins)

        # Choisir la référence d'autonomie
        if nb_pleins >= 2 and autonomie_moyenne > 0:
            autonomie_ref = autonomie_moyenne
        else:
            autonomie_ref = autonomie_totale

        km_parcourus = max(odometer_km - km_dernier_plein, 0.0)
        km_restants  = max(autonomie_ref - km_parcourus, 0.0)

        self._attr_native_value = round(km_restants, 1)

        _LOGGER.debug(
            "Autonomie %s: ref=%.1f km, parcourus=%.1f km (depuis %.1f), restants=%.1f km (pleins: %d)",
            self.tracker_name, autonomie_ref, km_parcourus, km_dernier_plein,
            km_restants, int(nb_pleins),
        )

    @property
    def extra_state_attributes(self) -> dict:
        nb_pleins = self._get_float(self._entity_nb_pleins)
        autonomie_moyenne = self._get_float(self._entity_autonomie_moyenne)
        autonomie_totale  = self._get_float(self._entity_autonomie_totale, 150.0)
        return {
            "autonomie_reference": "moyenne_calculee" if nb_pleins >= 2 and autonomie_moyenne > 0 else "theorique",
            "autonomie_theorique_km": autonomie_totale,
            "autonomie_moyenne_km": autonomie_moyenne if autonomie_moyenne > 0 else None,
            "nb_pleins_enregistres": int(nb_pleins),
            "km_dernier_plein": self._get_float(self._entity_km_dernier_plein),
        }


# ════════════════════════════════════════════════════════════════════════════
# SENSORS — ENTRETIENS (km restants + jours restants calculés en Python)
# ════════════════════════════════════════════════════════════════════════════

class _GeoRideEntretienKmBase(SensorEntity, RestoreEntity):
    """Classe de base pour les sensors km restants entretien.

    Calcul commun :
      km_restants = km_dernier_entretien + intervalle_km - odometer_actuel
      (peut être négatif : entretien en retard)

    S'abonne à :
      - sensor.<moto>_odometer  (via référence directe à GeoRideRealOdometerSensor)
      - number.<moto>_<intervalle_key>
      - number.<moto>_<km_dernier_key>
    """

    def __init__(
        self,
        entry,
        tracker,
        hass,
        odometer_sensor: "GeoRideRealOdometerSensor",
        unique_id_suffix: str,
        name_suffix: str,
        icon: str,
        intervalle_entity: str,
        km_dernier_entity: str,
    ) -> None:
        self._entry = entry
        self._tracker = tracker
        self._hass = hass
        self._odometer_sensor = odometer_sensor
        self._entity_intervalle = intervalle_entity
        self._entity_km_dernier = km_dernier_entity

        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")

        self._attr_unique_id = f"{self.tracker_id}_{unique_id_suffix}"
        self._attr_name = f"{self.tracker_name} {name_suffix}"
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = UnitOfLength.KILOMETERS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = None
        self._attr_native_value: float = 0.0

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                try:
                    self._attr_native_value = float(last_state.state)
                except (ValueError, TypeError):
                    pass

        from homeassistant.helpers.event import async_track_state_change_event

        watched = [
            self._odometer_sensor.entity_id,
            self._entity_intervalle,
            self._entity_km_dernier,
        ]
        self.async_on_remove(
            async_track_state_change_event(
                self._hass, watched, self._handle_state_change,
            )
        )
        self._recalculate()

    @callback
    def _handle_state_change(self, event) -> None:
        self._recalculate()
        self.async_write_ha_state()

    def _get_float(self, entity_id: str, default: float = 0.0) -> float:
        state = self._hass.states.get(entity_id)
        if state and state.state not in (None, "unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return default

    def _recalculate(self) -> None:
        odometer_km   = self._odometer_sensor.native_value or 0.0
        intervalle_km = self._get_float(self._entity_intervalle, 0.0)
        km_dernier    = self._get_float(self._entity_km_dernier, 0.0)

        # Si les deux valeurs de référence sont à 0 → pas encore configuré
        if intervalle_km == 0 and km_dernier == 0:
            self._attr_native_value = 0.0
            return

        km_restants = km_dernier + intervalle_km - odometer_km
        self._attr_native_value = round(km_restants, 1)

        _LOGGER.debug(
            "%s: dernier=%.1f km + intervalle=%.1f km - odometer=%.1f km = restants=%.1f km",
            self._attr_name, km_dernier, intervalle_km, odometer_km, km_restants,
        )

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "km_dernier_entretien": self._get_float(self._entity_km_dernier),
            "intervalle_km": self._get_float(self._entity_intervalle),
            "odometer_actuel": self._odometer_sensor.native_value,
        }


class GeoRideKmRestantsChaineSensor(_GeoRideEntretienKmBase):
    """Sensor km restants avant entretien chaîne."""

    def __init__(self, entry, tracker, hass, odometer_sensor) -> None:
        slug = tracker.get("trackerName", f"Tracker {tracker.get('trackerId')}").lower().replace(" ", "_")
        super().__init__(
            entry=entry,
            tracker=tracker,
            hass=hass,
            odometer_sensor=odometer_sensor,
            unique_id_suffix="km_restants_chaine",
            name_suffix="Entretien Chaîne - KM restants",
            icon="mdi:link-variant",
            intervalle_entity=f"number.{slug}_entretien_chaine_intervalle_km",
            km_dernier_entity=f"number.{slug}_entretien_chaine_km_au_dernier_entretien",
        )


class GeoRideKmRestantsVidangeSensor(_GeoRideEntretienKmBase):
    """Sensor km restants avant vidange."""

    def __init__(self, entry, tracker, hass, odometer_sensor) -> None:
        slug = tracker.get("trackerName", f"Tracker {tracker.get('trackerId')}").lower().replace(" ", "_")
        super().__init__(
            entry=entry,
            tracker=tracker,
            hass=hass,
            odometer_sensor=odometer_sensor,
            unique_id_suffix="km_restants_vidange",
            name_suffix="Entretien Vidange - KM restants",
            icon="mdi:oil",
            intervalle_entity=f"number.{slug}_vidange_intervalle_km",
            km_dernier_entity=f"number.{slug}_vidange_km_a_la_derniere_vidange",
        )


class GeoRideKmRestantsRevisionSensor(_GeoRideEntretienKmBase):
    """Sensor km restants avant révision."""

    def __init__(self, entry, tracker, hass, odometer_sensor) -> None:
        slug = tracker.get("trackerName", f"Tracker {tracker.get('trackerId')}").lower().replace(" ", "_")
        super().__init__(
            entry=entry,
            tracker=tracker,
            hass=hass,
            odometer_sensor=odometer_sensor,
            unique_id_suffix="km_restants_revision",
            name_suffix="Entretien Révision - KM restants",
            icon="mdi:wrench",
            intervalle_entity=f"number.{slug}_revision_intervalle_km",
            km_dernier_entity=f"number.{slug}_revision_km_a_la_derniere_revision",
        )


class GeoRideJoursRestantsRevisionSensor(SensorEntity, RestoreEntity):
    """Sensor jours restants avant révision (basé sur date dernier entretien + intervalle jours).

    Calcul :
      jours_restants = (date_dernier_entretien + intervalle_jours) - aujourd'hui
      (peut être négatif : révision en retard)

    S'abonne à :
      - datetime.<moto>_entretien_revision_date_derniere_revision
      - number.<moto>_entretien_revision_intervalle_jours
    """

    def __init__(self, entry, tracker, hass) -> None:
        self._entry = entry
        self._tracker = tracker
        self._hass = hass

        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")

        slug = self.tracker_name.lower().replace(" ", "_")
        self._entity_date_dernier  = f"datetime.{slug}_revision_date_derniere_revision"
        self._entity_intervalle_j  = f"number.{slug}_revision_intervalle_jours"

        self._attr_unique_id = f"{self.tracker_id}_jours_restants_revision"
        self._attr_name = f"{self.tracker_name} Entretien Révision - Jours restants"
        self._attr_icon = "mdi:calendar-clock"
        self._attr_native_unit_of_measurement = "d"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = None
        self._attr_native_value: float = 0.0

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                try:
                    self._attr_native_value = float(last_state.state)
                except (ValueError, TypeError):
                    pass

        from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change

        watched = [self._entity_date_dernier, self._entity_intervalle_j]
        self.async_on_remove(
            async_track_state_change_event(
                self._hass, watched, self._handle_state_change,
            )
        )
        # Recalcul quotidien à minuit (le nombre de jours change chaque jour même sans action)
        self.async_on_remove(
            async_track_time_change(
                self._hass, self._handle_midnight,
                hour=0, minute=0, second=0,
            )
        )
        self._recalculate()

    @callback
    def _handle_state_change(self, event) -> None:
        self._recalculate()
        self.async_write_ha_state()

    @callback
    def _handle_midnight(self, now) -> None:
        self._recalculate()
        self.async_write_ha_state()

    def _get_float(self, entity_id: str, default: float = 0.0) -> float:
        state = self._hass.states.get(entity_id)
        if state and state.state not in (None, "unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return default

    def _recalculate(self) -> None:
        intervalle_j = self._get_float(self._entity_intervalle_j, 0.0)

        # Lire la date du dernier entretien depuis l'entité datetime
        dt_state = self._hass.states.get(self._entity_date_dernier)
        if dt_state is None or dt_state.state in (None, "unknown", "unavailable"):
            self._attr_native_value = 0.0
            return

        if intervalle_j == 0:
            self._attr_native_value = 0.0
            return

        try:
            date_dernier = datetime.fromisoformat(dt_state.state)
            if date_dernier.tzinfo is None:
                from datetime import timezone as tz
                date_dernier = date_dernier.replace(tzinfo=tz.utc)
        except (ValueError, TypeError):
            self._attr_native_value = 0.0
            return

        from datetime import timezone as tz
        now = datetime.now(tz.utc)
        echeance = date_dernier + timedelta(days=intervalle_j)
        jours_restants = (echeance - now).days

        self._attr_native_value = float(jours_restants)

        _LOGGER.debug(
            "%s: dernier=%s + %d jours → échéance=%s → restants=%d j",
            self._attr_name,
            date_dernier.date(), int(intervalle_j),
            echeance.date(), jours_restants,
        )

    @property
    def extra_state_attributes(self) -> dict:
        intervalle_j = self._get_float(self._entity_intervalle_j)
        dt_state = self._hass.states.get(self._entity_date_dernier)
        date_str = dt_state.state if dt_state else None

        echeance_str = None
        if date_str and intervalle_j > 0:
            try:
                date_dernier = datetime.fromisoformat(date_str)
                echeance = date_dernier + timedelta(days=int(intervalle_j))
                echeance_str = echeance.date().isoformat()
            except (ValueError, TypeError):
                pass

        return {
            "date_dernier_entretien": date_str,
            "intervalle_jours": int(intervalle_j),
            "date_echeance": echeance_str,
        }


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
        self._attr_entity_category = None
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
        # GeoRide envoie le type dans 'name' (ex: "sonorAlarmOn"),
        # fallback sur 'alarmType' ou 'type' pour compatibilité.
        alarm_type = data.get("name") or data.get("alarmType") or data.get("type")
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