"""GeoRide Trips — utilitaires partagés.

Centralise les fonctions et mixins réutilisés dans tout le projet :
- GeoRideEntityMixin : device_info + _get_float
- resolve_entity_id  : résolution fiable d'entity_id via l'entity registry
"""

import logging
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class GeoRideEntityMixin:
    """Mixin fournissant device_info et _get_float pour toutes les entités GeoRide.

    La classe qui hérite doit définir :
      - self.tracker_id  (str)
      - self.tracker_name (str)
      - self._tracker    (dict)
      - self._hass       (HomeAssistant)  — seulement pour _get_float
    """

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
        """Lire la valeur numérique d'une entité HA, avec fallback."""
        hass = getattr(self, "_hass", None) or getattr(self, "hass", None)
        if hass is None:
            return default
        state = hass.states.get(entity_id)
        if state and state.state not in (None, "unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return default


def resolve_entity_id(
    hass: HomeAssistant,
    domain: str,
    tracker_id: str,
    key: str,
) -> str | None:
    """Résoudre l'entity_id d'une entité GeoRide via l'entity registry.

    Utilise le unique_id = "{tracker_id}_{key}" pour retrouver
    l'entity_id réel, indépendamment du slug dérivé du nom.

    Args:
        hass: instance Home Assistant
        domain: domaine de l'entité (ex: "number", "datetime", "sensor")
        tracker_id: ID du tracker GeoRide
        key: clé de l'entité (ex: "autonomie_totale", "km_dernier_plein")

    Returns:
        entity_id (ex: "number.tmax_530_carburant_autonomie_totale") ou None
    """
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    unique_id = f"{tracker_id}_{key}"
    entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)

    if entity_id is None:
        _LOGGER.debug(
            "resolve_entity_id: entité introuvable — domain=%s unique_id=%s",
            domain, unique_id,
        )
    return entity_id