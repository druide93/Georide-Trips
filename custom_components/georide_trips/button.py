"""GeoRide Trips buttons - Refresh buttons and maintenance record buttons."""
import asyncio
import logging
from datetime import datetime, timezone

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
    api = data["api"]

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
            GeoRideConfirmerPleinButton(
                hass, entry, tracker,
                api=api,
                coordinator=coordinators[tracker_id],
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

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

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

        # Désactivation du switch entretien correspondant
        prefix = self.tracker_name.lower().replace(" ", "_")
        switch_entity = f"switch.{prefix}_entretien_{self._maintenance_type}_a_faire"
        switch_state = self._hass.states.get(switch_entity)
        if switch_state and switch_state.state == "on":
            await self._hass.services.async_call(
                "switch", "turn_off",
                {"entity_id": switch_entity},
                blocking=True,
            )
            _LOGGER.info(
                "Turned off maintenance switch '%s' for %s",
                switch_entity, self.tracker_name,
            )

        _LOGGER.info(
            "Recorded %s for %s: %.1f km on %s",
            self._maintenance_type, self.tracker_name, odometer_km, now_str,
        )


class GeoRideConfirmerPleinButton(ButtonEntity):
    """Bouton pour confirmer un plein — calcul odometer précis en 2 étapes.

    Étape 1 (async_press) — immédiate :
        • Stocker plein_pending_at = now() (datetime)
        • Stocker plein_pending_odometer = odometer actuel (km au début du trajet en cours)
        • Éteindre le switch "Faire le plein"
        • S'abonner au prochain nouveau trajet détecté (on_new_trip) du coordinator

    Étape 2 (_on_new_trip_for_plein) — déclenchée à la détection du nouveau trajet :
        • Lire startTime du dernier trajet dans coordinator.data (= trajet du plein)
        • Appel API get_trips(startTime → plein_pending_at) → distance entre départ et plein
        • odometer_au_plein = plein_pending_odometer + distance_api
        • Calcul distance inter-plein
        • Rotation FIFO historique (hist_3 ← hist_2 ← hist_1 ← nouveau)
        • Recalcul moyenne glissante (max 3 pleins)
        • Mise à jour km_dernier_plein + nb_pleins_enregistres
        • Reset plein_pending_at = None (sentinel epoch 1970)

    Fallback : si aucun nouveau trajet n'est détecté dans FALLBACK_TIMEOUT secondes,
        utiliser plein_pending_odometer directement (distance_api = 0).
    """

    HIST_SLOTS = 3
    FALLBACK_TIMEOUT = 30 * 60  # 30 min

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tracker: dict,
        api,
        coordinator,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._tracker = tracker
        self._api = api
        self._coordinator = coordinator

        self.tracker_id = str(tracker.get("trackerId"))
        self.tracker_name = tracker.get("trackerName", f"Tracker {self.tracker_id}")
        self._prefix = self.tracker_name.lower().replace(" ", "_")

        self._attr_name = f"{self.tracker_name} Confirmer le plein"
        self._attr_unique_id = f"{self.tracker_id}_confirmer_plein"
        self._attr_icon = "mdi:gas-station-outline"

        # Gestion de l'abonnement au new_trip et du timer fallback
        self._unregister_new_trip_cb: callable | None = None
        self._fallback_timer: asyncio.TimerHandle | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.tracker_id)},
            name=f"{self.tracker_name} Trips",
            manufacturer="GeoRide",
            model=self._tracker.get("model", "GeoRide Tracker"),
            sw_version=str(self._tracker.get("softwareVersion", "")),
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_float(self, entity_id: str, default: float = 0.0) -> float:
        state = self._hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return default
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return default

    def _number_entity_id(self, key: str) -> str | None:
        """Résoudre l'entity_id d'un number à partir de sa clé via l'entity registry."""
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(self._hass)
        unique_id = f"{self.tracker_id}_{key}"
        return registry.async_get_entity_id("number", DOMAIN, unique_id)

    def _datetime_entity_id(self, key: str) -> str | None:
        """Résoudre l'entity_id d'un datetime à partir de sa clé via l'entity registry."""
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(self._hass)
        unique_id = f"{self.tracker_id}_{key}"
        return registry.async_get_entity_id("datetime", DOMAIN, unique_id)

    def _get_number(self, key: str, default: float = 0.0) -> float:
        """Lire la valeur d'un number par sa clé (via entity registry)."""
        entity_id = self._number_entity_id(key)
        if entity_id is None:
            _LOGGER.warning("%s: entity_id introuvable pour la clé number '%s'", self.tracker_name, key)
            return default
        return self._get_float(entity_id, default)

    def _get_datetime(self, key: str) -> datetime | None:
        """Lire la valeur d'un datetime par sa clé. Retourne None si absent ou sentinel 1970."""
        entity_id = self._datetime_entity_id(key)
        if entity_id is None:
            _LOGGER.warning("%s: entity_id introuvable pour la clé datetime '%s'", self.tracker_name, key)
            return None
        state = self._hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            dt = datetime.fromisoformat(state.state.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            # Sentinel : epoch 1970 = pas de plein en attente
            if dt.year == 1970:
                return None
            return dt
        except (ValueError, AttributeError):
            return None

    async def _set_number(self, key: str, value: float) -> None:
        entity_id = self._number_entity_id(key)
        if entity_id is None:
            _LOGGER.error(
                "%s: entity_id introuvable pour la clé number '%s' (unique_id=%s_%s)",
                self.tracker_name, key, self.tracker_id, key,
            )
            return
        await self._hass.services.async_call(
            "number", "set_value",
            {"entity_id": entity_id, "value": value},
            blocking=True,
        )

    async def _set_datetime(self, key: str, value: datetime | None) -> None:
        """Écrire un datetime par sa clé. None → sentinel epoch 1970."""
        entity_id = self._datetime_entity_id(key)
        if entity_id is None:
            _LOGGER.error(
                "%s: entity_id introuvable pour la clé datetime '%s' (unique_id=%s_%s)",
                self.tracker_name, key, self.tracker_id, key,
            )
            return
        if value is None:
            value = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        elif value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        await self._hass.services.async_call(
            "datetime", "set_value",
            {"entity_id": entity_id, "datetime": value.strftime("%Y-%m-%d %H:%M:%S")},
            blocking=True,
        )

    async def _turn_off_switch(self, entity_id: str) -> None:
        state = self._hass.states.get(entity_id)
        if state and state.state == "on":
            await self._hass.services.async_call(
                "switch", "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )

    def _cancel_pending(self) -> None:
        """Annuler l'abonnement new_trip et le timer fallback en cours."""
        if self._unregister_new_trip_cb:
            self._unregister_new_trip_cb()
            self._unregister_new_trip_cb = None
        if self._fallback_timer:
            self._fallback_timer.cancel()
            self._fallback_timer = None

    # ── Étape 1 : press immédiat ──────────────────────────────────────────────

    async def async_press(self) -> None:
        """Étape 1 — Snapshot odometer + attendre la détection du prochain trajet."""
        p = self._prefix

        # Si un plein est déjà en attente, l'annuler proprement
        if self._unregister_new_trip_cb or self._fallback_timer:
            _LOGGER.warning(
                "%s: nouveau press plein alors qu'un plein était déjà en attente — annulation",
                self.tracker_name,
            )
            self._cancel_pending()

        # Snapshot : horodatage du plein + odometer avant le trajet en cours
        now = datetime.now(timezone.utc)
        odometer_actuel = self._get_float(f"sensor.{p}_odometer")

        await self._set_datetime("plein_pending_at", now)
        await self._set_number("plein_pending_odometer", odometer_actuel)
        await self._turn_off_switch(f"switch.{p}_faire_le_plein")

        _LOGGER.info(
            "%s: plein enregistré à %s (odometer départ=%.1f km) — "
            "attente prochain trajet pour calcul précis",
            self.tracker_name, now.strftime("%H:%M:%S"), odometer_actuel,
        )

        # S'abonner au prochain nouveau trajet détecté
        self._unregister_new_trip_cb = self._coordinator.on_new_trip(
            self._on_new_trip_for_plein
        )

        # Timer fallback : si aucun trajet dans FALLBACK_TIMEOUT → utiliser odometer actuel
        self._fallback_timer = self._hass.loop.call_later(
            self.FALLBACK_TIMEOUT,
            lambda: self._hass.async_create_task(self._apply_fallback()),
        )

    # ── Étape 2 : nouveau trajet détecté ─────────────────────────────────────

    def _on_new_trip_for_plein(self) -> None:
        """Callback appelé par le coordinator lors de la détection d'un nouveau trajet."""
        # Annuler le fallback timer puisque le trajet est arrivé à temps
        if self._fallback_timer:
            self._fallback_timer.cancel()
            self._fallback_timer = None
        # Désenregistrer explicitement pour ne pas être rappelé aux prochains trajets
        if self._unregister_new_trip_cb:
            self._unregister_new_trip_cb()
            self._unregister_new_trip_cb = None

        self._hass.async_create_task(self._compute_and_record_plein(use_fallback=False))

    async def _apply_fallback(self) -> None:
        """Appelé si aucun nouveau trajet dans FALLBACK_TIMEOUT — utiliser odometer actuel."""
        self._cancel_pending()
        _LOGGER.warning(
            "%s: timeout fallback plein (%ds) — utilisation odometer au départ",
            self.tracker_name, self.FALLBACK_TIMEOUT,
        )
        await self._compute_and_record_plein(use_fallback=True)

    # ── Calcul commun (nouveau trajet ou fallback) ────────────────────────────

    async def _compute_and_record_plein(self, use_fallback: bool) -> None:
        """Calculer l'odometer au plein et enregistrer toutes les métriques.

        Logique :
        - plein_pending_odometer  = odometer avant le trajet en cours (trajets terminés)
        - plein_pending_trip_start = début du trajet en cours (epoch UTC)
        - plein_pending_at         = horodatage du plein (datetime UTC)
        - API get_trips(trip_start → plein_timestamp) → distance entre départ et plein
        - odometer_au_plein = plein_pending_odometer + distance_api

        Fallback : si API échoue ou aucun trajet détecté → odometer_au_plein = plein_pending_odometer
        """
        from .const import METERS_TO_KM

        plein_dt = self._get_datetime("plein_pending_at")
        odometer_depart = self._get_number("plein_pending_odometer")
        km_dernier_plein = self._get_number("km_dernier_plein")

        if plein_dt is None:
            _LOGGER.warning(
                "%s: _compute_and_record_plein appelé sans plein_pending_at valide",
                self.tracker_name,
            )
            return

        plein_ts = plein_dt.timestamp()

        # ── Calculer la distance parcourue entre début trajet et moment du plein ──
        # Le dernier trajet dans coordinator.data est forcément le trajet du plein
        trip_start_ts = 0.0
        if not use_fallback:
            trips = self._coordinator.data or []
            if trips:
                start_str = trips[0].get("startTime", "")
                if start_str:
                    try:
                        start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        trip_start_ts = start_dt.timestamp()
                    except (ValueError, AttributeError):
                        _LOGGER.warning(
                            "%s: impossible de parser startTime '%s'",
                            self.tracker_name, start_str,
                        )

        if use_fallback or trip_start_ts == 0:
            distance_trajet_km = 0.0
            _LOGGER.warning(
                "%s: %s — distance=0",
                self.tracker_name,
                "fallback plein (pas de trajet détecté)" if use_fallback else "startTime introuvable",
            )
        else:
            distance_trajet_km = await self._fetch_trip_distance(trip_start_ts, plein_ts, METERS_TO_KM)

        odometer_au_plein = round(odometer_depart + distance_trajet_km, 2)
        _LOGGER.info(
            "%s: odometer plein = %.1f km (départ=%.1f + trajet_api=%.1f km, fallback=%s)",
            self.tracker_name, odometer_au_plein, odometer_depart, distance_trajet_km, use_fallback,
        )

        if odometer_au_plein <= 0:
            _LOGGER.error("%s: odometer au plein invalide (%.1f), abandon", self.tracker_name, odometer_au_plein)
            await self._set_datetime("plein_pending_at", None)
            return

        # ── Premier plein : juste snapshot, pas de calcul inter-plein ─────
        if km_dernier_plein == 0:
            _LOGGER.info(
                "%s: premier plein — snapshot odometer = %.1f km",
                self.tracker_name, odometer_au_plein,
            )
            await self._set_number("km_dernier_plein", odometer_au_plein)
            await self._set_number("nb_pleins_enregistres", 1)
            await self._set_datetime("plein_pending_at", None)
            return

        # ── Calcul distance inter-plein ────────────────────────────────────
        distance_inter_plein = round(odometer_au_plein - km_dernier_plein, 1)
        if distance_inter_plein <= 0:
            _LOGGER.warning(
                "%s: distance inter-plein négative (%.1f km), abandon",
                self.tracker_name, distance_inter_plein,
            )
            await self._set_datetime("plein_pending_at", None)
            return

        # ── Rotation FIFO historique ────────────────────────────────────────
        hist_1 = self._get_number("km_plein_hist_1")
        hist_2 = self._get_number("km_plein_hist_2")

        await self._set_number("km_plein_hist_3", hist_2)
        await self._set_number("km_plein_hist_2", hist_1)
        await self._set_number("km_plein_hist_1", distance_inter_plein)

        # ── Moyenne glissante (slots non-nuls, max HIST_SLOTS) ─────────────
        slots = [s for s in [distance_inter_plein, hist_1, hist_2] if s > 0]
        slots = slots[:self.HIST_SLOTS]
        moyenne = round(sum(slots) / len(slots), 1)

        nb_pleins = int(self._get_number("nb_pleins_enregistres")) + 1

        await self._set_number("autonomie_moyenne_calculee", moyenne)
        await self._set_number("nb_pleins_enregistres", nb_pleins)
        await self._set_number("km_dernier_plein", odometer_au_plein)
        await self._set_datetime("plein_pending_at", None)

        _LOGGER.info(
            "%s: plein confirmé — odometer=%.1f km, inter-plein=%.1f km, "
            "moyenne=%.1f km (%d valeur(s)), nb_pleins=%d",
            self.tracker_name, odometer_au_plein, distance_inter_plein,
            moyenne, len(slots), nb_pleins,
        )

    async def _fetch_trip_distance(
        self, trip_start_ts: float, plein_ts: float, meters_to_km: float
    ) -> float:
        """Appeler l'API get_trips entre trip_start et plein_ts pour obtenir la distance parcourue.

        Returns:
            Distance en km entre les deux timestamps, ou 0.0 si l'API échoue.
        """
        try:
            from_date = datetime.fromtimestamp(trip_start_ts, tz=timezone.utc)
            to_date = datetime.fromtimestamp(plein_ts, tz=timezone.utc)

            _LOGGER.debug(
                "%s: fetch trips pour distance plein : %s → %s",
                self.tracker_name,
                from_date.isoformat(),
                to_date.isoformat(),
            )

            trips = await self._api.get_trips(
                self.tracker_id,
                from_date=from_date,
                to_date=to_date,
            )

            if trips is None:
                _LOGGER.warning("%s: API get_trips a retourné None", self.tracker_name)
                return 0.0

            distance_km = round(sum(t.get("distance", 0) for t in trips) / meters_to_km, 2)

            _LOGGER.info(
                "%s: distance trajet API = %.1f km (%d segment(s) entre %s et %s)",
                self.tracker_name, distance_km, len(trips),
                from_date.strftime("%H:%M"), to_date.strftime("%H:%M"),
            )
            return distance_km

        except Exception as err:
            _LOGGER.error(
                "%s: erreur fetch distance plein : %s",
                self.tracker_name, err,
            )
            return 0.0