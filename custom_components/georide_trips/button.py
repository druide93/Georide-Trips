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
        • Stocker plein_pending_timestamp = now()
        • Stocker plein_pending_odometer = odometer en mémoire (fallback)
        • Éteindre le switch "Faire le plein"
        • S'abonner au prochain arrêt confirmé (5 min) du coordinator

    Étape 2 (_on_stop_confirmed_for_plein) — déclenchée après 5 min d'arrêt :
        • Appel API get_trips(activation_date → plein_pending_timestamp)
        • odometer_au_plein = sum(distances) / METERS_TO_KM + offset_km
        • Calcul distance inter-plein
        • Rotation FIFO historique (hist_3 ← hist_2 ← hist_1 ← nouveau)
        • Recalcul moyenne glissante (max 3 pleins)
        • Mise à jour km_dernier_plein + nb_pleins_enregistres
        • Reset plein_pending_timestamp = 0

    Fallback : si l'arrêt ne se produit pas dans FALLBACK_TIMEOUT secondes
        (ex: API SocketIO down, moto garée longtemps), utiliser
        plein_pending_odometer (valeur en mémoire au moment du press).
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
        self._activation_date = tracker.get("activationDate")
        self._prefix = self.tracker_name.lower().replace(" ", "_")

        self._attr_name = f"{self.tracker_name} Confirmer le plein"
        self._attr_unique_id = f"{self.tracker_id}_confirmer_plein"
        self._attr_icon = "mdi:gas-station-outline"

        # Gestion de l'abonnement au stop_confirmed et du timer fallback
        self._unregister_stop_cb: callable | None = None
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

    async def _set_number(self, key: str, value: float) -> None:
        await self._hass.services.async_call(
            "number", "set_value",
            {"entity_id": f"number.{self._prefix}_{key}", "value": value},
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
        """Annuler l'abonnement stop et le timer fallback en cours."""
        if self._unregister_stop_cb:
            self._unregister_stop_cb()
            self._unregister_stop_cb = None
        if self._fallback_timer:
            self._fallback_timer.cancel()
            self._fallback_timer = None

    # ── Étape 1 : press immédiat ──────────────────────────────────────────────

    async def async_press(self) -> None:
        """Étape 1 — Enregistrer le timestamp du plein et attendre l'arrêt confirmé."""
        p = self._prefix

        # Si un plein est déjà en attente, l'annuler proprement
        if self._unregister_stop_cb or self._fallback_timer:
            _LOGGER.warning(
                "%s: nouveau press plein alors qu'un plein était déjà en attente — annulation",
                self.tracker_name,
            )
            self._cancel_pending()

        # Snapshot timestamp + odometer mémoire (fallback)
        now_ts = datetime.now(timezone.utc).timestamp()
        odometer_memoire = self._get_float(f"sensor.{p}_odometer")

        await self._set_number("plein_pending_timestamp", now_ts)
        await self._set_number("plein_pending_odometer", odometer_memoire)
        await self._turn_off_switch(f"switch.{p}_faire_le_plein")

        _LOGGER.info(
            "%s: plein enregistré à %.0f (odometer mémoire=%.1f km) — "
            "attente arrêt confirmé pour calcul précis",
            self.tracker_name, now_ts, odometer_memoire,
        )

        # S'abonner au prochain arrêt confirmé du coordinator
        self._unregister_stop_cb = self._coordinator.on_stop_confirmed(
            self._on_stop_confirmed_for_plein
        )

        # Timer fallback : si pas d'arrêt dans FALLBACK_TIMEOUT → utiliser odometer mémoire
        self._fallback_timer = self._hass.loop.call_later(
            self.FALLBACK_TIMEOUT,
            lambda: self._hass.async_create_task(self._apply_fallback()),
        )

    # ── Étape 2 : arrêt confirmé ──────────────────────────────────────────────

    def _on_stop_confirmed_for_plein(self) -> None:
        """Callback appelé par le coordinator après 5 min d'arrêt — lancer le calcul."""
        # Annuler le fallback timer puisque l'arrêt est arrivé à temps
        if self._fallback_timer:
            self._fallback_timer.cancel()
            self._fallback_timer = None
        self._unregister_stop_cb = None  # déjà consommé (callback one-shot)

        self._hass.async_create_task(self._compute_and_record_plein(use_fallback=False))

    async def _apply_fallback(self) -> None:
        """Appelé si aucun arrêt confirmé dans FALLBACK_TIMEOUT — utiliser odometer mémoire."""
        self._cancel_pending()
        _LOGGER.warning(
            "%s: timeout fallback plein (%ds) — utilisation odometer mémoire",
            self.tracker_name, self.FALLBACK_TIMEOUT,
        )
        await self._compute_and_record_plein(use_fallback=True)

    # ── Calcul commun (API ou fallback) ───────────────────────────────────────

    async def _compute_and_record_plein(self, use_fallback: bool) -> None:
        """Calculer l'odometer au moment du plein et enregistrer toutes les métriques."""
        from .const import METERS_TO_KM

        p = self._prefix

        plein_ts = self._get_float(f"number.{p}_plein_pending_timestamp")
        km_dernier_plein = self._get_float(f"number.{p}_km_dernier_plein")
        offset_km = self._get_float(f"number.{p}_odometer_offset")

        if plein_ts == 0:
            _LOGGER.warning(
                "%s: _compute_and_record_plein appelé sans plein_pending_timestamp valide",
                self.tracker_name,
            )
            return

        # ── Calculer l'odometer au moment du plein ─────────────────────────
        if use_fallback:
            odometer_au_plein = self._get_float(f"number.{p}_plein_pending_odometer")
            _LOGGER.info(
                "%s: odometer plein (fallback mémoire) = %.1f km",
                self.tracker_name, odometer_au_plein,
            )
        else:
            odometer_au_plein = await self._fetch_odometer_at_timestamp(plein_ts, offset_km, METERS_TO_KM)
            if odometer_au_plein is None:
                # API a échoué → fallback automatique
                odometer_au_plein = self._get_float(f"number.{p}_plein_pending_odometer")
                _LOGGER.warning(
                    "%s: API échouée pour calcul plein, fallback odometer mémoire = %.1f km",
                    self.tracker_name, odometer_au_plein,
                )

        if odometer_au_plein <= 0:
            _LOGGER.error("%s: odometer au plein invalide (%.1f), abandon", self.tracker_name, odometer_au_plein)
            await self._set_number("plein_pending_timestamp", 0)
            return

        # ── Premier plein : juste snapshot, pas de calcul inter-plein ─────
        if km_dernier_plein == 0:
            _LOGGER.info(
                "%s: premier plein — snapshot odometer = %.1f km",
                self.tracker_name, odometer_au_plein,
            )
            await self._set_number("km_dernier_plein", odometer_au_plein)
            await self._set_number("nb_pleins_enregistres", 1)
            await self._set_number("plein_pending_timestamp", 0)
            return

        # ── Calcul distance inter-plein ────────────────────────────────────
        distance_inter_plein = round(odometer_au_plein - km_dernier_plein, 1)
        if distance_inter_plein <= 0:
            _LOGGER.warning(
                "%s: distance inter-plein négative (%.1f km), abandon",
                self.tracker_name, distance_inter_plein,
            )
            await self._set_number("plein_pending_timestamp", 0)
            return

        # ── Rotation FIFO historique ────────────────────────────────────────
        hist_1 = self._get_float(f"number.{p}_km_plein_hist_1")
        hist_2 = self._get_float(f"number.{p}_km_plein_hist_2")

        await self._set_number("km_plein_hist_3", hist_2)
        await self._set_number("km_plein_hist_2", hist_1)
        await self._set_number("km_plein_hist_1", distance_inter_plein)

        # ── Moyenne glissante (slots non-nuls, max HIST_SLOTS) ─────────────
        slots = [s for s in [distance_inter_plein, hist_1, hist_2] if s > 0]
        slots = slots[:self.HIST_SLOTS]
        moyenne = round(sum(slots) / len(slots), 1)

        nb_pleins = int(self._get_float(f"number.{p}_nb_pleins_enregistres")) + 1

        await self._set_number("autonomie_moyenne_calculee", moyenne)
        await self._set_number("nb_pleins_enregistres", nb_pleins)
        await self._set_number("km_dernier_plein", odometer_au_plein)
        await self._set_number("plein_pending_timestamp", 0)

        _LOGGER.info(
            "%s: plein confirmé — odometer=%.1f km, inter-plein=%.1f km, "
            "moyenne=%.1f km (%d valeur(s)), nb_pleins=%d, fallback=%s",
            self.tracker_name, odometer_au_plein, distance_inter_plein,
            moyenne, len(slots), nb_pleins, use_fallback,
        )

    async def _fetch_odometer_at_timestamp(
        self, plein_ts: float, offset_km: float, meters_to_km: float
    ) -> float | None:
        """Interroger l'API pour obtenir l'odometer exact au moment du plein.

        Récupère tous les trajets depuis l'activation jusqu'au timestamp du plein,
        somme les distances et ajoute l'offset.

        Returns:
            odometer en km, ou None si l'API a échoué.
        """
        try:
            from_date = None
            if self._activation_date:
                from datetime import datetime as dt
                try:
                    from_date = dt.fromisoformat(self._activation_date.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    _LOGGER.warning(
                        "%s: impossible de parser activation_date '%s'",
                        self.tracker_name, self._activation_date,
                    )

            to_date = datetime.fromtimestamp(plein_ts, tz=timezone.utc)

            _LOGGER.debug(
                "%s: fetch trips pour odometer plein : %s → %s",
                self.tracker_name,
                from_date.isoformat() if from_date else "début",
                to_date.isoformat(),
            )

            trips = await self._api.get_trips(
                self.tracker_id,
                from_date=from_date,
                to_date=to_date,
            )

            if trips is None:
                return None

            tracker_km = sum(t.get("distance", 0) for t in trips) / meters_to_km
            odometer = round(tracker_km + offset_km, 2)

            _LOGGER.info(
                "%s: odometer plein via API = %.1f km "
                "(tracker=%.1f km + offset=%.1f km, %d trips)",
                self.tracker_name, odometer, tracker_km, offset_km, len(trips),
            )
            return odometer

        except Exception as err:
            _LOGGER.error(
                "%s: erreur fetch odometer plein : %s",
                self.tracker_name, err,
            )
            return None
