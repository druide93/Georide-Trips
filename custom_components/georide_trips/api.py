"""GeoRide API Client."""
import logging
import aiohttp
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

_LOGGER = logging.getLogger(__name__)


class GeoRideTripsAPI:
    """GeoRide Trips API Client."""

    def __init__(self, email: str, password: str, session: aiohttp.ClientSession):
        """Initialize the API client."""
        self.email = email
        self.password = password
        self.session = session
        self.base_url = "https://api.georide.fr"
        self.token = None

    async def login(self) -> bool:
        """Login to GeoRide API."""
        url = f"{self.base_url}/user/login"
        data = {
            "email": self.email,
            "password": self.password
        }
        
        try:
            async with self.session.post(url, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    self.token = result.get("authToken")
                    _LOGGER.debug("Successfully logged in to GeoRide API")
                    return True
                else:
                    _LOGGER.error("Failed to login: %s", response.status)
                    return False
        except Exception as err:
            _LOGGER.error("Error during login: %s", err)
            return False

    async def get_trackers(self) -> List[Dict[str, Any]]:
        """Get list of trackers."""
        if not self.token:
            await self.login()
        
        url = f"{self.base_url}/user/trackers"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        try:
            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    _LOGGER.error("Failed to get trackers: %s", response.status)
                    return []
        except Exception as err:
            _LOGGER.error("Error getting trackers: %s", err)
            return []

    async def get_trips(
        self,
        tracker_id: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        _retry: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get trips for a tracker."""
        if not self.token:
            await self.login()

        # Default to last 30 days
        if from_date is None:
            from_date = datetime.now(timezone.utc) - timedelta(days=30)
        if to_date is None:
            to_date = datetime.now(timezone.utc)

        # Format dates
        from_str = from_date.strftime("%Y%m%dT%H%M%S")
        to_str = to_date.strftime("%Y%m%dT%H%M%S")

        url = f"{self.base_url}/tracker/{tracker_id}/trips"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        params = {
            "from": from_str,
            "to": to_str
        }

        try:
            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    trips = await response.json()
                    _LOGGER.debug("Retrieved %d trips for tracker %s", len(trips), tracker_id)
                    return trips
                elif response.status == 401 and _retry:
                    # Token expired, retry once with new login
                    _LOGGER.warning("Token expired, re-authenticating...")
                    if not await self.login():
                        _LOGGER.error("Re-authentication failed, cannot fetch trips")
                        return []
                    return await self.get_trips(tracker_id, from_date, to_date, _retry=False)
                else:
                    _LOGGER.error("Failed to get trips: %s", response.status)
                    return []
        except Exception as err:
            _LOGGER.error("Error getting trips: %s", err)
            return []

    async def get_last_position(self, tracker_id: str) -> Optional[Dict[str, Any]]:
        """Get last known position via the last trip's positions endpoint.

        L'API GeoRide n'expose pas d'endpoint /positions/last.
        On récupère les trips des dernières 24h et on prend la dernière position du dernier trip.
        """
        if not self.token:
            await self.login()

        # Récupérer les trips récents (24h)
        from_date = datetime.now(timezone.utc) - timedelta(hours=24)
        to_date = datetime.now(timezone.utc)
        trips = await self.get_trips(tracker_id, from_date, to_date)

        if not trips:
            # Élargir à 7 jours si aucun trip dans les 24h
            from_date = datetime.now(timezone.utc) - timedelta(days=7)
            trips = await self.get_trips(tracker_id, from_date, to_date)

        if not trips:
            _LOGGER.debug("No recent trips for tracker %s, cannot get last position", tracker_id)
            return None

        # Prendre le trip le plus récent
        last_trip = sorted(trips, key=lambda t: t.get("endDate", t.get("startDate", "")))[-1]
        trip_start = last_trip.get("startDate") or last_trip.get("startTime")
        trip_end = last_trip.get("endDate") or last_trip.get("endTime")

        if not trip_start or not trip_end:
            _LOGGER.debug("Trip has no start/end date for tracker %s", tracker_id)
            return None

        # Récupérer les positions de ce trip
        positions = await self.get_trip_positions_by_date(tracker_id, trip_start, trip_end)

        if not positions:
            return None

        # Retourner la dernière position
        last = positions[-1]
        _LOGGER.debug("Last position for tracker %s: %s", tracker_id, last)
        return last

    async def get_trip_positions_by_date(
        self,
        tracker_id: str,
        from_date: str,
        to_date: str,
        _retry: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get positions for a trip by date range (ISO 8601 strings)."""
        if not self.token:
            await self.login()

        url = f"{self.base_url}/tracker/{tracker_id}/trips/positions"
        headers = {"Authorization": f"Bearer {self.token}"}
        params = {"from": from_date, "to": to_date}

        try:
            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    # L'API retourne {"positions": [...]} ou directement [...]
                    if isinstance(data, dict):
                        return data.get("positions", [])
                    return data
                elif response.status == 401 and _retry:
                    _LOGGER.warning("Token expired, re-authenticating...")
                    if not await self.login():
                        _LOGGER.error("Re-authentication failed, cannot fetch positions")
                        return []
                    return await self.get_trip_positions_by_date(tracker_id, from_date, to_date, _retry=False)
                else:
                    _LOGGER.error("Failed to get trip positions: %s", response.status)
                    return []
        except Exception as err:
            _LOGGER.error("Error getting trip positions: %s", err)
            return []

    async def get_trip_positions(
        self,
        tracker_id: str,
        trip_id: str
    ) -> List[Dict[str, Any]]:
        """Get positions for a specific trip."""
        if not self.token:
            await self.login()

        url = f"{self.base_url}/tracker/{tracker_id}/trip/{trip_id}/positions"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        try:
            async with self.session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    _LOGGER.error("Failed to get trip positions: %s", response.status)
                    return []
        except Exception as err:
            _LOGGER.error("Error getting trip positions: %s", err)
            return []

    async def get_tracker_status(self, tracker_id: str) -> Optional[Dict[str, Any]]:
        """Get tracker status (online/offline, isLocked, battery, etc.).

        Utilise GET /user/trackers et filtre sur tracker_id.
        Le GeoRideTrackerStatusCoordinator appelle cette méthode toutes les 5 min
        pour alimenter les binary_sensors "En ligne" et "Verrouillé".
        """
        if not self.token:
            await self.login()

        try:
            trackers = await self.get_trackers()
            for tracker in trackers:
                if str(tracker.get("trackerId")) == str(tracker_id):
                    _LOGGER.debug(
                        "Tracker status for %s: status=%s isLocked=%s",
                        tracker_id,
                        tracker.get("status"),
                        tracker.get("isLocked"),
                    )
                    return tracker
            _LOGGER.warning("Tracker %s not found in /user/trackers response", tracker_id)
            return None
        except Exception as err:
            _LOGGER.error("Error getting tracker status: %s", err)
            return None

    async def set_eco_mode(self, tracker_id: str, enabled: bool) -> bool:
        """Enable or disable eco mode for a tracker.

        Endpoint: PUT /tracker/{tracker_id}/eco
        Body: {"isInEco": true/false}
        """
        if not self.token:
            await self.login()

        url = f"{self.base_url}/tracker/{tracker_id}/eco"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        body = {"isInEco": enabled}

        try:
            async with self.session.put(url, headers=headers, json=body) as response:
                if response.status in (200, 204):
                    _LOGGER.info(
                        "Eco mode %s for tracker %s",
                        "enabled" if enabled else "disabled",
                        tracker_id,
                    )
                    return True
                elif response.status == 401:
                    _LOGGER.warning("Token expired, re-authenticating...")
                    await self.login()
                    return await self.set_eco_mode(tracker_id, enabled)
                else:
                    text = await response.text()
                    _LOGGER.error(
                        "Failed to set eco mode: status=%s body=%s",
                        response.status, text,
                    )
                    return False
        except Exception as err:
            _LOGGER.error("Error setting eco mode: %s", err)
            return False