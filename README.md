# 🏍️ GeoRide Trips — Intégration Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Intégration Home Assistant complète pour les trackers GPS **GeoRide** montés sur moto. Au-delà du simple suivi GPS, elle fournit un odomètre réel corrigé, le suivi des entretiens, le calcul d'autonomie carburant et des notifications de trajet enrichies.

---

## ✨ Fonctionnalités

### 🗺️ Suivi GPS temps réel
Connexion **Socket.IO** persistante pour des mises à jour de position quasi instantanées, avec fallback automatique sur le polling HTTP si la connexion est perdue.

### 📏 Odomètre corrigé
GeoRide ne compte que les kilomètres parcourus depuis l'installation du tracker. L'intégration applique un **offset configurable** pour afficher le kilométrage réel de la moto.

### 🔗 Entretien chaîne
Suivi des km parcourus depuis le dernier entretien avec alerte configurable et bouton de confirmation depuis l'application mobile.

### 🛢️ Vidange
Même principe que la chaîne : alerte kilométrique avec confirmation mobile.

### 🔧 Révision générale
Double critère **km ET jours** — l'alerte se déclenche dès que l'un des deux seuils est atteint.

### ⛽ Autonomie carburant
Calcul de l'autonomie restante basé sur la consommation moyenne et le plein de référence, avec alerte sous un seuil configurable.

### 🚨 Alarmes temps réel
Notifications immédiates via Socket.IO pour les alarmes **chute/crash** (critique), vibration/vol, coupure d'alimentation, zone de sortie, etc.

### 📊 Statistiques périodiques
Snapshots automatiques (jour/semaine/mois) et bilans envoyés par notification mobile ou notification persistante dans HA.

---

## 📦 Entités créées par tracker

### Sensors
| Entité | Description |
|--------|-------------|
| `sensor.<moto>_last_trip` | Dernier trajet (distance, durée, vitesse) |
| `sensor.<moto>_last_trip_details` | Détails complets du dernier trajet |
| `sensor.<moto>_total_distance` | Distance totale sur la période |
| `sensor.<moto>_trip_count` | Nombre de trajets |
| `sensor.<moto>_lifetime_odometer` | Odomètre brut depuis installation |
| `sensor.<moto>_real_odometer` | Odomètre réel (offset appliqué) |
| `sensor.<moto>_tracker_status` | Statut du tracker (en ligne / hors ligne) |
| `sensor.<moto>_external_battery` | Batterie externe (12V moto) |
| `sensor.<moto>_internal_battery` | Batterie interne du tracker |
| `sensor.<moto>_last_alarm` | Dernière alarme reçue via Socket.IO |

### Binary sensors
| Entité | Description |
|--------|-------------|
| `binary_sensor.<moto>_moving` | Moto en mouvement (Socket.IO) |
| `binary_sensor.<moto>_stolen` | Alarme vol active |
| `binary_sensor.<moto>_crashed` | Chute détectée |
| `binary_sensor.<moto>_online` | Tracker en ligne (polling 5 min) |
| `binary_sensor.<moto>_locked` | Tracker verrouillé |

### Switches
| Entité | Description |
|--------|-------------|
| `switch.<moto>_faire_le_plein` | Plein à faire (activé automatiquement) |
| `switch.<moto>_entretien_chaine` | Entretien chaîne requis |
| `switch.<moto>_entretien_vidange` | Vidange requise |
| `switch.<moto>_entretien_revision` | Révision requise |
| `switch.<moto>_eco_mode` | Mode éco du tracker |

### Numbers (configuration & diagnostic)
Entités de configuration pour les intervalles, seuils d'alerte, km au dernier entretien et km restants pour chaque type d'entretien (chaîne, vidange, révision), offset odomètre, autonomie carburant, etc.

### Boutons
- `button.<moto>_refresh_odometer` — Forcer la mise à jour de l'odomètre

### Datetime
Dates des derniers entretiens (chaîne, vidange, révision) et curseur de dernier trajet.

### Device tracker
- `device_tracker.<moto>` — Position GPS sur la carte HA

---

## 🚀 Installation

### Via HACS (recommandé)
1. Ouvrir HACS → Intégrations → ⋮ → Dépôts personnalisés
2. Ajouter l'URL de ce dépôt, catégorie **Integration**
3. Chercher **GeoRide Trips** et installer
4. Redémarrer Home Assistant

### Manuellement
1. Copier le dossier `custom_components/georide_trips` dans votre répertoire `config/custom_components/`
2. Redémarrer Home Assistant

---

## ⚙️ Configuration

