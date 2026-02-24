# 🏍️ GeoRide Trips — Intégration Home Assistant

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://github.com/druide93/Georide-Trips)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.1+-green.svg)](https://www.home-assistant.io/)

Intégration Home Assistant complète pour les trackers GPS **GeoRide**, permettant le suivi des trajets moto, le calcul d'odometer corrigé, la gestion de l'entretien (chaîne, vidange, révision), le suivi de l'autonomie carburant et les alertes de sécurité en temps réel.

---

## ✨ Fonctionnalités

| Domaine | Fonctionnalité |
|---|---|
| 🗺️ **Trajets** | Historique des 30 derniers jours, dernier trajet détaillé, notification à l'arrêt |
| 🔢 **Odometer** | Kilométrage réel avec offset configurable (km avant l'installation du tracker) |
| 📅 **Kilométrage périodique** | Compteurs journaliers, hebdomadaires et mensuels calculés automatiquement |
| ⛽ **Carburant** | Autonomie restante avec moyenne glissante sur 3 pleins, alerte sous seuil |
| 🔗 **Entretien chaîne** | Suivi km depuis le dernier entretien, alerte sous seuil configurable |
| 🛢️ **Vidange** | Suivi km depuis la dernière vidange, alerte sous seuil configurable |
| 🔧 **Révision** | Double critère km **et** jours, alerte dès que l'un des deux seuils est atteint |
| 🚨 **Sécurité** | Alarme vol, chute détectée, position en temps réel via Socket.IO |
| 🔋 **Batterie** | Niveau de batterie externe (moto) et interne (tracker) |
| 📡 **Temps réel** | Connexion Socket.IO pour mises à jour instantanées (mouvement, alarmes) |
| 🌿 **Mode éco** | Activation/désactivation du mode éco du tracker depuis HA |

---

## 🏗️ Architecture

L'intégration repose sur une **architecture hybride** combinant :

- **Socket.IO** (`socket.georide.com`) : mises à jour temps réel pour la position, le mouvement et les alarmes (vol, chute). La latence est quasi nulle.
- **Polling HTTP** (`api.georide.fr`) via trois coordinators indépendants :
  - **Trips Coordinator** : récupère les trajets des 30 derniers jours (polling toutes les heures par défaut). Déclenche un refresh immédiat à chaque arrêt de 5 minutes confirmé via Socket.IO.
  - **Lifetime Coordinator** : cumule le kilométrage total à vie via l'API `/trips` (polling toutes les 24h). Se rafraîchit à minuit et dès qu'un nouveau trajet est détecté.
  - **Status Coordinator** : récupère l'état du tracker (batterie, statut ligne, mode éco) via `/user/trackers` (polling toutes les 5 minutes).

```
GeoRide API ──────► Trips Coordinator    (1h)  ──► Trajets, odometer récent
              ├───► Lifetime Coordinator  (24h) ──► Odometer total à vie
              └───► Status Coordinator   (5min) ──► Batterie, statut, mode éco

socket.georide.com ──► Socket.IO ──► Position, mouvement, alarmes (temps réel)
```

---

## 📦 Installation

### Via HACS (recommandé)

1. Dans HACS, aller dans **Intégrations** → menu ⋮ → **Dépôts personnalisés**
2. Ajouter `https://github.com/druide93/Georide-Trips` avec la catégorie **Intégration**
3. Rechercher **GeoRide Trips** et installer
4. Redémarrer Home Assistant

### Manuel

1. Copier le dossier `georide_trips` dans `config/custom_components/`
2. Redémarrer Home Assistant

### Configuration

1. Aller dans **Paramètres → Appareils et services → Ajouter une intégration**
2. Rechercher **GeoRide Trips**
3. Saisir l'email et le mot de passe du compte GeoRide
4. L'intégration crée automatiquement un **appareil par tracker** détecté sur le compte

#### Options avancées (configurables après installation)

| Option | Défaut | Description |
|---|---|---|
| Socket.IO activé | `true` | Active les mises à jour temps réel |
| Polling trajets | `3600 s` | Intervalle de rafraîchissement des trajets (5 min – 24h) |
| Polling lifetime | `86400 s` | Intervalle de rafraîchissement de l'odometer total (1h – 7j) |
| Polling statut tracker | `300 s` | Intervalle de rafraîchissement batterie/statut (1 min – 1h) |
| Historique trajets | `30 jours` | Fenêtre temporelle des trajets récupérés (1–365 jours) |

---

## 📊 Entités créées par tracker

### Sensors (`sensor.*`)

#### Trajets
| Entité | Description | Unité |
|---|---|---|
| `*_last_trip` | Dernier trajet (état : distance en km) | km |
| `*_last_trip_details` | Détails du dernier trajet (attributs complets) | — |
| `*_total_distance` | Distance totale des trajets récents (fenêtre configurée) | km |
| `*_trip_count` | Nombre de trajets sur la période | — |

#### Kilométrage
| Entité | Description | Unité |
|---|---|---|
| `*_lifetime_odometer` | Kilométrage total brut depuis l'installation du tracker | km |
| `*_odometer` | Odometer réel = lifetime + offset (km avant installation) | km |
| `*_km_journaliers` | Km parcourus depuis minuit | km |
| `*_km_hebdomadaires` | Km parcourus depuis lundi minuit | km |
| `*_km_mensuels` | Km parcourus depuis le 1er du mois | km |

#### Entretien
| Entité | Description | Unité |
|---|---|---|
| `*_km_restants_chaine` | Km restants avant le prochain entretien chaîne | km |
| `*_km_restants_vidange` | Km restants avant la prochaine vidange | km |
| `*_km_restants_revision` | Km restants avant la prochaine révision | km |
| `*_jours_restants_revision` | Jours restants avant la prochaine révision | jours |

#### Carburant
| Entité | Description | Unité |
|---|---|---|
| `*_autonomie_restante` | Km restants estimés sur le plein actuel | km |

#### Tracker
| Entité | Description | Unité |
|---|---|---|
| `*_tracker_status` | Statut du tracker (online / offline) | — |
| `*_external_battery` | Niveau de batterie externe (moto) | V |
| `*_internal_battery` | Niveau de batterie interne (tracker) | V |
| `*_last_alarm` | Dernière alarme reçue via Socket.IO | — |

### Binary Sensors (`binary_sensor.*`)

| Entité | Source | Description |
|---|---|---|
| `*_en_mouvement` | Socket.IO | `on` si la moto est en mouvement |
| `*_alarme_vol` | Socket.IO | `on` si l'alarme antivol est active |
| `*_chute_detectee` | Socket.IO | `on` si une chute est détectée |
| `*_online` | Status Coordinator | `on` si le tracker est connecté |
| `*_locked` | Status Coordinator | `on` si le tracker est verrouillé |

### Switches (`switch.*`)

| Entité | Description |
|---|---|
| `*_faire_le_plein` | Activé automatiquement quand l'autonomie passe sous le seuil |
| `*_entretien_chaine_a_faire` | Activé quand les km restants chaîne passent sous le seuil |
| `*_vidange_a_faire` | Activé quand les km restants vidange passent sous le seuil |
| `*_revision_a_faire` | Activé quand les km restants révision passent sous le seuil |
| `*_mode_eco` | Active / désactive le mode éco du tracker via l'API |

> Les switches d'entretien et carburant survivent aux redémarrages (`RestoreEntity`). Les notifications ne sont envoyées qu'une fois par transition `off → on` grâce au blueprint.

### Buttons (`button.*`)

| Entité | Action |
|---|---|
| `*_refresh_trips` | Force le rafraîchissement des trajets récents |
| `*_refresh_odometer` | Force le rafraîchissement du kilométrage lifetime |
| `*_confirmer_le_plein` | Enregistre le plein (odometer + historique inter-plein) |
| `*_enregistrer_entretien_chaine` | Enregistre le dernier entretien chaîne (odometer + date) |
| `*_enregistrer_vidange` | Enregistre la dernière vidange (odometer + date) |
| `*_enregistrer_revision` | Enregistre la dernière révision (odometer + date) |

### Numbers (`number.*`)

#### Configuration odometer
| Entité | Description | Défaut |
|---|---|---|
| `*_odometer_offset` | Km à ajouter à l'odometer tracker (km avant installation) | 0 km |

#### Configuration carburant
| Entité | Description | Défaut |
|---|---|---|
| `*_autonomie_totale` | Autonomie théorique sur un plein | 150 km |
| `*_seuil_alerte_autonomie` | Seuil d'alerte autonomie | 30 km |
| `*_km_dernier_plein` | Odometer au dernier plein (stockage) | — |

#### Configuration entretien chaîne
| Entité | Description | Défaut |
|---|---|---|
| `*_intervalle_km_chaine` | Km entre deux entretiens | 500 km |
| `*_seuil_alerte_chaine` | Km avant échéance pour alerter | 50 km |
| `*_km_dernier_entretien_chaine` | Odometer au dernier entretien (stockage) | — |

#### Configuration vidange
| Entité | Description | Défaut |
|---|---|---|
| `*_intervalle_km_vidange` | Km entre deux vidanges | 6000 km |
| `*_seuil_alerte_vidange` | Km avant échéance pour alerter | 500 km |
| `*_km_derniere_vidange` | Odometer à la dernière vidange (stockage) | — |

#### Configuration révision
| Entité | Description | Défaut |
|---|---|---|
| `*_intervalle_km_revision` | Km entre deux révisions | 12000 km |
| `*_intervalle_jours_revision` | Jours max entre révisions | 365 jours |
| `*_seuil_alerte_revision` | Km avant échéance pour alerter | 1000 km |
| `*_km_derniere_revision` | Odometer à la dernière révision (stockage) | — |

#### Configuration kilométrage périodique
| Entité | Description |
|---|---|
| `*_seuil_distance_trajet` | Distance minimale pour notifier un trajet |
| `*_km_debut_journee` | Snapshot odometer à minuit (calculé automatiquement) |
| `*_km_debut_semaine` | Snapshot odometer lundi minuit (calculé automatiquement) |
| `*_km_debut_mois` | Snapshot odometer 1er du mois (calculé automatiquement) |

### Datetimes (`datetime.*`)

| Entité | Description |
|---|---|
| `*_date_dernier_entretien_chaine` | Date du dernier entretien chaîne |
| `*_date_derniere_vidange` | Date de la dernière vidange |
| `*_date_derniere_revision` | Date de la dernière révision |

### Device Tracker (`device_tracker.*`)

| Entité | Description |
|---|---|
| `*_position` | Position GPS en temps réel de la moto |

---

## 🤖 Blueprint d'automatisation

L'intégration est livrée avec un **blueprint complet** (`georide-trips.yaml`) gérant l'ensemble des notifications et de la logique métier. **Créer une instance par moto.**

### Fonctionnalités du blueprint (v21)

**⛽ Carburant**
- Notification push quand l'autonomie passe sous le seuil avec bouton d'action *Plein effectué*
- Enregistrement automatique du plein : odometer précis capturé après 5 min d'arrêt
- Calcul de l'autonomie moyenne glissante sur les 3 derniers pleins

**🗺️ Nouveau trajet**
- Notification à chaque arrêt si la distance dépasse le seuil configuré
- Contenu : distance, durée, vitesse moyenne, vitesse max, adresse de départ/arrivée
- Latence quasi nulle avec Socket.IO ; fallback automatique sans Socket.IO

**🔗 Entretien chaîne / 🛢️ Vidange / 🔧 Révision**
- Notification unique à la transition `off → on` du switch correspondant
- Bouton d'action *Entretien effectué* → enregistrement odometer + date automatique
- Aucune notification en double lors des redémarrages de HA

**📅 Kilométrage périodique**
- Snapshots automatiques à minuit, lundi minuit, et au jour configurable du mois
- Bilans hebdomadaires et mensuels en notification push et/ou persistante

**🚨 Sécurité**
- Notification immédiate en cas d'alarme vol ou de chute détectée

### Installation du blueprint

1. Copier `georide-trips.yaml` dans `config/blueprints/automation/georide_trips/`
2. Dans HA : **Paramètres → Automatisations → Blueprints**
3. Créer une automatisation depuis le blueprint **Moto GeoRide - Suivi complet**
4. Configurer les entités de chaque section (moto, capteurs, notifications…)

---

## 🔧 Calcul de l'odometer

Le tracker GeoRide ne comptabilise les km qu'à partir de sa **date d'installation**, pas depuis l'origine de la moto. L'entité `*_odometer` applique un **offset** pour restituer le kilométrage réel :

```
Odometer réel = Lifetime tracker (km depuis installation) + Offset (km avant installation)
```

L'offset est configurable directement depuis l'interface HA via `number.*_odometer_offset`. Toutes les entités d'entretien et de carburant utilisent cet odometer corrigé.

---

## 📋 Prérequis

- Home Assistant 2024.1 ou supérieur
- Un compte GeoRide avec au moins un tracker actif
- Application **Home Assistant Companion** (pour les notifications push avec boutons d'action)
- Python 3.11+

### Dépendances Python (installées automatiquement)

- `aiohttp >= 3.8.0`
- `python-socketio[asyncio_client] >= 5.0`

---

## 🌐 Endpoints API utilisés

| Endpoint | Usage |
|---|---|
| `POST /user/login` | Authentification |
| `GET /user/trackers` | Liste des trackers + statut |
| `GET /tracker/{id}/trips` | Historique des trajets |
| `GET /tracker/{id}/trip/{trip_id}/positions` | Positions d'un trajet |
| `PUT /tracker/{id}/eco-mode/on` | Activer le mode éco |
| `PUT /tracker/{id}/eco-mode/off` | Désactiver le mode éco |
| `Socket.IO socket.georide.com` | Événements temps réel |

---

## 🛠️ Dépannage

**Le kilométrage lifetime ne se met pas à jour**
Vérifier que le coordinator lifetime n'est pas en erreur dans les logs. Le refresh est déclenché à minuit et après chaque nouveau trajet.

**L'odometer est incorrect**
Configurer `number.*_odometer_offset` avec le kilométrage de la moto au moment de l'installation du tracker.

**Les notifications d'entretien se répètent**
Vérifier que le switch correspondant (ex. `switch.*_vidange_a_faire`) repasse bien à `off` lors de la confirmation d'entretien. Le blueprint ne notifie qu'à la transition `off → on`.

**Socket.IO se déconnecte fréquemment**
Normal en cas de réseau instable — le polling HTTP prend le relais automatiquement. Désactiver Socket.IO dans les options si la connexion est trop instable.

**Les entités n'apparaissent pas après installation**
S'assurer que le dossier s'appelle exactement `georide_trips` et redémarrer Home Assistant (pas seulement recharger).

---

## 📄 Licence

MIT License — Voir [LICENSE](LICENSE) pour les détails.

---

## 🤝 Contribution

Les issues et pull requests sont les bienvenus sur [GitHub](https://github.com/druide93/Georide-Trips).
