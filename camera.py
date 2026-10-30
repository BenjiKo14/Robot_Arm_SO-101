import os
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
import cv2

class CameraManager:
    def __init__(self, log_fn=None):
        self.log_fn = log_fn or print
        self.camera_index = None
        self.cap = None
        self.is_running = False
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        
        # Frames en mémoire
        self._latest_raw_frame = None  # Image après orientation (sans réticule) pour snapshots/IA
        self._latest_display_jpeg = None  # Bytes JPEG pour le flux MJPEG
        
        self.width = 640
        self.height = 480
        self.fps = 0.0
        
        # Réglages
        self.show_crosshair = True
        self.rotate_180 = False
        self.flip_h = False
        
        # Hook pour l'étape 2 (ex: IA / détection d'objets)
        self.frame_processor = None

    def log(self, msg):
        try:
            self.log_fn(msg)
        except Exception:
            print(msg)

    def list_cameras(self, max_index=4):
        """Détecte rapidement les webcams branchées sous Windows/Linux"""
        cameras = []
        is_windows = (os.name == 'nt')
        backend = cv2.CAP_DSHOW if is_windows else cv2.CAP_ANY

        for idx in range(max_index):
            # Si cette caméra est déjà ouverte et en cours d'utilisation, on l'ajoute directement
            if self.is_running and self.camera_index == idx:
                cameras.append({
                    'index': idx,
                    'label': f"Caméra {idx} ({self.width}x{self.height})",
                    'active': True
                })
                continue

            try:
                cap = cv2.VideoCapture(idx, backend)
                if cap.isOpened():
                    # Petite lecture pour vérifier qu'elle renvoie bien des données
                    ret, _ = cap.read()
                    if ret:
                        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        cameras.append({
                            'index': idx,
                            'label': f"Caméra {idx} ({w}x{h})",
                            'active': False
                        })
                    cap.release()
            except Exception as e:
                pass

        return cameras

    def start(self, index=0, width=640, height=480):
        """Démarre l'acquisition sur l'index spécifié"""
        with self._lock:
            if self.is_running:
                if self.camera_index == index:
                    return True, None
                self._stop_unlocked()

            self.log(f"📷 Ouverture de la caméra {index}...")
            is_windows = (os.name == 'nt')
            backend = cv2.CAP_DSHOW if is_windows else cv2.CAP_ANY

            cap = cv2.VideoCapture(int(index), backend)
            if not cap.isOpened() and is_windows:
                # Fallback sans CAP_DSHOW au cas où
                cap = cv2.VideoCapture(int(index))

            if not cap.isOpened():
                self.log(f"❌ Impossible d'ouvrir la caméra {index}")
                return False, f"Impossible d'ouvrir la caméra {index}"

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, 30)

            # Test de lecture
            ret, frame = cap.read()
            if not ret or frame is None:
                cap.release()
                self.log(f"❌ La caméra {index} ne renvoie pas d'image")
                return False, f"La caméra {index} ne renvoie pas d'image"

            self.cap = cap
            self.camera_index = index
            self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or width
            self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or height
            self.is_running = True
            self._stop_event.clear()

            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            self.log(f"✅ Caméra {index} active ({self.width}x{self.height})")
            return True, None

    def _draw_crosshair(self, frame):
        """Dessine un réticule central ergonomique pour aligner la pince du robot"""
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2

        color = (0, 255, 180)  # Cyan / Vert clair
        secondary_color = (0, 180, 255) # Jaune / Orange
        thickness = 1

        # Cercle central
        cv2.circle(frame, (cx, cy), 20, color, thickness, cv2.LINE_AA)
        cv2.circle(frame, (cx, cy), 3, (0, 0, 255), -1, cv2.LINE_AA) # Point central rouge

        # Lignes avec espace central
        gap = 25
        line_len = 50
        # Horizontal gauche & droite
        cv2.line(frame, (cx - gap - line_len, cy), (cx - gap, cy), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (cx + gap, cy), (cx + gap + line_len, cy), color, thickness, cv2.LINE_AA)
        # Vertical haut & bas
        cv2.line(frame, (cx, cy - gap - line_len), (cx, cy - gap), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (cx, cy + gap), (cx, cy + gap + line_len), color, thickness, cv2.LINE_AA)

        # Repères d'alignement pince (largeur d'ouverture approximative)
        gripper_w = 40
        cv2.line(frame, (cx - gripper_w, cy - 10), (cx - gripper_w, cy + 10), secondary_color, 1, cv2.LINE_AA)
        cv2.line(frame, (cx + gripper_w, cy - 10), (cx + gripper_w, cy + 10), secondary_color, 1, cv2.LINE_AA)

    def _capture_loop(self):
        """Boucle d'acquisition continue dans un thread dédié"""
        fail_count = 0
        last_time = time.time()
        frame_count = 0

        while not self._stop_event.is_set():
            if not self.cap or not self.cap.isOpened():
                break

            ret, frame = self.cap.read()
            if not ret or frame is None:
                fail_count += 1
                if fail_count > 20:
                    self.log(f"⚠️ Perte du signal vidéo de la caméra {self.camera_index}")
                    break
                time.sleep(0.05)
                continue

            fail_count = 0

            # 1. Orientation
            if self.rotate_180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            if self.flip_h:
                frame = cv2.flip(frame, 1)

            # Sauvegarder la frame propre pour IA et Snapshot
            with self._lock:
                self._latest_raw_frame = frame.copy()

            # 2. Préparation pour affichage
            display_frame = frame.copy()

            # Hook étape 2 : détection d'objets si défini
            if self.frame_processor:
                try:
                    display_frame = self.frame_processor(display_frame)
                except Exception as e:
                    pass

            # Réticule
            if self.show_crosshair:
                self._draw_crosshair(display_frame)

            # 3. Encodage JPEG
            ok, buf = cv2.imencode('.jpg', display_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with self._lock:
                    self._latest_display_jpeg = buf.tobytes()

            # Calcul FPS
            frame_count += 1
            now = time.time()
            if now - last_time >= 1.0:
                self.fps = frame_count / (now - last_time)
                frame_count = 0
                last_time = now

            time.sleep(0.015) # Limiter à ~30-40 FPS pour soulager le CPU

        with self._lock:
            self._stop_unlocked()

    def _stop_unlocked(self):
        """Arrêt interne sans reprendre le lock"""
        self._stop_event.set()
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.is_running = False
        self.camera_index = None
        self._latest_display_jpeg = None
        self.fps = 0.0

    def stop(self):
        """Arrête la caméra proprement"""
        with self._lock:
            self.log("⏹ Arrêt de la caméra...")
            self._stop_unlocked()
            if self._thread and self._thread.is_alive():
                # Attente brève sans bloquer
                pass
            self.log("✓ Caméra arrêtée")
            return True

    def get_jpeg_frame(self):
        """Retourne la dernière image encodée en JPEG"""
        with self._lock:
            return self._latest_display_jpeg

    def update_settings(self, show_crosshair=None, rotate_180=None, flip_h=None):
        """Met à jour les paramètres d'affichage à chaud"""
        with self._lock:
            if show_crosshair is not None:
                self.show_crosshair = bool(show_crosshair)
            if rotate_180 is not None:
                self.rotate_180 = bool(rotate_180)
            if flip_h is not None:
                self.flip_h = bool(flip_h)
            return self.get_status()

    def take_snapshot(self, save_dir="snapshots"):
        """Prend une capture d'écran haute qualité de l'image courante"""
        with self._lock:
            if not self.is_running or self._latest_raw_frame is None:
                return False, "Caméra non active ou aucune image reçue", None
            frame = self._latest_raw_frame.copy()

        try:
            dir_path = Path(save_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            filename = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            filepath = dir_path / filename
            cv2.imwrite(str(filepath), frame)
            self.log(f"📸 Snapshot sauvegardé : {filename}")
            return True, filename, str(filepath)
        except Exception as e:
            self.log(f"❌ Erreur snapshot: {e}")
            return False, str(e), None

    def get_status(self):
        """Retourne l'état complet du gestionnaire de caméra"""
        return {
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
