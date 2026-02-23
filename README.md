# 🏍️ GeoRide Trips — Intégration Home Assistant

[![Version](https://img.shields.io/badge/version-2.0.0-blue)]()
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-brightgreen)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Intégration Home Assistant complète pour les trackers GPS **GeoRide**. Suivi des trajets, gestion des entretiens, odomètre corrigé, alertes carburant et notifications mobiles interactives — une instance par moto, zéro helper externe.

---

## ✨ Fonctionnalités

### 📡 Connectivité
- **Polling HTTP** — Récupération régulière des trajets via l'API GeoRide
- **Socket.IO temps réel** *(beta)* — Connexion persistante pour la position GPS, la détection de mouvement, vol et chute sans délai de polling

### 🗺️ Position & Trajets
- Device tracker GPS par moto, alimenté en temps réel via Socket.IO
- Dernier trajet avec tous les attributs : distance, durée, vitesse moy./max., adresses départ/arrivée, coordonnées GPS
- Distance cumulée et nombre de trajets sur la période configurée

### 📏 Odomètre
- Kilométrage brut calculé depuis l'activation du tracker (tous les trajets)
- **Odomètre corrigé** = kilométrage tracker + offset configurable, pour aligner sur le compteur réel de la moto
- Ajustement unique via service HA `georide_trips.set_odometer`

### ⛽ Carburant
- Calcul automatique des km restants avant plein
- Alerte mobile dès que l'autonomie passe sous le seuil configuré
- Confirmation via bouton dans la notification → mise à jour automatique du kilométrage au dernier plein

### 📅 Kilométrage périodique
- Snapshots automatiques à minuit (jour), lundi minuit (semaine), jour configurable du mois
- Compteurs km journaliers, hebdomadaires et mensuels recalculés en continu
- Bilans hebdomadaire et mensuel envoyés en notification mobile et/ou persistante

### 🔧 Gestion des entretiens
Trois types d'entretien suivis de façon identique :

| Type | Critère |
|---|---|
| 🔗 Chaîne | Intervalle en km |
| 🛢️ Vidange huile | Intervalle en km |
| 🔧 Révision générale | Intervalle en km **ET** en jours (le premier atteint déclenche) |

Chaque entretien dispose d'un seuil d'alerte, d'un compteur de km restants, et d'une confirmation mobile qui enregistre automatiquement le kilométrage et la date.

### 🔔 Notifications mobiles
Toutes les alertes incluent des **actions de confirmation** directement dans la notification iOS/Android. Une seule appui suffit pour enregistrer un plein ou un entretien.

---

## 📦 Structure du projet

```
custom_components/georide_trips/
├── __init__.py           # Setup de l'intégration, services HA
├── api.py                # Client HTTP GeoRide (login, trackers, trips, positions)
├── config_flow.py        # Interface de configuration (UI)
├── const.py              # Constantes (domaine, clés, endpoints, Socket.IO)
├── manifest.json         # Métadonnées HA
├── services.yaml         # Déclaration des services
├── strings.json          # Traductions
│
├── sensor.py             # Odomètre, odomètre corrigé, trajets, distance, compteur
├── number.py             # Intervalles, seuils, km snapshots, diagnostics
├── button.py             # Refresh trajets, refresh odomètre, enregistrement entretiens
├── switch.py             # Faire le plein, entretien chaîne/vidange/révision à faire
├── datetime.py           # Dates de dernier entretien (chaîne, vidange, révision)
├── device_tracker.py     # Position GPS temps réel (Socket.IO + fallback API)
├── binary_sensor.py      # En mouvement, alarme vol, chute détectée (Socket.IO)
└── socket_manager.py     # Gestionnaire Socket.IO (connexion persistante, reconnexion auto)

blueprints/automation/
└── moto_georide_suivi.yaml   # Blueprint principal — une instance par moto
```

---

## 🚀 Installation

### Via HACS (recommandé)

1. Dans HACS → **Intégrations** → ⋮ → **Dépôts personnalisés**
2. Ajouter `https://github.com/druide93/Georide-Trips` — catégorie **Intégration**
3. Installer **GeoRide Trips**
4. Redémarrer Home Assistant

### Installation manuelle

```bash
cp -r custom_components/georide_trips/ /config/custom_components/
```

Redémarrer Home Assistant.

---

## ⚙️ Configuration

**Paramètres → Appareils & Services → Ajouter une intégration → GeoRide Trips**

Saisir votre email et mot de passe GeoRide. L'intégration crée automatiquement un appareil par tracker détecté sur le compte.

### Options (modifiables après installation)

| Option | Défaut | Description |
|---|---|---|
| Socket.IO temps réel | Activé | Position GPS et alertes sans polling. Désactiver si instable. |
| Intervalle trajets récents | 3600 s | Fréquence polling trajets (min. 300 s / 5 min) |
| Intervalle odomètre total | 86400 s | Fréquence polling kilométrage lifetime (min. 3600 s) |
| Jours d'historique | 30 | Fenêtre de récupération des trajets récents |

---

## 🔧 Services

### `georide_trips.set_odometer`
Définir le kilométrage réel de la moto. L'offset est calculé automatiquement et persisté.

```yaml
service: georide_trips.set_odometer
data:
  entity_id: sensor.tmax_530_odometer
  value: 15234.5
```

### `georide_trips.reset_odometer`
Remettre l'odomètre sur la valeur brute du tracker (offset = 0).

```yaml
service: georide_trips.reset_odometer
data:
  entity_id: sensor.tmax_530_odometer
```

### `georide_trips.get_trips`
Récupérer les trajets d'un tracker sur une période.

```yaml
service: georide_trips.get_trips
data:
  tracker_id: "2289417"
  from_date: "2025-01-01T00:00:00"
  to_date: "2025-01-31T23:59:59"
```

---

## 📐 Entités créées par moto

Exemple pour une moto nommée `tmax_530` :

### Capteurs (`sensor`)
| Entité | Description |
|---|---|
| `sensor.tmax_530_odometer` | Odomètre corrigé (tracker + offset) |
| `sensor.tmax_530_lifetime_odometer` | Kilométrage brut total depuis activation |
| `sensor.tmax_530_last_trip` | Date/heure du dernier trajet |
| `sensor.tmax_530_last_trip_details` | Résumé complet (distance, durée, vitesse, adresses…) |
| `sensor.tmax_530_total_distance` | Distance cumulée sur la période |
| `sensor.tmax_530_trip_count` | Nombre de trajets sur la période |

### Capteurs binaires (`binary_sensor`) — Socket.IO
| Entité | Description |
|---|---|
| `binary_sensor.tmax_530_en_mouvement` | Moto en mouvement (temps réel) |
| `binary_sensor.tmax_530_alarme_vol` | Alarme vol active |
| `binary_sensor.tmax_530_chute_detectee` | Chute détectée |

### Tracker GPS (`device_tracker`)
| Entité | Description |
|---|---|
| `device_tracker.tmax_530_position` | Position GPS (lat/lon, vitesse, cap, altitude) |

### Nombres (`number`) — config & diagnostic
```
number.tmax_530_odometer_offset
number.tmax_530_autonomie_totale
number.tmax_530_seuil_alerte_autonomie
number.tmax_530_km_au_dernier_plein
number.tmax_530_km_restants_avant_plein
number.tmax_530_km_debut_journee / km_journaliers
number.tmax_530_km_debut_semaine / km_hebdomadaires
number.tmax_530_km_debut_mois / km_mensuels
number.tmax_530_entretien_chaine_intervalle_km
number.tmax_530_entretien_chaine_seuil_alerte
number.tmax_530_entretien_chaine_km_au_dernier_entretien
number.tmax_530_entretien_chaine_km_restants_avant_entretien
# idem pour vidange et revision
```

### Switchs, boutons, datetimes
```
switch.tmax_530_faire_le_plein
switch.tmax_530_entretien_chaine_a_faire
switch.tmax_530_vidange_a_faire
switch.tmax_530_revision_a_faire

button.tmax_530_refresh_trips
button.tmax_530_refresh_odometer
button.tmax_530_enregistrer_entretien_chaine
button.tmax_530_enregistrer_vidange
button.tmax_530_enregistrer_revision

datetime.tmax_530_entretien_chaine_date_dernier_entretien
datetime.tmax_530_vidange_date_derniere_vidange
datetime.tmax_530_revision_date_derniere_revision
```

---

## 📐 Blueprint — Suivi moto GeoRide

Le fichier `blueprints/automation/moto_georide_suivi.yaml` automatise l'ensemble des fonctionnalités. Créer **une instance par moto** depuis **Paramètres → Automatisations → Blueprints**.

### Sections configurables

| Section | Contenu |
|---|---|
| 🏍️ Identité | Nom de la moto (utilisé dans les notifications) |
| 📡 Capteurs | Odomètre, binary_sensor moving, last trip, bouton refresh |
| ⛽ Carburant | Autonomie, km dernier plein, seuil alerte, switch |
| 📅 Kilométrage périodique | Entités snapshot + compteurs |
| 🔗 Chaîne | Intervalle, seuil, dernier entretien, switch, bouton enregistrer |
| 🛢️ Vidange | Intervalle, seuil, dernière vidange, switch, bouton enregistrer |
| 🔧 Révision | Intervalle km + jours, seuil, dernière révision, switch, bouton enregistrer |
| 🔔 Notifications | Service notify, activation par type d'alerte, seuil distance trajet |
| 📲 Actions mobiles | Identifiants uniques par moto (ex. `PLEIN_TMAX530`) |
| 📊 Bilan hebdomadaire | Activation, heure d'envoi, mobile et/ou persistant |
| 📊 Bilan mensuel | Activation, jour du mois, heure d'envoi, mobile et/ou persistant |

### Déclencheurs gérés

- Changement de l'odomètre (polling ou bouton refresh)
- Moto arrêtée (`binary_sensor moving` → `off`, via Socket.IO)
- Nouveau trajet détecté (`last_trip_details` change, fallback sans Socket.IO)
- Toutes les 15 min (compteurs périodiques)
- Toutes les 30 min (autonomie + entretiens en tâche de fond)
- Minuit (reset journalier, hebdomadaire et mensuel selon le jour)
- Heure configurée (bilans hebdo et mensuel)
- Actions mobiles de confirmation (plein, chaîne, vidange, révision)
- Boutons d'enregistrement natifs de l'intégration

---

## ⚠️ Socket.IO — Fonctionnalité beta

La connexion temps réel via Socket.IO est **fonctionnelle mais en beta**. Elle apporte :

- Position GPS mise à jour immédiatement (vs. attente du prochain polling)
- `binary_sensor` moving/vol/chute alimentés sans délai
- Déclenchement de la notification de fin de trajet dès l'arrêt de la moto

En cas d'instabilité, le gestionnaire reconnecte automatiquement avec un backoff exponentiel (jusqu'à 5 min entre chaque tentative). Pour désactiver Socket.IO, aller dans les options de l'intégration.