1. **Paramètres → Appareils et services → Ajouter une intégration**
2. Rechercher **GeoRide Trips**
3. Entrer votre email et mot de passe GeoRide
4. Un appareil est automatiquement créé pour chaque tracker détecté sur le compte

### Options configurables
| Option | Description | Défaut |
|--------|-------------|--------|
| Intervalle de polling trajets | Fréquence de récupération des trajets | 30 s |
| Intervalle odomètre lifetime | Fréquence de récupération lifetime | 300 s |
| Jours de trajets à récupérer | Fenêtre historique des trajets | 30 jours |
| Socket.IO activé | Connexion temps réel | Activé |
| Intervalle tracker status | Fréquence polling statut/batterie | 300 s |

---

## 🤖 Blueprint — Suivi complet (v17)

Un blueprint d'automation est fourni pour gérer une moto de bout en bout. **Créer une instance par moto.**

### Installation
1. Importer le blueprint depuis le fichier `blueprints/automation/moto_georide_suivi.yaml`
   ou via l'URL du dépôt dans **Paramètres → Automations → Blueprints → Importer**
2. Créer une nouvelle automation depuis ce blueprint
3. Configurer chaque section

### Sections disponibles
| Section | Fonctionnalité |
|---------|----------------|
| 🏍️ Identité | Nom et device tracker de la moto |
| 📏 Odomètre | Entités odomètre et offset |
| ⛽ Autonomie | Seuil d'alerte et suivi du plein |
| 🔗 Chaîne | Intervalle et suivi entretien |
| 🛢️ Vidange | Intervalle et suivi vidange |
| 🔧 Révision | Seuils km + jours |
| 📅 Kilométrage périodique | Configuration des snapshots |
| 🔔 Notifications & Trajets | Service mobile, activation par alerte |
| 📲 Actions mobiles | Identifiants uniques par moto |
| 🚨 Alarmes | Sélection des types d'alarmes à notifier |
| 📊 Bilan hebdomadaire | Heure d'envoi et canaux |
| 📊 Bilan mensuel | Jour du mois et canaux |

### Actions mobiles
Chaque confirmation (plein, chaîne, vidange, révision) est accessible directement depuis la notification push iOS/Android. Les identifiants doivent être **uniques par moto** (ex. `PLEIN_TMAX530`, `CHAINE_AFRICA_TWIN`).

---

## 🔌 Événements HA publiés

Le Socket.IO manager publie des événements sur le bus HA utilisables dans vos propres automations :

| Événement | Données | Description |
|-----------|---------|-------------|
| `georide_device_event` | `device_id`, `moving`, `stolen`, `crashed` | Changement d'état du device |
| `georide_alarm_event` | `device_id`, `device_name`, `type` | Alarme reçue |
| `georide_lock_event` | `device_id`, `device_name`, `locked` | Changement état verrou |

### Types d'alarmes (`georide_alarm_event`)
`alarm_vibration`, `alarm_exitZone`, `alarm_crash`, `alarm_crashParking`, `alarm_deviceOffline`, `alarm_deviceOnline`, `alarm_powerCut`, `alarm_powerUncut`, `alarm_batteryWarning`, `alarm_temperatureWarning`, `alarm_magnetOn`, `alarm_magnetOff`, `alarm_sonorAlarmOn`

---

## 📋 Prérequis

- Home Assistant 2024.1+
- Compte GeoRide avec tracker(s) associé(s)
- Application **Home Assistant Companion** pour les notifications push (optionnel)

---

## 🛠️ Service personnalisé

```yaml
service: georide_trips.set_odometer
data:
  entity_id: number.<moto>_odometer_offset
  value: 12345.6
```
Permet de mettre à jour programmatiquement l'offset odomètre sans passer par l'interface.

---

## 📝 Changelog

### v3 (2026-02-23)
- Ajout du sensor `last_alarm` alimenté par Socket.IO
- Blueprint v17 : section Alarmes avec 4 toggles de notification et push critique pour les crashes
- Fix : trigger `not_from: unavailable` sur les boutons pour éviter les exécutions parasites au redémarrage

### v2
- Connexion Socket.IO temps réel avec reconnexion automatique
- Binary sensors alimentés par Socket.IO (`moving`, `stolen`, `crashed`)
- Device tracker GPS temps réel

### v1
- Première version — polling HTTP, odomètre corrigé, entretiens, autonomie

---

## 🤝 Contribuer

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue pour signaler un bug ou proposer une fonctionnalité.

---

## 📄 Licence

MIT — voir [LICENSE](LICENSE)

---

*Testé sur Yamaha Tmax 530 et Honda Africa Twin avec trackers GeoRide.*
