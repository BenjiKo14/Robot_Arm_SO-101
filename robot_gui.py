"""
Interface Graphique pour bras robotique SO-ARM101
Utilise LeRobot / Feetech SDK de HuggingFace
https://huggingface.co/docs/lerobot/so101
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import time
import subprocess
import sys
import inspect

from config import (
    MOTOR_NAMES, MOTOR_IDS, LEROBOT_AVAILABLE,
    FeetechMotorsBus, Motor, MotorNormMode, HOME_POSITIONS
)
from normalization import normalize_position, denormalize_position, detect_wrap_around
from motor_control import MotorController
from calibration import CalibrationManager
from recording import RecordingManager
import widgets


class LeRobotGUI:
    """Interface graphique utilisant LeRobot pour SO-ARM101"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("SO-ARM101 - LeRobot Controller")
        self.root.geometry("900x700")
        
        self.motors = None
        self.is_connected = False
        
        # Managers
        self.motor_controller = None
        self.calibration_manager = None
        self.recording_manager = None
        
        # État pour le contrôle par sliders
        self._pending_positions = {}
        self._position_sender_running = False
        self._torque_enabled_for_sliders = set()
        
        # Créer les widgets
        self.create_widgets()
        
        if not LEROBOT_AVAILABLE:
            self.log("❌ LeRobot non disponible!")
            self.log("   Installez avec: conda activate lerobot && pip install lerobot[feetech]")
        else:
            self.verify_lerobot_api()
    
    def log(self, message):
        """Ajoute un message dans la zone de log"""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update()
    
    def verify_lerobot_api(self):
        """Vérifie la structure exacte de l'API LeRobot"""
        if not LEROBOT_AVAILABLE:
            return
        
        self.log("\n🔍 Vérification de l'API LeRobot...")
        
        import inspect
        methods = [m for m in dir(FeetechMotorsBus) if not m.startswith('_')]
        self.log(f"Méthodes FeetechMotorsBus: {', '.join(methods[:15])}...")
        
        calib_methods = [m for m in methods if 'calib' in m.lower() or 'set' in m.lower() or 'write' in m.lower()]
        if calib_methods:
            self.log(f"Méthodes de calibration trouvées: {', '.join(calib_methods)}")
        else:
            self.log("⚠️ Aucune méthode de calibration évidente trouvée")
    
    def get_normalized_position(self, motor_name, raw_pos):
        """Normalise une position brute en utilisant la calibration stockée."""
        if not self.calibration_manager or motor_name not in self.calibration_manager.calibrations:
            return None
        
        calib = self.calibration_manager.calibrations[motor_name]
        pos_left = calib.get('pos_left')
        pos_right = calib.get('pos_right')
        pos_center = calib.get('pos_center')
        
        if pos_left is None or pos_right is None or pos_center is None:
            return None
        
        return normalize_position(raw_pos, pos_left, pos_right, pos_center)
    
    def get_raw_position(self, motor_name, normalized):
        """Dénormalise une valeur en utilisant la calibration stockée."""
        if not self.calibration_manager or motor_name not in self.calibration_manager.calibrations:
            return None
        
        calib = self.calibration_manager.calibrations[motor_name]
        pos_left = calib.get('pos_left')
        pos_right = calib.get('pos_right')
        pos_center = calib.get('pos_center')
        
        if pos_left is None or pos_right is None or pos_center is None:
            return None
        
        result = denormalize_position(normalized, pos_left, pos_right, pos_center)
        return result
    
    def create_widgets(self):
        """Crée tous les widgets de l'interface"""
        # Initialiser slider_enabled AVANT de créer les sliders pour éviter les erreurs
        self.slider_enabled = tk.BooleanVar(value=False)
        
        # Connexion
        self.port_var = tk.StringVar(value="COM3")
        _, self.btn_connect, self.status_label = widgets.create_connection_frame(
            self.root, self.port_var, self.connect
        )
        
        # Contrôle
        widgets.create_control_frame(self.root, {
            'read_positions': self.read_positions,
            'release_motors': self.release_motors,
            'lock_motors': self.lock_motors,
            'go_home': self.go_home
        })
        
        # Enregistrement
        _, self.sample_interval, self.btn_record, self.btn_stop_record, \
        self.btn_play, self.btn_stop_play, self.record_status = widgets.create_recording_frame(
            self.root, {
                'start_recording': self.start_recording,
                'stop_recording': self.stop_recording,
                'save_recording': self.save_recording,
                'load_recording': self.load_recording,
                'play_recording': self.play_recording,
                'stop_playback': self.stop_playback
            }
        )
        
        # Outils
        widgets.create_tools_frame(self.root, {
            'setup_motors': self.run_setup_motors,
            'calibrate': self.run_calibrate,
            'find_port': self.run_find_port
        })
        
        # Sliders - passer slider_enabled existant au lieu de le créer
        _, _, self.motor_sliders, self.motor_labels, \
        self.motor_calib_labels = widgets.create_sliders_frame(
            self.root,
            self.on_slider_change,
            self.on_slider_toggle,
            self.update_slider_calibration_display,
            self.slider_enabled  # Passer le BooleanVar existant
        )
        
        # Log - créer d'abord le widget, puis appeler les callbacks
        _, self.log_text = widgets.create_log_frame(self.root, log_callback=None)
        
        # Maintenant que log_text existe, afficher le message de bienvenue
        self.log("🤖 SO-ARM101 Controller avec LeRobot")
        self.log("   Documentation: https://huggingface.co/docs/lerobot/so101")
        if LEROBOT_AVAILABLE:
            self.log("✓ LeRobot disponible")
        else:
            self.log("❌ LeRobot non disponible")
            self.log("")
            self.log("Pour installer:")
            self.log("  1. conda activate lerobot")
            self.log("  2. pip install lerobot[feetech]")
            self.log("  3. python robot_gui.py")
    
    def connect(self):
        """Connexion/Déconnexion du robot"""
        if not self.is_connected:
            if not LEROBOT_AVAILABLE:
                messagebox.showerror("Erreur", "LeRobot non installé!\n\nInstallez avec:\nconda activate lerobot\npip install lerobot[feetech]")
                return
            
            try:
                port = self.port_var.get()
                self.log(f"🔌 Connexion sur {port}...")
                
                # Configuration des moteurs
                motor_config = {
                    name: Motor(id=motor_id, model="sts3215", norm_mode=MotorNormMode.RANGE_0_100)
                    for name, motor_id in zip(MOTOR_NAMES, MOTOR_IDS)
                }
                
                self.motors = FeetechMotorsBus(port=port, motors=motor_config)
                self.motors.connect()
                
                self.is_connected = True
                self.btn_connect.config(text="Déconnecter")
                self.status_label.config(text=f"Connecté sur {port}", foreground="green")
                self.log(f"✓ Connecté via LeRobot FeetechMotorsBus")
                
                # Initialiser les managers
                self.motor_controller = MotorController(self.motors, self.log)
                self.calibration_manager = CalibrationManager(self.motors, self.log)
                self.recording_manager = RecordingManager(self.motors, self.log)
                
                # Charger les calibrations
                self.calibration_manager.load_calibration_from_file()
                self.update_slider_calibration_display()
                
                # Lire les positions initiales
                self.read_positions()
                
            except Exception as e:
                messagebox.showerror("Erreur", f"Connexion impossible:\n{e}")
                self.log(f"❌ Erreur: {e}")
        else:
            # Déconnexion
            if self.motors:
                try:
                    self.motors.disconnect()
                except:
                    pass
            self.motors = None
            self.motor_controller = None
            self.calibration_manager = None
            self.recording_manager = None
            self.is_connected = False
            self.btn_connect.config(text="Connecter")
            self.status_label.config(text="Déconnecté", foreground="red")
            self.log("✓ Déconnecté")
    
    def read_positions(self):
        """Lit et affiche les positions actuelles"""
        if not self.is_connected:
            messagebox.showwarning("Attention", "Connectez-vous d'abord au robot")
            return
        
        try:
            positions = self.motor_controller.read_positions(normalize=False)
            
            self.log("📊 Positions actuelles:")
            for name in MOTOR_NAMES:
                raw_pos = int(positions.get(name, 0))
                
                normalized = self.get_normalized_position(name, raw_pos)
                if normalized is not None:
                    pct = int(normalized * 100)
                    self.log(f"   {name}: {raw_pos} ({pct}%)")
                else:
                    pct = int((raw_pos / 4095) * 100)
                    self.log(f"   {name}: {raw_pos} (non calibré)")
                
                # Mettre à jour les sliders et labels
                try:
                    self.motor_sliders[name].set(pct)
                    self.motor_labels[name].config(text=f"{pct}%")
                    if name in self.motor_calib_labels:
                        self.motor_calib_labels[name]['raw'].config(text=str(raw_pos))
                except:
                    pass
                    
        except Exception as e:
            import traceback
            error_msg = f"❌ Erreur lecture: {e}\n{traceback.format_exc()}"
            self.log(error_msg)
            messagebox.showerror("Erreur de lecture", f"Impossible de lire les positions:\n{e}")
    
    def release_motors(self):
        """Désactive le torque sur tous les moteurs"""
        if not self.is_connected:
            return
        self.motor_controller.release_motors()
    
    def lock_motors(self):
        """Active le torque sur tous les moteurs"""
        if not self.is_connected:
            return
        self.motor_controller.lock_motors()
    
    def go_home(self):
        """Envoie tous les moteurs à la position centrale"""
        if not self.is_connected:
            return
        self.motor_controller.go_home()
    
    def on_slider_change(self, motor_name, value):
        """Callback quand un slider change"""
        if not self.slider_enabled.get() or not self.is_connected:
            return
        
        try:
            pct = float(value)
            normalized = pct / 100.0
            
            self.motor_labels[motor_name].config(text=f"{int(pct)}%")
            
            # Conversion directe slider → valeurs brutes pour TOUS les moteurs
            # Utilise les valeurs de calibration (pos_left, pos_right) comme range
            raw_pos = self._convert_slider_to_raw_direct(motor_name, normalized)
            
            if motor_name in self.motor_calib_labels:
                self.motor_calib_labels[motor_name]['raw'].config(text=str(raw_pos))
            
            self._pending_positions[motor_name] = raw_pos
            self._start_position_sender()
            
        except Exception as e:
            print(f"Erreur slider {motor_name}: {e}")
    
    def on_slider_toggle(self):
        """Callback quand on active/désactive le contrôle par sliders"""
        if self.slider_enabled.get():
            # Activer les sliders sans vérification ni déplacement automatique
            self._init_slider_state()
        else:
            # Désactiver les sliders
            self._position_sender_running = False
            self._torque_enabled_for_sliders = set()
    
    def _start_position_sender(self):
        """Démarre le thread d'envoi des positions"""
        if not hasattr(self, '_position_sender_running'):
            self._position_sender_running = False
        if not hasattr(self, '_pending_positions'):
            self._pending_positions = {}
        if not hasattr(self, '_torque_enabled_for_sliders'):
            self._torque_enabled_for_sliders = set()
        
        if self._position_sender_running:
            return
        
        self._position_sender_running = True
        
        def send_positions():
            overload_cooldown = {}
            
            while self._position_sender_running and self.slider_enabled.get():
                if not self._pending_positions:
                    time.sleep(0.02)
                    continue
                
                positions_to_send = self._pending_positions.copy()
                self._pending_positions.clear()
                
                current_time = time.time()
                
                for motor_name, raw_pos in positions_to_send.items():
                    if motor_name in overload_cooldown:
                        if current_time < overload_cooldown[motor_name]:
                            continue
                        else:
                            del overload_cooldown[motor_name]
                    
                    try:
                        if motor_name not in self._torque_enabled_for_sliders:
                            self.motors.write("Torque_Enable", motor_name, 1, normalize=False)
                            self._torque_enabled_for_sliders.add(motor_name)
                            time.sleep(0.01)
                        
                        # Vérifier si le moteur est inversé (détection basée sur test de mouvement)
                        final_pos = self._apply_motor_inversion(motor_name, raw_pos)
                        
                        self.motors.write("Goal_Position", motor_name, final_pos, normalize=False)
                        
                    except Exception as e:
                        error_msg = str(e)
                        if "Overload" in error_msg:
                            if motor_name not in overload_cooldown:
                                print(f"⚠️ {motor_name}: Surcharge détectée - pause 2s")
                                overload_cooldown[motor_name] = current_time + 2.0
                        else:
                            print(f"Erreur envoi {motor_name}: {e}")
                    
                    time.sleep(0.02)
                
                time.sleep(0.03)
            
            self._position_sender_running = False
        
        threading.Thread(target=send_positions, daemon=True).start()
    
    def _init_slider_state(self):
        """Initialise les variables d'état pour les sliders"""
        self._pending_positions = {}
        self._position_sender_running = False
        self._torque_enabled_for_sliders = set()
    
    def _check_motors_in_calibrated_range(self):
        """Vérifie si tous les moteurs sont dans leur range calibré"""
        if not self.calibration_manager or not self.is_connected:
            return True
        
        try:
            positions = self.motor_controller.read_positions(normalize=False)
            motors_out_of_range = []
            
            for motor_name in MOTOR_NAMES:
                if motor_name not in self.calibration_manager.calibrations:
                    continue
                
                calib = self.calibration_manager.calibrations[motor_name]
                pos_left = calib.get('pos_left')
                pos_right = calib.get('pos_right')
                current_pos = positions.get(motor_name, 0)
                
                if pos_left is None or pos_right is None:
                    continue
                
                # Calculer les limites du range (avec marge de sécurité de 10%)
                min_pos = min(pos_left, pos_right)
                max_pos = max(pos_left, pos_right)
                range_size = max_pos - min_pos
                margin = int(range_size * 0.1)
                
                in_range = not (current_pos < (min_pos - margin) or current_pos > (max_pos + margin))
                
                # Vérifier si la position est dans le range avec marge
                if not in_range:
                    motors_out_of_range.append(motor_name)
                    self.log(f"⚠️ {motor_name}: Position {current_pos} hors range [{min_pos}, {max_pos}]")
            
            result = len(motors_out_of_range) == 0
            return result
            
        except Exception as e:
            self.log(f"❌ Erreur vérification range: {e}")
            return True  # En cas d'erreur, on laisse passer
    
    def _convert_slider_to_raw_direct(self, motor_name, normalized):
        """
        Convertit directement le slider (0.0-1.0) en valeurs brutes
        en utilisant les valeurs de calibration comme range.
        Même logique simple que test_gripper.py pour tous les moteurs.
        """
        # Valeurs spéciales mesurées pour le gripper
        if motor_name == "gripper":
            GRIPPER_CLOSED = 2029  # Position fermée réelle mesurée
            GRIPPER_OPEN = 3204    # Position ouverte réelle mesurée
            return int(GRIPPER_CLOSED + (normalized * (GRIPPER_OPEN - GRIPPER_CLOSED)))
        
        # Pour les autres moteurs, utiliser les valeurs de calibration
        if not self.calibration_manager or motor_name not in self.calibration_manager.calibrations:
            # Pas de calibration : conversion linéaire simple 0-4095
            return int(normalized * 4095)
        
        calib = self.calibration_manager.calibrations[motor_name]
        pos_left = calib.get('pos_left')
        pos_right = calib.get('pos_right')
        
        if pos_left is None or pos_right is None:
            # Calibration incomplète : conversion linéaire simple
            return int(normalized * 4095)
        
        # Conversion linéaire directe : slider 0% = pos_left, slider 100% = pos_right
        # Normalisé 0.0 → pos_left, normalisé 1.0 → pos_right
        return int(pos_left + (normalized * (pos_right - pos_left)))
    
    def _apply_motor_inversion(self, motor_name, raw_pos):
        """
        Applique l'inversion pour les moteurs qui ont un comportement inversé.
        Certains moteurs Feetech ont leur firmware/câblage inversé.
        
        NOTE: Si un moteur est calibré manuellement avec ses positions inversées
        (pos_left > pos_right pour un mouvement croissant), alors la calibration
        gère déjà l'inversion et il ne faut PAS l'ajouter ici (double inversion).
        """
        # Liste des moteurs connus pour être inversés (détectés via test de mouvement)
        # ET qui n'ont PAS été calibrés avec inversion
        INVERTED_MOTORS = {
            # "gripper" était ici, mais retiré car la calibration manuelle
            # a déjà inversé les valeurs (pos_left=3930 > pos_right=1034)
        }
        
        if motor_name in INVERTED_MOTORS:
            inverted_pos = 4095 - raw_pos
            self.log(f"⚙️ {motor_name}: Inversion {raw_pos} → {inverted_pos}")
            return inverted_pos
        
        return raw_pos
    
    def _move_to_calibrated_centers(self):
        """Déplace tous les moteurs vers leurs positions centrales calibrées"""
        if not self.calibration_manager or not self.is_connected:
            return
        
        try:
            self.log("🎯 Déplacement vers les positions centrales calibrées...")
            
            target_positions = {}
            for motor_name in MOTOR_NAMES:
                if motor_name not in self.calibration_manager.calibrations:
                    continue
                
                calib = self.calibration_manager.calibrations[motor_name]
                pos_center = calib.get('pos_center')
                
                if pos_center is not None:
                    # Appliquer l'inversion si nécessaire
                    target_positions[motor_name] = self._apply_motor_inversion(motor_name, pos_center)
            
            if target_positions:
                # Activer le torque
                self.motor_controller.set_torque(list(target_positions.keys()), enable=True)
                time.sleep(0.05)
                
                # Envoyer les positions cibles
                self.motor_controller.write_positions(target_positions, normalize=False)
                
                self.log(f"✓ {len(target_positions)} moteurs déplacés vers leur centre calibré")
                time.sleep(0.5)  # Attendre que les moteurs se déplacent
            
        except Exception as e:
            self.log(f"❌ Erreur déplacement vers centres: {e}")
    
    def update_slider_calibration_display(self):
        """Met à jour l'affichage des valeurs de calibration sur les sliders"""
        if not self.calibration_manager:
            return
        
        for motor_name in MOTOR_NAMES:
            if motor_name not in self.motor_calib_labels:
                continue
            
            labels = self.motor_calib_labels[motor_name]
            
            if motor_name in self.calibration_manager.calibrations:
                calib = self.calibration_manager.calibrations[motor_name]
                pos_left = calib.get('pos_left')
                pos_right = calib.get('pos_right')
                
                if pos_left is not None:
                    labels['left'].config(text=str(pos_left))
                else:
                    labels['left'].config(text="---")
                
                if pos_right is not None:
                    labels['right'].config(text=str(pos_right))
                else:
                    labels['right'].config(text="---")
            else:
                labels['left'].config(text="---")
                labels['right'].config(text="---")
        
        self.log("↻ Affichage calibration des sliders mis à jour")
    
    def start_recording(self):
        """Démarre l'enregistrement des positions"""
        if not self.is_connected:
            messagebox.showwarning("Attention", "Connectez-vous d'abord")
            return
        
        self.recording_manager.start_recording(
            self.sample_interval.get(),
            self.release_motors
        )
        self.btn_record.config(state=tk.DISABLED)
        self.btn_stop_record.config(state=tk.NORMAL)
    
    def stop_recording(self):
        """Arrête l'enregistrement"""
        self.recording_manager.stop_recording(self.lock_motors)
        self.btn_record.config(state=tk.NORMAL)
        self.btn_stop_record.config(state=tk.DISABLED)
    
    def save_recording(self):
        """Sauvegarde l'enregistrement"""
        self.recording_manager.save_recording(self.sample_interval.get())
    
    def load_recording(self):
        """Charge un enregistrement"""
        self.recording_manager.load_recording()
    
    def play_recording(self):
        """Joue l'enregistrement"""
        if not self.is_connected:
            messagebox.showwarning("Attention", "Connectez-vous d'abord")
            return
        
        def status_update(frame_num, total):
            self.record_status.config(text=f"Frame {frame_num}/{total}")
        
        self.recording_manager.play_recording(status_update, self.lock_motors)
        self.btn_play.config(state=tk.DISABLED)
        self.btn_stop_play.config(state=tk.NORMAL)
    
    def stop_playback(self):
        """Arrête la lecture"""
        self.recording_manager.stop_playback()
        self.btn_play.config(state=tk.NORMAL)
        self.btn_stop_play.config(state=tk.DISABLED)
    
    def run_lerobot_command(self, cmd):
        """Exécute une commande LeRobot dans un terminal"""
        self.log(f"🔧 Exécution: {cmd}")
        
        def run():
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                self.root.after(0, lambda: self.log(result.stdout))
                if result.stderr:
                    self.root.after(0, lambda: self.log(f"⚠️ {result.stderr}"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"❌ Erreur: {e}"))
        
        threading.Thread(target=run, daemon=True).start()
    
    def run_setup_motors(self):
        """Lance le setup motors via subprocess"""
        if self.is_connected:
            if not messagebox.askyesno("Déconnexion requise", 
                                       "Le port est actuellement utilisé par la GUI.\n\n"
                                       "Voulez-vous déconnecter maintenant pour configurer les IDs ?"):
                return
            self.connect()
        
        port = self.port_var.get()
        
        msg = (
            "Le setup des moteurs va se lancer dans une fenêtre de terminal.\n\n"
            "Suivez les instructions à l'écran:\n"
            "1. Connectez UN SEUL moteur à la fois\n"
            "2. Appuyez sur Entrée quand demandé\n"
            "3. Le script configurera automatiquement l'ID et le baudrate\n\n"
            "Continuer ?"
        )
        
        if not messagebox.askyesno("Setup Motors", msg):
            return
        
        cmd = f'lerobot-setup-motors --robot.type=so101_follower --robot.port={port}'
        
        if sys.platform == 'win32':
            subprocess.Popen(['cmd', '/c', 'start', 'cmd', '/k', cmd])
        else:
            subprocess.Popen(['x-terminal-emulator', '-e', cmd])
        
        self.log(f"🔧 Setup motors lancé dans un terminal séparé")
        self.log(f"   Commande: {cmd}")
    
    def run_calibrate(self):
        """Ouvre une fenêtre de calibration intégrée"""
        if not self.is_connected:
            messagebox.showwarning("Attention", "Connectez-vous d'abord au robot")
            return
        
        calib_window = tk.Toplevel(self.root)
        calib_window.title("Calibration des Moteurs")
        calib_window.geometry("700x700")
        
        notebook = ttk.Notebook(calib_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        auto_frame = ttk.Frame(notebook)
        notebook.add(auto_frame, text="🔧 Automatique")
        
        manual_frame = ttk.Frame(notebook)
        notebook.add(manual_frame, text="✋ Manuelle")
        
        self._setup_auto_calibration(auto_frame)
        self._setup_manual_calibration(manual_frame)
    
    def _setup_auto_calibration(self, parent):
        """Configure l'onglet de calibration automatique"""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(header_frame, text="Calibration Automatique", 
                 font=("Arial", 12, "bold")).pack()
        
        ttk.Label(header_frame, 
                 text="Cette fonction va trouver les limites min/max de chaque moteur.\n"
                      "Assurez-vous que le robot a de l'espace pour bouger !",
                 justify=tk.CENTER).pack(pady=5)
        
        frame_motors = ttk.LabelFrame(parent, text="Moteurs à calibrer", padding=10)
        frame_motors.pack(fill=tk.X, padx=10, pady=5)
        
        motor_vars = {}
        motors_grid = ttk.Frame(frame_motors)
        motors_grid.pack()
        
        for i, (name, motor_id) in enumerate(zip(MOTOR_NAMES, MOTOR_IDS)):
            var = tk.BooleanVar(value=True)
            motor_vars[name] = var
            row = i // 2
            col = (i % 2) * 2
            ttk.Checkbutton(motors_grid, text=f"{name} (ID {motor_id})", 
                           variable=var).grid(row=row, column=col, sticky=tk.W, padx=10, pady=2)
        
        log_frame = ttk.LabelFrame(parent, text="Progression", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        calib_log = scrolledtext.ScrolledText(log_frame, height=10, wrap=tk.WORD)
        calib_log.pack(fill=tk.BOTH, expand=True)
        
        def log_calib(msg):
            calib_log.insert(tk.END, msg + "\n")
            calib_log.see(tk.END)
            parent.update()
        
        def start_calibration():
            motors_to_calib = [name for name, var in motor_vars.items() if var.get()]
            
            if not motors_to_calib:
                messagebox.showwarning("Attention", "Sélectionnez au moins un moteur")
                return
        
            btn_start.config(state=tk.DISABLED)
            log_calib("=" * 50)
            log_calib("Démarrage de la calibration...")
            
            def calib_thread():
                log_calib("\n🔍 Vérification de la connexion des moteurs...")
                responding_motors = []
                for motor_name in motors_to_calib:
                    motor_id = MOTOR_IDS[MOTOR_NAMES.index(motor_name)]
                    try:
                        pos = self.motors.read("Present_Position", motor_name, normalize=False, num_retry=2)
                        log_calib(f"  ✓ {motor_name} (ID {motor_id}) répond - position: {pos}")
                        responding_motors.append(motor_name)
                    except Exception as e:
                        log_calib(f"  ❌ {motor_name} (ID {motor_id}) ne répond pas: {e}")
                
                if not responding_motors:
                    log_calib("\n❌ Aucun moteur ne répond! Vérifiez les connexions.")
                    parent.after(0, lambda: btn_start.config(state=tk.NORMAL))
                    return
                
                log_calib(f"\n✓ {len(responding_motors)}/{len(motors_to_calib)} moteurs répondent")
                log_calib("=" * 50)
                
                success_count = 0
                for motor_name in responding_motors:
                    motor_id = MOTOR_IDS[MOTOR_NAMES.index(motor_name)]
                    if self.calibration_manager.calibrate_motor_auto(motor_name, motor_id, log_calib):
                        success_count += 1
                
                parent.after(0, lambda: log_calib(f"\n{'='*50}"))
                parent.after(0, lambda: log_calib(f"✓ Calibration terminée: {success_count}/{len(responding_motors)} moteurs"))
                parent.after(0, lambda: btn_start.config(state=tk.NORMAL))
            
            threading.Thread(target=calib_thread, daemon=True).start()
        
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10, padx=10)
        
        btn_start = ttk.Button(btn_frame, text="▶ Démarrer la Calibration", command=start_calibration)
        btn_start.pack(side=tk.LEFT, padx=5)
    
    def _setup_manual_calibration(self, parent):
        """Configure l'onglet de calibration manuelle - CALIBRATION 3 POINTS"""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(header_frame, text="Calibration Manuelle - 3 Points", 
                 font=("Arial", 12, "bold")).pack()
        
        ttk.Label(header_frame, 
                 text="Cette calibration gère les servos dont le range passe par 0 (wrap-around).\n"
                      "Pour chaque moteur, vous devez enregistrer 3 positions: GAUCHE, DROITE, et MILIEU.",
                 justify=tk.CENTER, foreground="blue").pack(pady=5)
        
        main_frame = ttk.Frame(parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=5)
        
        btn_release_all = ttk.Button(control_frame, text="🔓 Relâcher TOUS les moteurs")
        btn_release_all.pack(side=tk.LEFT, padx=5)
        
        btn_lock_all = ttk.Button(control_frame, text="🔒 Verrouiller TOUS")
        btn_lock_all.pack(side=tk.LEFT, padx=5)
        
        canvas = tk.Canvas(main_frame, height=350)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        calibration_data = {}
        motor_widgets = {}
        
        for motor_name in MOTOR_NAMES:
            calibration_data[motor_name] = {
                'pos_left': None,
                'pos_right': None,
                'pos_center': None,
                'is_done': False
            }
        
        position_update_running = [False]
        
        def update_all_positions():
            if not self.is_connected:
                position_update_running[0] = False
                return
            
            for motor_name in MOTOR_NAMES:
                try:
                    pos = self.motors.read("Present_Position", motor_name, normalize=False, num_retry=1)
                    pos_int = int(pos)
                    motor_widgets[motor_name]['pos_label'].config(text=str(pos_int))
                except:
                    pass
                time.sleep(0.02)
            
            if position_update_running[0]:
                parent.after(150, update_all_positions)
        
        def start_position_update():
            if not position_update_running[0]:
                position_update_running[0] = True
                update_all_positions()
        
        def stop_position_update():
            position_update_running[0] = False
        
        def create_motor_calibration_row(motor_name, motor_id):
            motor_frame = ttk.LabelFrame(scrollable_frame, text=f"{motor_name} (ID {motor_id})", padding=5)
            motor_frame.pack(fill=tk.X, padx=5, pady=3)
            
            row1 = ttk.Frame(motor_frame)
            row1.pack(fill=tk.X, pady=2)
            
            ttk.Label(row1, text="Position actuelle:", width=15).pack(side=tk.LEFT)
            pos_label = ttk.Label(row1, text="---", width=6, font=("Consolas", 10, "bold"))
            pos_label.pack(side=tk.LEFT, padx=5)
            
            ttk.Label(row1, text="  ").pack(side=tk.LEFT)
            
            btn_left = ttk.Button(row1, text="◀ Gauche", width=10)
            btn_left.pack(side=tk.LEFT, padx=2)
            
            btn_right = ttk.Button(row1, text="Droite ▶", width=10)
            btn_right.pack(side=tk.LEFT, padx=2)
            
            btn_center = ttk.Button(row1, text="● Milieu", width=10)
            btn_center.pack(side=tk.LEFT, padx=2)
            
            btn_reset = ttk.Button(row1, text="↺ Reset", width=8)
            btn_reset.pack(side=tk.LEFT, padx=5)
            
            row2 = ttk.Frame(motor_frame)
            row2.pack(fill=tk.X, pady=2)
            
            ttk.Label(row2, text="Gauche:", width=8).pack(side=tk.LEFT)
            left_label = ttk.Label(row2, text="---", width=6, foreground="blue", font=("Consolas", 10))
            left_label.pack(side=tk.LEFT)
            
            ttk.Label(row2, text="  Droite:", width=8).pack(side=tk.LEFT)
            right_label = ttk.Label(row2, text="---", width=6, foreground="red", font=("Consolas", 10))
            right_label.pack(side=tk.LEFT)
            
            ttk.Label(row2, text="  Milieu:", width=8).pack(side=tk.LEFT)
            center_label = ttk.Label(row2, text="---", width=6, foreground="green", font=("Consolas", 10))
            center_label.pack(side=tk.LEFT)
            
            ttk.Label(row2, text="  ").pack(side=tk.LEFT)
            status_label = ttk.Label(row2, text="⏳ En attente", foreground="gray")
            status_label.pack(side=tk.LEFT, padx=10)
            
            motor_widgets[motor_name] = {
                'pos_label': pos_label,
                'left_label': left_label,
                'right_label': right_label,
                'center_label': center_label,
                'status_label': status_label,
                'btn_left': btn_left,
                'btn_right': btn_right,
                'btn_center': btn_center,
                'btn_reset': btn_reset
            }
            
            def record_position(position_type):
                try:
                    pos = self.motors.read("Present_Position", motor_name, normalize=False, num_retry=2)
                    pos_int = int(pos)
                except Exception as e:
                    messagebox.showerror("Erreur", f"Impossible de lire {motor_name}: {e}")
                    return
                
                calibration_data[motor_name][f'pos_{position_type}'] = pos_int
                
                if position_type == 'left':
                    left_label.config(text=str(pos_int))
                elif position_type == 'right':
                    right_label.config(text=str(pos_int))
                elif position_type == 'center':
                    center_label.config(text=str(pos_int))
                
                check_calibration_complete(motor_name)
            
            def check_calibration_complete(mname):
                data = calibration_data[mname]
                if data['pos_left'] is not None and data['pos_right'] is not None and data['pos_center'] is not None:
                    data['is_done'] = True
                    motor_widgets[mname]['status_label'].config(text="✓ Calibré", foreground="green")
                    
                    mid = MOTOR_IDS[MOTOR_NAMES.index(mname)]
                    self.calibration_manager.calibrations[mname] = {
                        'motor_id': mid,
                        'pos_left': data['pos_left'],
                        'pos_right': data['pos_right'],
                        'pos_center': data['pos_center']
                    }
                    
                    self.calibration_manager.save_calibration_to_file()
                    
                    all_done = all(calibration_data[n]['is_done'] for n in MOTOR_NAMES)
                    if all_done:
                        messagebox.showinfo("Succès", "Tous les moteurs sont calibrés! 🎉")
                else:
                    missing = []
                    if data['pos_left'] is None:
                        missing.append("Gauche")
                    if data['pos_right'] is None:
                        missing.append("Droite")
                    if data['pos_center'] is None:
                        missing.append("Milieu")
                    motor_widgets[mname]['status_label'].config(
                        text=f"Manque: {', '.join(missing)}", 
                        foreground="orange"
                    )
            
            def reset_motor_calibration():
                calibration_data[motor_name] = {
                    'pos_left': None,
                    'pos_right': None,
                    'pos_center': None,
                    'is_done': False
                }
                left_label.config(text="---")
                right_label.config(text="---")
                center_label.config(text="---")
                status_label.config(text="⏳ En attente", foreground="gray")
                
                if motor_name in self.calibration_manager.calibrations:
                    del self.calibration_manager.calibrations[motor_name]
            
            btn_left.config(command=lambda: record_position('left'))
            btn_right.config(command=lambda: record_position('right'))
            btn_center.config(command=lambda: record_position('center'))
            btn_reset.config(command=reset_motor_calibration)
            
            if motor_name in self.calibration_manager.calibrations:
                existing = self.calibration_manager.calibrations[motor_name]
                if 'pos_left' in existing and existing['pos_left'] is not None:
                    calibration_data[motor_name]['pos_left'] = existing['pos_left']
                    left_label.config(text=str(existing['pos_left']))
                if 'pos_right' in existing and existing['pos_right'] is not None:
                    calibration_data[motor_name]['pos_right'] = existing['pos_right']
                    right_label.config(text=str(existing['pos_right']))
                if 'pos_center' in existing and existing['pos_center'] is not None:
                    calibration_data[motor_name]['pos_center'] = existing['pos_center']
                    center_label.config(text=str(existing['pos_center']))
                check_calibration_complete(motor_name)
        
        for motor_name, motor_id in zip(MOTOR_NAMES, MOTOR_IDS):
            create_motor_calibration_row(motor_name, motor_id)
        
        def release_all():
            try:
                self.motor_controller.release_motors()
                self.log("🔓 Tous les moteurs relâchés")
                start_position_update()
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de relâcher: {e}")
        
        def lock_all():
            stop_position_update()
            try:
                self.motor_controller.lock_motors()
                self.log("🔒 Tous les moteurs verrouillés")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible de verrouiller: {e}")
        
        btn_release_all.config(command=release_all)
        btn_lock_all.config(command=lock_all)
    
    def run_find_port(self):
        """Lance lerobot-find-port"""
        self.run_lerobot_command("lerobot-find-port")


def main():
    root = tk.Tk()
    app = LeRobotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
