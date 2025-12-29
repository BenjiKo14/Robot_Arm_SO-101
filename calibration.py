"""
Gestion de la calibration des moteurs (automatique et manuelle)
"""

import json
import os
import inspect
import time
import threading
from tkinter import ttk, scrolledtext, messagebox

from config import (
    MOTOR_NAMES, MOTOR_IDS, DEFAULT_CALIBRATION_FILE,
    LEROBOT_AVAILABLE, MotorCalibration
)
from normalization import detect_wrap_around


class CalibrationManager:
    """Gère la calibration des moteurs"""
    
    def __init__(self, motors_bus, log_callback=None):
        """
        motors_bus: Instance de FeetechMotorsBus
        log_callback: Fonction pour logger les messages
        """
        self.motors = motors_bus
        self.log = log_callback or (lambda msg: None)
        
        # Stockage des calibrations (motor_name -> {motor_id, pos_left, pos_right, pos_center})
        self.calibrations = {}
        self.calibration_file = DEFAULT_CALIBRATION_FILE
    
    def create_motor_calibration(self, motor_id, min_pos, max_pos):
        """Crée un objet MotorCalibration avec la bonne signature (adaptatif)"""
        if not LEROBOT_AVAILABLE:
            raise RuntimeError("LeRobot non disponible")
        
        sig = inspect.signature(MotorCalibration.__init__)
        params = list(sig.parameters.keys())
        
        # Essayer différentes signatures possibles
        try:
            # Tentative 1: Signature avec motor_id, min_position, max_position
            if 'motor_id' in params and 'min_position' in params and 'max_position' in params:
                return MotorCalibration(
                    motor_id=motor_id,
                    drive_mode=0,
                    homing_offset=0,
                    min_position=min_pos,
                    max_position=max_pos
                )
        except Exception:
            pass
        
        try:
            # Tentative 2: Signature avec id, min_position, max_position
            if 'id' in params and 'min_position' in params and 'max_position' in params:
                return MotorCalibration(
                    id=motor_id,
                    drive_mode=0,
                    homing_offset=0,
                    min_position=min_pos,
                    max_position=max_pos
                )
        except Exception:
            pass
        
        try:
            # Tentative 3: Signature avec start_pos et end_pos
            if 'start_pos' in params and 'end_pos' in params:
                kwargs = {
                    'start_pos': min_pos,
                    'end_pos': max_pos
                }
                if 'motor_id' in params:
                    kwargs['motor_id'] = motor_id
                elif 'id' in params:
                    kwargs['id'] = motor_id
                if 'drive_mode' in params:
                    kwargs['drive_mode'] = 0
                if 'homing_offset' in params:
                    kwargs['homing_offset'] = 0
                return MotorCalibration(**kwargs)
        except Exception:
            pass
        
        try:
            # Tentative 4: Signature avec range_min et range_max
            if 'range_min' in params and 'range_max' in params:
                kwargs = {
                    'range_min': min_pos,
                    'range_max': max_pos
                }
                if 'motor_id' in params:
                    kwargs['motor_id'] = motor_id
                elif 'id' in params:
                    kwargs['id'] = motor_id
                if 'drive_mode' in params:
                    kwargs['drive_mode'] = 0
                if 'homing_offset' in params:
                    kwargs['homing_offset'] = 0
                return MotorCalibration(**kwargs)
        except Exception:
            pass
        
        # Si tout échoue, lever une erreur
        raise ValueError(
            f"Impossible de créer MotorCalibration avec motor_id={motor_id}, min={min_pos}, max={max_pos}.\n"
            f"Paramètres disponibles: {params}"
        )
    
    def save_motor_calibration(self, motor_name, calibration, save_to_file=True):
        """Sauvegarde une calibration pour un moteur (méthode adaptative)"""
        motor_id = MOTOR_IDS[MOTOR_NAMES.index(motor_name)]
        
        try:
            # Extraire les valeurs de calibration pour sauvegarde dans JSON
            min_pos = getattr(calibration, 'min_position', None)
            max_pos = getattr(calibration, 'max_position', None)
            
            # Si les attributs n'existent pas, essayer d'autres noms possibles
            if min_pos is None:
                min_pos = getattr(calibration, 'start_pos', None)
            if max_pos is None:
                max_pos = getattr(calibration, 'end_pos', None)
            if min_pos is None:
                min_pos = getattr(calibration, 'range_min', None)
            if max_pos is None:
                max_pos = getattr(calibration, 'range_max', None)
            
            # Sauvegarder dans le dictionnaire de calibrations
            if min_pos is not None and max_pos is not None:
                self.calibrations[motor_name] = {
                    'motor_id': motor_id,
                    'min_position': int(min_pos),
                    'max_position': int(max_pos)
                }
                if save_to_file:
                    self.save_calibration_to_file()
        except Exception as e:
            self.log(f"⚠️ Erreur extraction calibration pour {motor_name}: {e}")
        
        # Essayer différentes méthodes de sauvegarde sur le bus
        try:
            if hasattr(self.motors, 'set_calibration'):
                self.motors.set_calibration(calibration)
                return True
        except (AttributeError, Exception):
            pass
        
        try:
            if hasattr(self.motors, 'write_calibration'):
                self.motors.write_calibration({motor_name: calibration})
                return True
        except (AttributeError, Exception):
            pass
        
        try:
            if hasattr(self.motors, 'motors') and motor_name in self.motors.motors:
                self.motors.motors[motor_name].calibration = calibration
                return True
        except (AttributeError, Exception):
            pass
        
        try:
            if hasattr(self.motors, 'update_calibration'):
                self.motors.update_calibration(motor_name, calibration)
                return True
        except (AttributeError, Exception):
            pass
        
        # Si tout échoue, juste logger un avertissement
        self.log(f"⚠️ Impossible de sauvegarder la calibration sur le bus pour {motor_name}")
        return False
    
    def save_calibration_to_file(self):
        """Sauvegarde toutes les calibrations dans un fichier JSON"""
        try:
            with open(self.calibration_file, 'w', encoding='utf-8') as f:
                json.dump(self.calibrations, f, indent=2, ensure_ascii=False)
            self.log(f"💾 Calibrations sauvegardées dans {self.calibration_file}")
        except Exception as e:
            self.log(f"⚠️ Erreur sauvegarde calibrations: {e}")
    
    def load_calibration_from_file(self):
        """Charge les calibrations depuis le fichier JSON (format 3 points)"""
        if not os.path.exists(self.calibration_file):
            self.log(f"📂 Aucun fichier de calibration trouvé ({self.calibration_file})")
            return False
        
        try:
            with open(self.calibration_file, 'r', encoding='utf-8') as f:
                loaded_calibrations = json.load(f)
            
            if not loaded_calibrations:
                self.log("📂 Fichier de calibration vide")
                return False
            
            self.log(f"📂 Chargement des calibrations depuis {self.calibration_file}...")
            loaded_count = 0
            
            for motor_name, calib_data in loaded_calibrations.items():
                if motor_name not in MOTOR_NAMES:
                    continue
                
                motor_id = calib_data.get('motor_id')
                
                # Nouveau format 3 points
                pos_left = calib_data.get('pos_left')
                pos_right = calib_data.get('pos_right')
                pos_center = calib_data.get('pos_center')
                
                # Compatibilité ancien format (min_position, max_position)
                if pos_left is None and 'min_position' in calib_data:
                    pos_left = calib_data['min_position']
                if pos_right is None and 'max_position' in calib_data:
                    pos_right = calib_data['max_position']
                if pos_center is None and pos_left is not None and pos_right is not None:
                    # Calculer le centre si absent (ancien format)
                    pos_center = (pos_left + pos_right) // 2
                
                if motor_id is None or pos_left is None or pos_right is None or pos_center is None:
                    self.log(f"⚠️ Données de calibration incomplètes pour {motor_name}")
                    continue
                
                try:
                    # Stocker dans self.calibrations (format 3 points)
                    self.calibrations[motor_name] = {
                        'motor_id': motor_id,
                        'pos_left': pos_left,
                        'pos_right': pos_right,
                        'pos_center': pos_center
                    }
                    
                    # Déterminer si wrap-around pour l'affichage
                    wraps = detect_wrap_around(pos_left, pos_right, pos_center)
                    wrap_str = " (wrap)" if wraps else ""
                    
                    loaded_count += 1
                    self.log(f"  ✓ {motor_name}: L={pos_left}, R={pos_right}, C={pos_center}{wrap_str}")
                    
                except Exception as e:
                    self.log(f"  ❌ Erreur chargement calibration {motor_name}: {e}")
            
            if loaded_count > 0:
                self.log(f"✓ {loaded_count} calibration(s) chargée(s)")
                return True
            else:
                self.log("⚠️ Aucune calibration valide chargée")
                return False
                
        except Exception as e:
            self.log(f"❌ Erreur chargement fichier calibration: {e}")
            import traceback
            self.log(traceback.format_exc())
            return False
    
    def calibrate_motor_auto(self, motor_name, motor_id, log_callback):
        """Calibre un moteur automatiquement en trouvant MIN et MAX"""
        log_callback(f"\n🔧 Calibration de {motor_name} (ID {motor_id})...")
        
        try:
            # 1. Activer le torque
            log_callback(f"  → Activation du torque...")
            self.motors.write("Torque_Enable", motor_name, True, normalize=False)
            time.sleep(0.1)
            
            # 2. Position actuelle
            present_pos = self.motors.read("Present_Position", motor_name, normalize=False)
            log_callback(f"  Position actuelle: {present_pos}")
            
            # 3. Trouver MIN
            log_callback(f"  → Recherche MIN...")
            self.motors.write("Goal_Position", motor_name, 0, normalize=False)
            time.sleep(1.0)
            
            positions_history = []
            for _ in range(10):
                pos = self.motors.read("Present_Position", motor_name, normalize=False)
                positions_history.append(pos)
                time.sleep(0.1)
            
            calib_min = int(sum(positions_history[-5:]) / 5)
            log_callback(f"  ✓ MIN détecté: {calib_min}")
            
            # 4. Trouver MAX
            log_callback(f"  → Recherche MAX...")
            self.motors.write("Goal_Position", motor_name, 4095, normalize=False)
            time.sleep(1.0)
            
            positions_history = []
            for _ in range(10):
                pos = self.motors.read("Present_Position", motor_name, normalize=False)
                positions_history.append(pos)
                time.sleep(0.1)
            
            calib_max = int(sum(positions_history[-5:]) / 5)
            log_callback(f"  ✓ MAX détecté: {calib_max}")
            
            # 5. Validation
            if calib_max <= calib_min:
                log_callback(f"  ❌ Erreur: MAX ({calib_max}) <= MIN ({calib_min})")
                return False
            
            # 6. Créer et sauvegarder la calibration
            calibration = self.create_motor_calibration(motor_id, calib_min, calib_max)
            log_callback(f"  → Sauvegarde de la calibration...")
            self.save_motor_calibration(motor_name, calibration)
            log_callback(f"  ✓ Calibration sauvegardée: [{calib_min}, {calib_max}]")
            
            # 7. Retour à la position centrale
            center = (calib_min + calib_max) // 2
            self.motors.write("Goal_Position", motor_name, center, normalize=False)
            time.sleep(0.5)
            
            return True
            
        except Exception as e:
            import traceback
            log_callback(f"  ❌ Erreur: {e}")
            log_callback(traceback.format_exc())
            return False

