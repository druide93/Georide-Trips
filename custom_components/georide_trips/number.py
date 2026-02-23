"""GeoRide Trips number entities.

Entités number rattachées au device de chaque moto :

── Carburant ──────────────────────────────────────────────────────
- autonomie_totale              : km théoriques sur un plein (config)
- seuil_alerte_autonomie        : km restants pour déclencher l'alerte (config)
- km_dernier_plein              : snapshot odometer au dernier plein
- km_restants_avant_plein       : autonomie restante calculée (diagnostic)

── Kilométrage périodique ─────────────────────────────────────────
- km_debut_journee              : snapshot odometer à minuit (diagnostic)
- km_journaliers                : km parcourus aujourd'hui (diagnostic)
- km_debut_semaine              : snapshot odometer lundi minuit (diagnostic)
- km_hebdomadaires              : km parcourus cette semaine (diagnostic)
- km_debut_mois                 : snapshot odometer 1er du mois (diagnostic)
- km_mensuels                   : km parcourus ce mois (diagnostic)

── Entretien - Chaîne ────────────────────────────────────────────
- intervalle_km_chaine          : km entre deux entretiens (config)
- seuil_alerte_chaine           : km avant échéance pour alerter (config)
- km_dernier_entretien_chaine   : snapshot odometer au dernier entretien (config)
- km_restants_chaine            : km restants avant échéance (diagnostic)

── Entretien - Vidange ───────────────────────────────────────────
- intervalle_km_vidange         : km entre deux vidanges (config)
- seuil_alerte_vidange          : km avant échéance pour alerter (config)
- km_dernier_entretien_vidange  : snapshot odometer à la dernière vidange (config)
- km_restants_vidange           : km restants avant échéance (diagnostic)

── Entretien - Révision ──────────────────────────────────────────
- intervalle_km_revision            : km entre deux révisions (config)
- intervalle_jours_revision         : jours max entre révisions (config)
- seuil_alerte_revision             : km avant échéance pour alerter (config)
- km_dernier_entretien_revision     : snapshot odometer à la dernière révision (config)
- km_restants_revision              : km restants avant échéance (diagnostic)

── Trajets ───────────────────────────────────────────────────────
- seuil_distance_trajet         : distance minimale pour notifier (config)

── Offset ────────────────────────────────────────────────────────
- odometer_offset               : décalage kilométrage (km avant tracker)
"""
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