---

## 🐛 Debug & problèmes connus

**Les limites des entités `number` ne se mettent pas à jour après une modification du code**
`RestoreEntity` restaure les attributs depuis la base de données, pas depuis le code. Solution : utiliser le service `recorder.purge_entities` sur les entités concernées, puis redémarrer HA.

**Exécutions parasites des automatisations au démarrage**
Corrigé par la condition `not_from: [unavailable, unknown]` sur tous les triggers de type bouton et binary_sensor.

**Socket.IO ne se connecte pas**
Vérifier que `python-socketio[asyncio_client]>=5.0` est installé (déclaré dans `manifest.json`). Consulter les logs sous `Settings → System → Logs` en filtrant sur `georide_trips`.

---

## 🛣️ Roadmap

- [ ] **Socket.IO stable** — Passage en fonctionnalité standard après validation terrain
- [ ] **Sélection type de transmission** — Option pour masquer les entités chaîne (motos cardan/courroie)
- [ ] **Cartes Mushroom** — Templates dashboard préconfigurés
- [ ] **HACS officiel** — Soumission au store HACS

---

## 📄 Licence

MIT — voir [LICENSE](LICENSE)

---

## 🙏 Remerciements

Ce projet utilise l'API non officielle GeoRide et n'est pas affilié à **GeoRide SAS**.
