# Spec & Plan d'Implémentation — Slice 1 : Vision Embarquée (Caméra Follower)

**Date** : 2026-10-30  
**Projet** : `C:\Users\Benjamin\Documents\Projets\Robot_Arm_SO-101`  
**Environnement Python** : `C:\Users\Benjamin\anaconda3\envs\lerobot\python.exe` (OpenCV `4.12.0` déjà installé)  
**Serveur Web actif** : Flask sur `http://127.0.0.1:5000` (`start_web.py`)

---

## 1. Objectif & Contexte

Une webcam USB est fixée au sommet du bras robotique **Follower** (configuration *Eye-in-Hand*).  
L'objectif final en plusieurs étapes est de détecter un objet et de le saisir automatiquement.  
**Cette Slice 1** implémente le socle de vision embarquée :
1. Acquérir le flux vidéo de la webcam côté backend Python via OpenCV dans un thread dédié (pour que l'Étape 2 de détection d'objet ait directement accès aux frames NumPy en mémoire).
2. Diffuser le flux en direct sur l'interface web via MJPEG (`multipart/x-mixed-replace`) dans une carte dédiée pleine largeur au-dessus de la section **🎮 Contrôle**.
3. Fournir les outils indispensables au contrôle manuel avec caméra embarquée :
   - Détection et sélection de l'index caméra (`0`, `1`, `2`...) + bouton **Activer / Arrêter**.
   - **Réticule de visée central** (croix + cercle central) dessiné sur l'image pour aligner la pince.
   - **Contrôles d'orientation** : Rotation 180° (si la caméra est collée la tête en bas) et Miroir horizontal (`flip_h`).
   - **Capture photo (Snapshot)** : sauvegarde instantanée de la frame courante dans `snapshots/snapshot_YYYYMMDD_HHMMSS.jpg` + téléchargement ou notification.
4. Intégrer l'arrêt de la caméra au bouton global **🛑 Tout Déconnecter** (`/api/disconnect-all`).

---