NUMBER_DESCRIPTIONS = [

    # ── Odometer offset ───────────────────────────────────────────────────────
    {
        "key": "odometer_offset",
        "name": "Odometer Offset",
        "icon": "mdi:plus-circle",
        "unit": UnitOfLength.KILOMETERS,
        "min": -100_000, "max": 100_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": None,
    },

    # ── Persistance du cumul lifetime (usage interne) ─────────────────────────
    {
        "key": "lifetime_km_cumule",
        "name": "Lifetime KM cumulés (stockage)",
        "icon": "mdi:database",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 1_000_000, "step": 0.01, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },


    # ── Carburant ─────────────────────────────────────────────────────────────
    {
        "key": "autonomie_totale",
        "name": "Autonomie totale",
        "icon": "mdi:gas-station",
        "unit": UnitOfLength.KILOMETERS,
        "min": 50, "max": 800, "step": 1, "default": 150,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "seuil_alerte_autonomie",
        "name": "Seuil alerte autonomie",
        "icon": "mdi:alert-circle",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 200, "step": 5, "default": 30,
        "mode": NumberMode.SLIDER,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "km_dernier_plein",
        "name": "KM au dernier plein",
        "icon": "mdi:gas-station-outline",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 200_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": None,
    },
    {
        "key": "km_restants_avant_plein",
        "name": "KM restants avant plein",
        "icon": "mdi:map-marker-distance",
        "unit": UnitOfLength.KILOMETERS,
        "min": -100, "max": 800, "step": 1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },

    # ── Kilométrage périodique ─────────────────────────────────────────────────
    {
        "key": "km_debut_journee",
        "name": "KM début journée",
        "icon": "mdi:clock-start",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 200_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    {
        "key": "km_journaliers",
        "name": "KM journaliers",
        "icon": "mdi:counter",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 5_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    {
        "key": "km_debut_semaine",
        "name": "KM début semaine",
        "icon": "mdi:calendar-week",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 200_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    {
        "key": "km_hebdomadaires",
        "name": "KM hebdomadaires",
        "icon": "mdi:calendar-week",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 10_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    {
        "key": "km_debut_mois",
        "name": "KM début mois",
        "icon": "mdi:calendar-month",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 200_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    {
        "key": "km_mensuels",
        "name": "KM mensuels",
        "icon": "mdi:calendar-month",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 20_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },

    # ── Entretien - Chaîne ────────────────────────────────────────────────────
    {
        "key": "intervalle_km_chaine",
        "name": "Entretien chaîne - Intervalle km",
        "icon": "mdi:link-variant",
        "unit": UnitOfLength.KILOMETERS,
        "min": 100, "max": 10_000, "step": 100, "default": 500,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "seuil_alerte_chaine",
        "name": "Entretien chaîne - Seuil alerte",
        "icon": "mdi:link-variant-remove",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 500, "step": 50, "default": 100,
        "mode": NumberMode.SLIDER,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "km_dernier_entretien_chaine",
        "name": "Entretien chaîne - KM au dernier entretien",
        "icon": "mdi:link-variant-plus",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 200_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "km_restants_chaine",
        "name": "Entretien chaîne - KM restants avant entretien",
        "icon": "mdi:link-variant-plus",
        "unit": UnitOfLength.KILOMETERS,
        "min": -100, "max": 60_000, "step": 1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },

    # ── Entretien - Révision ──────────────────────────────────────────────────
    {
        "key": "intervalle_km_revision",
        "name": "Révision - Intervalle km",
        "icon": "mdi:wrench-clock",
        "unit": UnitOfLength.KILOMETERS,
        "min": 1_000, "max": 50_000, "step": 500, "default": 6_000,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "intervalle_jours_revision",
        "name": "Révision - Intervalle jours",
        "icon": "mdi:calendar-clock",
        "unit": "d",   # jours
        "min": 30, "max": 730, "step": 30, "default": 365,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "seuil_alerte_revision",
        "name": "Révision - Seuil alerte",
        "icon": "mdi:wrench-outline",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 2_000, "step": 100, "default": 500,
        "mode": NumberMode.SLIDER,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "km_dernier_entretien_revision",
        "name": "Révision - KM à la dernière révision",
        "icon": "mdi:wrench-check",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 200_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "km_restants_avant_entretien_revision",
        "name": "Révision - KM restants avant revision",
        "icon": "mdi:wrench-check",
        "unit": UnitOfLength.KILOMETERS,
        "min": -100, "max": 60_000, "step": 1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },

    # ── Entretien - Vidange ──────────────────────────────────────────────────
    {
        "key": "intervalle_km_vidange",
        "name": "Vidange - Intervalle km",
        "icon": "mdi:oil",
        "unit": UnitOfLength.KILOMETERS,
        "min": 1_000, "max": 50_000, "step": 500, "default": 6_000,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "seuil_alerte_vidange",
        "name": "Vidange - Seuil alerte",
        "icon": "mdi:oil-level",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 2_000, "step": 100, "default": 500,
        "mode": NumberMode.SLIDER,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "km_dernier_entretien_vidange",
        "name": "Vidange - KM à la dernière vidange",
        "icon": "mdi:oil-check",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 200_000, "step": 0.1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.CONFIG,
    },
    {
        "key": "km_restants_vidange",
        "name": "Vidange - KM restants avant vidange",
        "icon": "mdi:oil-check",
        "unit": UnitOfLength.KILOMETERS,
        "min": -100, "max": 60_000, "step": 1, "default": 0,
        "mode": NumberMode.BOX,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },

        # ── Trajets ───────────────────────────────────────────────────────────────
    {
        "key": "seuil_distance_trajet",
        "name": "Seuil notification trajet",
        "icon": "mdi:map-marker-path",
        "unit": UnitOfLength.KILOMETERS,
        "min": 0, "max": 50, "step": 0.5, "default": 2,
        "mode": NumberMode.SLIDER,
        "entity_category": EntityCategory.CONFIG,
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GeoRide Trips number entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    trackers = data["trackers"]

    entities = []
    for tracker in trackers:
        for desc in NUMBER_DESCRIPTIONS:
            entities.append(GeoRideNumberEntity(entry, tracker, desc))

    async_add_entities(entities)
    _LOGGER.info(
        "Added %d number entities for %d trackers",
        len(entities),
        len(trackers),
    )


class GeoRideNumberEntity(NumberEntity, RestoreEntity):
    """Entité number persistante rattachée au device GeoRide."""

    def __init__(self, entry: ConfigEntry, tracker: dict, desc: dict) -> None:
        self._entry = entry
        self._tracker = tracker
        self._desc = desc

        self._tracker_id = str(tracker.get("trackerId"))
        self._tracker_name = tracker.get("trackerName", f"Tracker {self._tracker_id}")

        self._attr_unique_id = f"{self._tracker_id}_{desc['key']}"
        self._attr_name = f"{self._tracker_name} {desc['name']}"
        self._attr_icon = desc["icon"]
        self._attr_native_unit_of_measurement = desc.get("unit", UnitOfLength.KILOMETERS)
        self._attr_mode = desc["mode"]
        self._attr_native_min_value = float(desc["min"])
        self._attr_native_max_value = float(desc["max"])
        self._attr_native_step = float(desc["step"])
        self._attr_native_value = float(desc["default"])
        self._attr_entity_category = desc.get("entity_category")

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
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                try:
                    self._attr_native_value = float(last_state.state)
                except (ValueError, TypeError):
                    self._attr_native_value = float(self._desc["default"])

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        _LOGGER.debug("Set %s for %s: %s", self._desc["key"], self._tracker_name, value)