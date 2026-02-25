"""GeoRide Trips binary_sensor entities.

Entités créées par tracker :

── Alimentées par Socket.IO (temps réel) ─────────────────────────
  - moving   : True si la moto est en mouvement
  - stolen   : True si l'alarme vol est active
  - crashed  : True si une chute est détectée

── Alimentées par GeoRideTrackerStatusCoordinator (polling 5 min) ──
  - online   : True si le tracker est en ligne (status == "online")
  - locked   : True si le tracker est verrouillé (isLocked)
"""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


SOCKET_BINARY_SENSOR_DESCRIPTIONS = [
    {
        "key": "moving",
        "name": "En mouvement",
        "device_class": BinarySensorDeviceClass.MOTION,
        "icon_on": "mdi:motorbike",
        "icon_off": "mdi:motorbike-off",
        "socket_events": ["position", "device"],
        "payload_key": "moving",
    },
    {
        "key": "stolen",
        "name": "Alarme vol",
        "device_class": BinarySensorDeviceClass.TAMPER,
        "icon_on": "mdi:shield-alert",
        "icon_off": "mdi:shield-check",
        "socket_events": ["device"],
        "payload_key": "stolen",
    },
    {
        "key": "crashed",
        "name": "Chute détectée",
        "device_class": BinarySensorDeviceClass.PROBLEM,
        "icon_on": "mdi:alert-circle",
        "icon_off": "mdi:check-circle",
        "socket_events": ["device"],
        "payload_key": "crashed",
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Créer les binary_sensors pour chaque tracker."""
    data = hass.data[DOMAIN][entry.entry_id]
    trackers = data["trackers"]
    tracker_status_coordinators = data["tracker_status_coordinators"]

    entities = []
    for tracker in trackers:
        tracker_id = str(tracker.get("trackerId"))
        status_coordinator = tracker_status_coordinators[tracker_id]

        # Sensors Socket.IO
        for desc in SOCKET_BINARY_SENSOR_DESCRIPTIONS:
            # Le sensor "moving" reçoit en plus le status_coordinator comme filet de sécurité :
            # si Socket.IO s'arrête sans envoyer de moving=False final, le polling 5 min
            # remet le capteur à OFF dès que le coordinator confirme l'arrêt.
            coordinator_fallback = status_coordinator if desc["key"] == "moving" else None
            entities.append(
                GeoRideBinarySensor(entry, tracker, desc, coordinator_fallback)
            )

        # Sensors polling (status coordinator)
        entities.append(GeoRideOnlineBinarySensor(status_coordinator, entry, tracker))
        entities.append(GeoRideLockedBinarySensor(status_coordinator, entry, tracker))

        # Binary sensors calculés : indicateurs d'alerte entretien/carburant
        entities.extend([
            GeoRidePleinRequisBinarySensor(entry, tracker, hass),
            GeoRideChaineRequiseBinarySensor(entry, tracker, hass),
            GeoRideVidangeRequiseBinarySensor(entry, tracker, hass),
            GeoRideRevisionRequiseBinarySensor(entry, tracker, hass),
        ])

    async_add_entities(entities)
    _LOGGER.info(
        "Added %d binary_sensor entities for %d trackers",
        len(entities),
        len(trackers),
    )


# ════════════════════════════════════════════════════════════════════════════
# BINARY SENSORS SOCKET.IO
# ════════════════════════════════════════════════════════════════════════════

class GeoRideBinarySensor(BinarySensorEntity, RestoreEntity):
    """Binary sensor GeoRide alimenté par Socket.IO.

    Accepte un coordinator_fallback optionnel (GeoRideTrackerStatusCoordinator) :
    à chaque polling du coordinator, si le champ correspondant (ex: moving) vaut False
    alors que le sensor est ON, le sensor est forcé à OFF.
    Cela couvre le cas où Socket.IO ne livre pas le dernier événement moving=False
    (micro-coupure réseau, reconnexion tardive, événements hors-ordre).
    """

    def __init__(
        self,
        entry: ConfigEntry,
        tracker: dict,
        desc: dict,
        coordinator_fallback=None,
    ) -> None:
        self._entry = entry
        self._tracker = tracker
        self._desc = desc
        self._socket_manager = None
        self._coordinator_fallback = coordinator_fallback

        self._tracker_id = str(tracker.get("trackerId"))
        self._tracker_name = tracker.get("trackerName", f"Tracker {self._tracker_id}")

        self._attr_unique_id = f"{self._tracker_id}_{desc['key']}"
        self._attr_name = f"{self._tracker_name} {desc['name']}"
        self._attr_device_class = desc["device_class"]
        self._attr_is_on = False

        self._unregister_callbacks: list = []
        self._unregister_coordinator: callable | None = None

    @property
    def icon(self) -> str:
        return self._desc["icon_on"] if self._attr_is_on else self._desc["icon_off"]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._tracker_id)},
            name=f"{self._tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    async def async_added_to_hass(self) -> None:
        """Restaurer l'état et s'abonner aux events Socket.IO."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                self._attr_is_on = last_state.state == "on"

        # Récupérer le socket_manager depuis hass.data (disponible ici, après setup complet)
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        self._socket_manager = entry_data.get("socket_manager")

        if self._socket_manager:
            for event_name in self._desc["socket_events"]:
                unregister = self._socket_manager.register_callback(
                    self._tracker_id,
                    event_name,
                    self._handle_socket_event,
                )
                self._unregister_callbacks.append(unregister)

        # Abonnement au coordinator de statut comme filet de sécurité
        if self._coordinator_fallback is not None:
            self._unregister_coordinator = self._coordinator_fallback.async_add_listener(
                self._handle_coordinator_update
            )

    async def async_will_remove_from_hass(self) -> None:
        """Se désenregistrer des callbacks Socket.IO et du coordinator."""
        for unregister in self._unregister_callbacks:
            unregister()
        self._unregister_callbacks.clear()

        if self._unregister_coordinator:
            self._unregister_coordinator()
            self._unregister_coordinator = None

    def _handle_coordinator_update(self) -> None:
        """Filet de sécurité : synchroniser l'état depuis le StatusCoordinator.

        Appelé à chaque polling du coordinator (toutes les 5 min).
        Si le coordinator confirme moving=False et que le sensor est encore ON,
        on le remet à OFF pour corriger un état bloqué (ex: dernier événement
        Socket.IO était moving=True avant déconnexion réseau).
        """
        payload_key = self._desc["payload_key"]
        data = self._coordinator_fallback.data
        if not data:
            return

        coordinator_state = data.get(payload_key)
        if coordinator_state is None:
            return

        new_state = bool(coordinator_state)

        # N'agir que si le coordinator dit OFF et que le sensor est bloqué ON
        # (évite d'écraser un vrai mouvement en cours confirmé par Socket.IO)
        if not new_state and self._attr_is_on:
            self._attr_is_on = False
            self.async_write_ha_state()
            _LOGGER.debug(
                "%s → OFF (fallback coordinator, Socket.IO n'avait pas livré l'état final)",
                self._attr_name,
            )

    async def _handle_socket_event(self, data: dict) -> None:
        """Traiter un événement Socket.IO et mettre à jour l'état."""
        payload_key = self._desc["payload_key"]
        if payload_key not in data:
            _LOGGER.debug(
                "%s: payload_key '%s' absent dans l'événement: %s",
                self._attr_name, payload_key, data,
            )
            return
        new_state = bool(data[payload_key])
        self._attr_is_on = new_state
        self.async_write_ha_state()
        _LOGGER.debug(
            "%s → %s (from Socket.IO event)",
            self._attr_name,
            "ON" if new_state else "OFF",
        )


# ════════════════════════════════════════════════════════════════════════════
# BINARY SENSORS POLLING (GeoRideTrackerStatusCoordinator)
# ════════════════════════════════════════════════════════════════════════════

class GeoRideOnlineBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor : tracker en ligne (status == 'online'), mis à jour toutes les 5 min."""

    def __init__(self, coordinator, entry: ConfigEntry, tracker: dict) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._tracker = tracker
        self._tracker_id = str(tracker.get("trackerId"))
        self._tracker_name = tracker.get("trackerName", f"Tracker {self._tracker_id}")

        self._attr_unique_id = f"{self._tracker_id}_online"
        self._attr_name = f"{self._tracker_name} En ligne"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

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
    def is_on(self) -> bool:
        data = self.coordinator.data
        if not data:
            return False
        return data.get("status") == "online"

    @property
    def icon(self) -> str:
        return "mdi:signal" if self.is_on else "mdi:signal-off"


class GeoRideLockedBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor : tracker verrouillé (isLocked), mis à jour toutes les 5 min."""

    def __init__(self, coordinator, entry: ConfigEntry, tracker: dict) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._tracker = tracker
        self._tracker_id = str(tracker.get("trackerId"))
        self._tracker_name = tracker.get("trackerName", f"Tracker {self._tracker_id}")

        self._attr_unique_id = f"{self._tracker_id}_locked"
        self._attr_name = f"{self._tracker_name} Verrouillé"
        self._attr_device_class = BinarySensorDeviceClass.LOCK
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
    def is_on(self) -> bool:
        # BinarySensorDeviceClass.LOCK : is_on=True = déverrouillé, is_on=False = verrouillé
        data = self.coordinator.data
        if not data:
            return False
        return not bool(data.get("isLocked", False))

    @property
    def icon(self) -> str:
        return "mdi:lock-open" if self.is_on else "mdi:lock"


# ════════════════════════════════════════════════════════════════════════════
# BINARY SENSORS CALCULÉS — ALERTES ENTRETIEN / CARBURANT
# ════════════════════════════════════════════════════════════════════════════

class _GeoRideAlerteBinarySensorBase(BinarySensorEntity):
    """Base pour les binary sensors d'alerte entretien/carburant.

    Calcule son état en temps réel à partir des sensors/numbers de l'intégration.
    Passe OFF→ON quand le seuil est franchi, ON→OFF quand les données redeviennent OK
    (après confirmation d'entretien/plein). Aucune logique d'anti-doublon nécessaire :
    le blueprint utilise un trigger from='off' to='on' pour déclencher la notification.
    """

    def __init__(self, entry: ConfigEntry, tracker: dict, hass: HomeAssistant) -> None:
        self._entry = entry
        self._tracker = tracker
        self._hass = hass
        self._attr_is_on = False

        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._slug = self.tracker_name.lower().replace(" ", "_")

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    def _get_float(self, entity_id: str, default: float = 0.0) -> float:
        state = self._hass.states.get(entity_id)
        if state and state.state not in (None, "unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return default

    def _watched_entities(self) -> list[str]:
        """Retourner la liste des entités à surveiller pour recalcul."""
        raise NotImplementedError

    def _compute_is_on(self) -> bool:
        """Calculer si l'alerte doit être active."""
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self._hass,
                self._watched_entities(),
                self._handle_state_change,
            )
        )
        self._recalculate()

    @callback
    def _handle_state_change(self, event) -> None:
        self._recalculate()
        self.async_write_ha_state()

    def _recalculate(self) -> None:
        self._attr_is_on = self._compute_is_on()


class GeoRidePleinRequisBinarySensor(_GeoRideAlerteBinarySensorBase):
    """Binary sensor : plein requis (autonomie_restante ≤ seuil_alerte_autonomie).

    `binary_sensor.<moto>_plein_requis`
    Remplace switch.<moto>_faire_le_plein.
    """

    def __init__(self, entry, tracker, hass) -> None:
        super().__init__(entry, tracker, hass)
        self._entity_autonomie = f"sensor.{self._slug}_autonomie_restante"
        self._entity_seuil = f"number.{self._slug}_carburant_seuil_alerte_autonomie"
        self._attr_unique_id = f"{self.tracker_id}_plein_requis"
        self._attr_name = f"{self.tracker_name} Plein requis"
        self._attr_icon = "mdi:gas-station-alert"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    def _watched_entities(self) -> list[str]:
        return [self._entity_autonomie, self._entity_seuil]

    def _compute_is_on(self) -> bool:
        autonomie = self._get_float(self._entity_autonomie, -1.0)
        seuil = self._get_float(self._entity_seuil, 30.0)
        if autonomie < 0:
            return False
        return autonomie <= seuil


class GeoRideChaineRequiseBinarySensor(_GeoRideAlerteBinarySensorBase):
    """Binary sensor : entretien chaîne requis (km_restants_chaine ≤ seuil_alerte_chaine).

    `binary_sensor.<moto>_chaine_requise`
    Remplace switch.<moto>_entretien_chaine_a_faire.
    """

    def __init__(self, entry, tracker, hass) -> None:
        super().__init__(entry, tracker, hass)
        self._entity_km_restants = f"sensor.{self._slug}_entretien_chaine_km_restants"
        self._entity_seuil = f"number.{self._slug}_entretien_chaine_seuil_alerte"
        self._attr_unique_id = f"{self.tracker_id}_chaine_requise"
        self._attr_name = f"{self.tracker_name} Entretien Chaîne - Requis"
        self._attr_icon = "mdi:link-variant-plus"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    def _watched_entities(self) -> list[str]:
        return [self._entity_km_restants, self._entity_seuil]

    def _compute_is_on(self) -> bool:
        km_restants = self._get_float(self._entity_km_restants, 9999.0)
        seuil = self._get_float(self._entity_seuil, 100.0)
        if km_restants == 9999.0:  # entité non disponible
            return False
        return km_restants <= seuil


class GeoRideVidangeRequiseBinarySensor(_GeoRideAlerteBinarySensorBase):
    """Binary sensor : vidange requise (km_restants_vidange ≤ seuil_alerte_vidange).

    `binary_sensor.<moto>_vidange_requise`
    Remplace switch.<moto>_vidange_a_faire.
    """

    def __init__(self, entry, tracker, hass) -> None:
        super().__init__(entry, tracker, hass)
        self._entity_km_restants = f"sensor.{self._slug}_entretien_vidange_km_restants"
        self._entity_seuil = f"number.{self._slug}_entretien_vidange_seuil_alerte"
        self._attr_unique_id = f"{self.tracker_id}_vidange_requise"
        self._attr_name = f"{self.tracker_name} Entretien Vidange - Requise"
        self._attr_icon = "mdi:oil-level"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    def _watched_entities(self) -> list[str]:
        return [self._entity_km_restants, self._entity_seuil]

    def _compute_is_on(self) -> bool:
        km_restants = self._get_float(self._entity_km_restants, 9999.0)
        seuil = self._get_float(self._entity_seuil, 500.0)
        if km_restants == 9999.0:
            return False
        return km_restants <= seuil


class GeoRideRevisionRequiseBinarySensor(_GeoRideAlerteBinarySensorBase):
    """Binary sensor : révision requise (km OU jours ≤ seuil).

    `binary_sensor.<moto>_revision_requise`
    Remplace switch.<moto>_revision_a_faire.
    Double critère : km_restants ≤ seuil_km OU jours_restants ≤ 30.
    """

    def __init__(self, entry, tracker, hass) -> None:
        super().__init__(entry, tracker, hass)
        self._entity_km_restants = f"sensor.{self._slug}_entretien_revision_km_restants"
        self._entity_jours_restants = f"sensor.{self._slug}_jours_restants_revision"
        self._entity_seuil_km = f"number.{self._slug}_entretien_revision_seuil_alerte"
        self._attr_unique_id = f"{self.tracker_id}_revision_requise"
        self._attr_name = f"{self.tracker_name} Entretien Révision - Requise"
        self._attr_icon = "mdi:wrench-clock"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    def _watched_entities(self) -> list[str]:
        return [self._entity_km_restants, self._entity_jours_restants, self._entity_seuil_km]

    def _compute_is_on(self) -> bool:
        km_restants = self._get_float(self._entity_km_restants, 9999.0)
        jours_restants = self._get_float(self._entity_jours_restants, 9999.0)
        seuil_km = self._get_float(self._entity_seuil_km, 500.0)
        if km_restants == 9999.0 and jours_restants == 9999.0:
            return False
        alerte_km = km_restants <= seuil_km
        alerte_jours = jours_restants <= 30
        return alerte_km or alerte_jours