## 2. Architecture Cible

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         camera.py (CameraManager)                       │
│  - Thread daemon d'acquisition (cv2.VideoCapture + CAP_DSHOW Windows)   │
│  - Transformation en direct (rotate_180, flip_h)                        │
│  - Hook futur `frame_processor` (prêt pour Étape 2 : détection d'objet) │
│  - Dessin de l'overlay (réticule central + infos FPS/résolution)        │
│  - Encodage JPEG en mémoire (self._latest_jpeg, self._latest_raw_frame) │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              web_app.py                                 │
│  - GET  /api/camera/list       -> Liste les index de caméras dispo      │
│  - GET  /api/camera/status     -> État caméra & settings                │
│  - POST /api/camera/connect    -> Démarre CameraManager sur index N     │
│  - POST /api/camera/disconnect -> Arrête CameraManager                  │
│  - POST /api/camera/settings   -> Toggle crosshair, rotate_180, flip_h  │
│  - GET  /api/camera/stream     -> Flux Response MJPEG temps réel        │
│  - POST /api/camera/snapshot   -> Sauvegarde JPEG dans snapshots/       │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│             templates/index.html + style.css + app.js                   │
│  - Carte pleine largeur "📷 Vision Embarquée (Caméra Follower)"         │
│    placée juste au-dessus de la carte "🎮 Contrôle"                     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Plan d'Implémentation Détaillé (Fichier par Fichier)

### Tâche 1 : Créer le module [`camera.py`](file:///C:/Users/Benjamin/Documents/Projets/Robot_Arm_SO-101/camera.py)

Créer `C:\Users\Benjamin\Documents\Projets\Robot_Arm_SO-101\camera.py` avec la classe `CameraManager` :

#### Spécifications techniques de `CameraManager` :
- **Attributs d'état** :
  - `self.camera_index = None`
  - `self.cap = None`
  - `self.is_running = False`
  - `self._thread = None`
  - `self._stop_event = threading.Event()`
  - `self._lock = threading.Lock()`
  - `self._latest_frame = None` (image OpenCV BGR après orientation, **avant** réticule, pour que le snapshot ou la détection d'objet ait l'image propre)
  - `self._latest_display_jpeg = None` (bytes JPEG avec réticule pour le flux MJPEG)
  - `self.width = 640`, `self.height = 480`, `self.fps = 0.0`
  - **Settings** :
    - `self.show_crosshair = True` (activé par défaut)
    - `self.rotate_180 = False`
    - `self.flip_h = False`
  - **Hook Étape 2** : `self.frame_processor = None` (callable optionnel `fn(frame) -> frame` appelé dans la boucle avant le dessin du réticule).

- **Méthode `list_cameras(max_index=4)`** :
  - Sur Windows (`os.name == 'nt'`), utiliser `cv2.VideoCapture(idx, cv2.CAP_DSHOW)` pour éviter les blocages de 3 secondes par index inexistant.
  - Si `self.is_running` et `idx == self.camera_index`, ajouter directement la caméra active à la liste sans tenter de la rouvrir (pour ne pas interrompre le flux en cours !).
  - Pour chaque index qui s'ouvre (`cap.isOpened()`), lire `width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))` et `height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))`, puis `cap.release()`.
  - Retourner `[{'index': idx, 'label': f'Caméra {idx} ({width}x{height})', 'active': (idx == self.camera_index and self.is_running)}]`.

- **Méthode `start(index=0, width=640, height=480)`** :
  - Si déjà actif sur le même `index`, retourner `(True, None)`.
  - Si actif sur un autre index, appeler `self.stop()`.
  - Ouvrir `cv2.VideoCapture(int(index), cv2.CAP_DSHOW)` sous Windows (avec fallback `cv2.VideoCapture(int(index))` si `CAP_DSHOW` échoue).
  - Configurer `CAP_PROP_FRAME_WIDTH` (640), `CAP_PROP_FRAME_HEIGHT` (480), `CAP_PROP_FPS` (30).
  - Vérifier `cap.isOpened()` et faire une première lecture `ret, frame = cap.read()` pour valider que la webcam renvoie bien une image.
  - Lancer le thread daemon `_capture_loop()`.

- **Méthode `_capture_loop()`** :
  - Boucle tant que `not self._stop_event.is_set()` :
    1. `ret, frame = self.cap.read()` (si échec répété > 10 fois, sortir et fermer).
    2. Appliquer l'orientation :
       - Si `self.rotate_180`: `frame = cv2.rotate(frame, cv2.ROTATE_180)`
       - Si `self.flip_h`: `frame = cv2.flip(frame, 1)`
    3. Sauvegarder `self._latest_frame = frame.copy()` sous `self._lock`.
    4. Créer `display_frame = frame.copy()`.
    5. Si `self.frame_processor` est défini (Étape 2), appeler `display_frame = self.frame_processor(display_frame)`.
    6. Si `self.show_crosshair`, dessiner le réticule central (`_draw_crosshair(display_frame)`):
       - Croix centrale fine vert/cyan (`(0, 255, 180)`) avec un petit espace au centre, un cercle de rayon 25px, et 2 repères de largeur de pince.
    7. Encoder en JPEG : `ok, buf = cv2.imencode('.jpg', display_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])`.
    8. Stocker `self._latest_display_jpeg = buf.tobytes()` sous `self._lock`.
    9. `time.sleep(0.015)` (~30-40 FPS max sans saturer le CPU).

- **Méthode `stop()`** :
  - Signal `self._stop_event.set()`, `join(timeout=2.0)`, `cap.release()`, réinitialiser `is_running = False`, `camera_index = None`, `_latest_display_jpeg = None`.

- **Méthode `update_settings(show_crosshair=None, rotate_180=None, flip_h=None)`** :
  - Met à jour les booléens passés et retourne le dictionnaire `get_status()`.

- **Méthode `take_snapshot(save_dir="snapshots")`** :
  - Crée le dossier `snapshots/` s'il n'existe pas.
  - Récupère `self._latest_frame` sous `self._lock`.
  - Enregistre `snapshots/snapshot_YYYYMMDD_HHMMSS.jpg` avec `cv2.imwrite`.
  - Retourne `(True, filename, filepath)` ou `(False, error_msg, None)`.

- **Méthode `get_status()`** :
  - Retourne :
    ```python
    {
        'connected': self.is_running,
        'index': self.camera_index,
        'width': self.width,
        'height': self.height,
        'fps': round(self.fps, 1),
        'settings': {
            'show_crosshair': self.show_crosshair,
            'rotate_180': self.rotate_180,
            'flip_h': self.flip_h
        }
    }
    ```

---

### Tâche 2 : Intégrer `CameraManager` et les routes dans [`web_app.py`](file:///C:/Users/Benjamin/Documents/Projets/Robot_Arm_SO-101/web_app.py)

1. **Imports & Hot-Reload** :
   - Importer `Response` depuis `flask` : `from flask import Flask, render_template, jsonify, request, send_from_directory, Response`
   - Importer `from camera import CameraManager`
   - Ajouter `'camera': sys.modules['camera']` dans `_loaded_modules` et `'camera': Path('camera.py')` dans `_module_paths`, ainsi que le rechargement dans `reload_module()`.
2. **État global (`app_state`)** :
   - Ajouter `'camera_manager': CameraManager(log_fn=log)` dans `app_state`.
3. **Mise à jour de `/api/status` et `/api/disconnect-all`** :
   - Dans `get_status()` (`/api/status`), inclure `'camera': app_state['camera_manager'].get_status()`.
   - Dans `disconnect_all()` (`/api/disconnect-all`), appeler `app_state['camera_manager'].stop()` pour que le bouton **🛑 Tout Déconnecter** coupe aussi la caméra.
4. **Nouvelles routes API Caméra** :
   - `GET /api/camera/list` : appelle `app_state['camera_manager'].list_cameras()` et retourne `{'success': True, 'cameras': cameras, 'status': app_state['camera_manager'].get_status()}`.
   - `GET /api/camera/status` : retourne `{'success': True, **app_state['camera_manager'].get_status()}`.
   - `POST /api/camera/connect` : lit `index = int(data.get('index', 0))`, appelle `ok, err = app_state['camera_manager'].start(index=index)`, retourne `{'success': True, 'status': ...}` ou erreur `400`.
   - `POST /api/camera/disconnect` : appelle `app_state['camera_manager'].stop()`, retourne `{'success': True, 'status': ...}`.
   - `POST /api/camera/settings` : lit `show_crosshair`, `rotate_180`, `flip_h` dans `request.json`, met à jour `CameraManager` et retourne `{'success': True, 'status': ...}`.
   - `GET /api/camera/stream` : générateur MJPEG :
     ```python
     def generate():
         while app_state['camera_manager'].is_running:
             jpeg = app_state['camera_manager'].get_jpeg_frame()
             if jpeg:
                 yield (b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
             time.sleep(0.03)
     return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')
     ```
   - `POST /api/camera/snapshot` : appelle `ok, filename, _ = app_state['camera_manager'].take_snapshot()`, retourne `{'success': True, 'filename': filename, 'url': f'/snapshots/{filename}'}`.
   - `GET /snapshots/<path:filename>` : sert le fichier depuis le dossier `snapshots/` via `send_from_directory('snapshots', filename, as_attachment=True)`.

---

### Tâche 3 : Ajouter la carte Caméra dans [`templates/index.html`](file:///C:/Users/Benjamin/Documents/Projets/Robot_Arm_SO-101/templates/index.html)

Insérer juste au-dessus de `<!-- Section Contrôle -->` (ligne 98 de `templates/index.html`) une carte dédiée pleine largeur :

```html
<!-- Section Vision Embarquée (Caméra Follower) -->
<section class="card camera-card">
    <div class="card-header-flex">
        <h2>📷 Vision Embarquée (Caméra Follower)</h2>
        <div class="camera-header-badges">
            <span id="camera-status-badge" class="status-badge disconnected">Caméra inactive</span>
        </div>
    </div>

    <div class="camera-toolbar">
        <div class="camera-select-group">
            <label for="camera-index-select">Source vidéo :</label>
            <select id="camera-index-select" class="port-select">
                <option value="0">Caméra 0 (Par défaut)</option>
                <option value="1">Caméra 1</option>
                <option value="2">Caméra 2</option>
            </select>
            <button id="camera-detect-btn" class="btn btn-secondary btn-small" title="Rechercher les webcams branchées">↻ Détecter</button>
            <button id="camera-toggle-btn" class="btn btn-primary btn-small">▶ Activer Caméra</button>
        </div>

        <div class="camera-Quick-tools">
            <button id="camera-crosshair-btn" class="btn btn-secondary btn-small active-tool" title="Afficher/Masquer le réticule de visée central">🎯 Réticule</button>
            <button id="camera-rotate-btn" class="btn btn-secondary btn-small" title="Pivoter l'image de 180° (si webcam montée à l'envers)">🔄 Rotation 180°</button>
            <button id="camera-flip-btn" class="btn btn-secondary btn-small" title="Inverser gauche/droite (miroir)">↔️ Miroir</button>
            <button id="camera-snapshot-btn" class="btn btn-success btn-small" disabled title="Capturer et télécharger une photo">📸 Snapshot</button>
        </div>
    </div>

    <div class="camera-viewport-wrapper">
        <div id="camera-placeholder" class="camera-placeholder">
            <div class="camera-placeholder-icon">📷</div>
            <p>Flux vidéo inactif</p>
            <span>Sélectionnez votre webcam et cliquez sur « ▶ Activer Caméra » pour voir ce que voit le robot Follower.</span>
        </div>
        <img id="camera-stream-img" class="camera-stream-img" src="" alt="Flux caméra Follower" style="display: none;">
    </div>
</section>
```

---

### Tâche 4 : Styliser la carte dans [`static/css/style.css`](file:///C:/Users/Benjamin/Documents/Projets/Robot_Arm_SO-101/static/css/style.css)

Ajouter à la fin de `static/css/style.css` :
- `.camera-toolbar` : flexbox responsive alignant la sélection de caméra à gauche et les boutons d'outils (`🎯 Réticule`, `🔄 Rotation 180°`, `↔️ Miroir`, `📸 Snapshot`) à droite.
- `.btn.active-tool` : bordure lumineuse cyan/bleue (`#3498db`) et fond accentué pour indiquer clairement quels toggles (Réticule, Rotation 180°, Miroir) sont actifs.
- `.camera-viewport-wrapper` : conteneur 16:9 / 4:3 centré (`max-width: 800px`, `min-height: 380px`, `margin: 0 auto`, fond noir `#0d1117`, `border-radius: 10px`, `overflow: hidden`, bordure subtile).
- `.camera-stream-img` : `width: 100%`, `max-height: 520px`, `object-fit: contain`, `display: block`.
- `.camera-placeholder` : centré verticalement et horizontalement avec icône et texte explicatif.

---

### Tâche 5 : Logique Frontend dans [`static/js/app.js`](file:///C:/Users/Benjamin/Documents/Projets/Robot_Arm_SO-101/static/js/app.js)

1. **État global JS** :
   - Ajouter `cameraState = { connected: false, index: 0, settings: { show_crosshair: true, rotate_180: false, flip_h: false } }`.
2. **Initialisation (`initializeUI`)** :
   - Brancher les écouteurs sur `#camera-detect-btn` (`detectCameras()`), `#camera-toggle-btn` (`toggleCamera()`), `#camera-crosshair-btn` (`toggleCameraSetting('show_crosshair')`), `#camera-rotate-btn` (`toggleCameraSetting('rotate_180')`), `#camera-flip-btn` (`toggleCameraSetting('flip_h')`), et `#camera-snapshot-btn` (`takeCameraSnapshot()`).
   - Appeler `detectCameras()` au chargement de la page.
3. **Fonctions JS à implémenter** :
   - `detectCameras()` : appelle `GET /api/camera/list`, remplit `#camera-index-select` avec les caméras détectées (ou garde `Caméra 0`, `Caméra 1` par défaut si aucune n'est retournée) et met à jour l'UI.
   - `toggleCamera()` :
     - Si `cameraState.connected` est `false` : appelle `POST /api/camera/connect` avec l'index sélectionné, puis affiche `<img id="camera-stream-img" src="/api/camera/stream?t=...">`.
     - Si `cameraState.connected` est `true` : vide `img.src = ""` avant d'appeler `POST /api/camera/disconnect` pour libérer immédiatement la connexion HTTP MJPEG.
   - `toggleCameraSetting(key)` : inverse `cameraState.settings[key]`, appelle `POST /api/camera/settings`, et met à jour la classe `.active-tool` du bouton correspondant.
   - `takeCameraSnapshot()` : appelle `POST /api/camera/snapshot`, affiche un log de confirmation et déclenche le téléchargement automatique du cliché via un lien `<a download>` vers `data.url`.
   - `updateCameraUIFromStatus(camData)` : appelée depuis `updateUnifiedUIFromStatus(data)` (et après chaque action caméra) pour synchroniser le badge `En direct (Caméra X • 640×480)`, le bouton `⏹ Arrêter Caméra` / `▶ Activer Caméra`, l'affichage de `<img>` vs `#camera-placeholder`, et l'état des boutons toggles.

---

## 4. Vérification & Tests d'Acceptation

Une fois le code écrit :
1. **Test unitaire / fumée Python** :
   - Vérifier que `import camera` et `CameraManager` s'importent sans erreur avec `C:\Users\Benjamin\anaconda3\envs\lerobot\python.exe`.
   - Vérifier les endpoints `GET /api/camera/list`, `GET /api/camera/status`, `POST /api/camera/settings` via une requête HTTP locale sur `http://127.0.0.1:5000`.
2. **Test matériel en direct (Webcam)** :
   - Tester `POST /api/camera/connect` (`{"index": 0}`).
   - Vérifier que le flux `/api/camera/stream` renvoie bien des frames `image/jpeg` et que `POST /api/camera/snapshot` crée bien une image dans `snapshots/`.
   - Vérifier que `POST /api/disconnect-all` coupe bien la caméra en même temps que les bras.
