"""
Gestion de l'enregistrement et de la lecture de mouvements
"""

import json
import time
import threading
from tkinter import filedialog, messagebox

from config import MOTOR_NAMES, MOTOR_IDS


class RecordingManager:
    """Gère l'enregistrement et la lecture de mouvements"""
    
    def __init__(self, motors_bus, log_callback=None):
        """
        motors_bus: Instance de FeetechMotorsBus
        log_callback: Fonction pour logger les messages
        """
        self.motors = motors_bus
        self.log = log_callback or (lambda msg: None)
        
        self.is_recording = False
        self.is_playing = False
        self.recorded_frames = []
        self.sample_interval_ms = 100
    
    def start_recording(self, sample_interval_ms=100, release_callback=None):
        """
        Démarre l'enregistrement des positions.
        release_callback: Fonction à appeler pour relâcher les moteurs avant l'enregistrement
        """
        self.is_recording = True
        self.recorded_frames = []
        self.sample_interval_ms = sample_interval_ms
        
        if release_callback:
            release_callback()
        
        self.log("⏺ Enregistrement démarré - Bougez le robot!")
        
        def record_thread():
            t0 = time.monotonic()
            interval = sample_interval_ms / 1000.0
            
            while self.is_recording:
                try:
                    # Lire les valeurs brutes sans normalisation
                    positions = self.motors.sync_read("Present_Position", motors=MOTOR_NAMES, normalize=False)
                    t = time.monotonic() - t0
                    
                    # Convertir les noms en IDs pour le format JSON
                    frame = {
                        "t": t,
                        "pos": {str(MOTOR_IDS[i]): int(positions.get(name, 0)) 
                               for i, name in enumerate(MOTOR_NAMES)}
                    }
                    self.recorded_frames.append(frame)
                    
                except Exception:
                    pass
                
                time.sleep(interval)
            
            self.log(f"⏹ Enregistrement terminé: {len(self.recorded_frames)} frames")
        
        threading.Thread(target=record_thread, daemon=True).start()
    
    def stop_recording(self, lock_callback=None):
        """Arrête l'enregistrement"""
        self.is_recording = False
        if lock_callback:
            lock_callback()
    
    def save_recording(self, sample_interval_ms=100):
        """Sauvegarde l'enregistrement dans un fichier JSON"""
        if not self.recorded_frames:
            messagebox.showwarning("Attention", "Aucun enregistrement à sauvegarder")
            return
        
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile="recording.json"
        )
        
        if path:
            data = {
                "name": "recording",
                "sample_period_s": sample_interval_ms / 1000.0,
                "servo_ids": MOTOR_IDS,
                "frames": self.recorded_frames
            }
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.log(f"💾 Sauvegardé: {path}")
    
    def load_recording(self):
        """Charge un enregistrement depuis un fichier JSON"""
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json")]
        )
        
        if path:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.recorded_frames = data.get('frames', [])
            self.log(f"📂 Chargé: {path} ({len(self.recorded_frames)} frames)")
    
    def play_recording(self, status_update_callback=None, lock_callback=None):
        """
        Joue l'enregistrement.
        status_update_callback: Fonction(frame_num, total_frames) pour mettre à jour le statut
        lock_callback: Fonction pour verrouiller les moteurs avant la lecture
        """
        if not self.recorded_frames:
            messagebox.showwarning("Attention", "Aucun enregistrement à lire")
            return
        
        self.is_playing = True
        
        if lock_callback:
            lock_callback()
        
        self.log(f"▶ Lecture de {len(self.recorded_frames)} frames...")
        
        def play_thread():
            frames = self.recorded_frames
            t0 = time.monotonic()
            base_t = frames[0]['t'] if frames else 0
            
            for i, frame in enumerate(frames):
                if not self.is_playing:
                    break
                
                # Attendre le bon moment
                target_time = t0 + (frame['t'] - base_t)
                wait_time = target_time - time.monotonic()
                if wait_time > 0:
                    time.sleep(wait_time)
                
                # Écrire les positions (valeurs brutes)
                positions_dict = {
                    MOTOR_NAMES[i]: int(frame['pos'].get(str(MOTOR_IDS[i]), 2048))
                    for i in range(len(MOTOR_NAMES))
                }
                
                try:
                    self.motors.sync_write("Goal_Position", positions_dict, normalize=False)
                except Exception as e:
                    self.log(f"❌ Erreur: {e}")
                    break
                
                # Mise à jour du statut toutes les 10 frames
                if i % 10 == 0 and status_update_callback:
                    status_update_callback(i + 1, len(frames))
            
            self.is_playing = False
            self.log("✓ Lecture terminée")
        
        threading.Thread(target=play_thread, daemon=True).start()
    
    def stop_playback(self):
        """Arrête la lecture"""
        self.is_playing = False

