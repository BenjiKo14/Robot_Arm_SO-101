# Interface Web SO-ARM101 Controller

Interface web moderne pour contrôler le bras robotique SO-ARM101, remplaçant l'interface GUI Tkinter.

## Installation

1. Installer les dépendances Python :
```bash
pip install -r requirements.txt
```

2. S'assurer que LeRobot est installé :
```bash
conda activate lerobot
pip install lerobot[feetech]
```

## Lancement

```bash
python web_app.py
```

ou

```bash
python start_web.py
```

L'interface sera accessible à l'adresse : http://localhost:5000

Ouvrez votre navigateur web et accédez à cette URL.

## 🔄 Rechargement Automatique (Hot Reload)

L'application supporte le **rechargement automatique à chaud** des modules Python :

### Comment ça fonctionne ?

1. **Modifiez n'importe quel fichier Python** (`.py`) dans le projet :
   - `config.py`
   - `motor_control.py`
   - `calibration.py`
   - `recording.py`
   - `normalization.py`
   - `web_app.py`

2. **Actualisez simplement la page web** (F5 ou Ctrl+R)

3. **Les changements sont automatiquement appliqués** sans redémarrer le serveur !

### Détails techniques

- Le système détecte automatiquement les modifications de fichiers
- Les modules sont rechargés à chaud avec `importlib.reload()`
- Les références globales sont mises à jour automatiquement
- Aucune interruption de service - la connexion au robot reste active
- Une notification apparaît dans la console du navigateur quand des modules sont rechargés

### Limitations

- Les changements dans `web_app.py` nécessitent un redémarrage du serveur (c'est normal)
- Les changements de structure de classes peuvent nécessiter une reconnexion au robot
- Les imports de nouveaux modules nécessitent un redémarrage

## Fonctionnalités

### 🔌 Connexion
- Connexion/déconnexion au robot via port série (COM3 par défaut)
- Indicateur de statut de connexion en temps réel

### 🎮 Contrôle
- **Lire Positions** : Lit et affiche les positions actuelles de tous les moteurs
- **Relâcher Moteurs** : Désactive le torque pour permettre le mouvement manuel
- **Verrouiller Moteurs** : Active le torque pour maintenir les positions
- **Position Home** : Envoie tous les moteurs à leur position home

### 🎚️ Contrôle Manuel (Sliders)
- Sliders pour contrôler chaque moteur individuellement (0-100%)
- Affichage des valeurs de calibration (gauche/droite)
- Affichage des positions brutes et normalisées
- Activation/désactivation du contrôle par sliders

### ⏺️ Enregistrement / Lecture
- **Enregistrer** : Enregistre les mouvements du robot
- **Stop** : Arrête l'enregistrement
- **Sauvegarder** : Sauvegarde l'enregistrement dans un fichier JSON
- **Charger** : Charge un enregistrement depuis un fichier
- **Lire** : Joue un enregistrement
- **Stop Lecture** : Arrête la lecture

### 🔧 Outils
- **Setup Moteurs** : Configuration des IDs des moteurs (nécessite un terminal séparé)
- **Calibrer** : Calibration automatique ou manuelle des moteurs
- **Trouver Port** : Trouve le port série du robot (nécessite un terminal séparé)

### 📐 Calibration
- **Automatique** : Trouve automatiquement les limites min/max de chaque moteur
- **Manuelle** : Enregistrement manuel de 3 positions (gauche, droite, milieu) pour chaque moteur

### 📋 Journal
- Affichage en temps réel des messages de log
- Historique des actions et erreurs

## Architecture

- **Backend** : Flask (Python) avec API REST
- **Frontend** : HTML5, CSS3, JavaScript vanilla
- **Design** : Interface moderne avec dégradés et animations

## Notes

- L'interface web conserve toutes les fonctionnalités de l'interface GUI originale
- Les fichiers d'enregistrement sont sauvegardés dans le répertoire courant
- La calibration est sauvegardée dans `calibration.json`
- L'interface est responsive et fonctionne sur desktop et tablette

