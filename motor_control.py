"""
Contrôle des moteurs - Lecture, écriture, verrouillage, etc.
"""

import time
from config import MOTOR_NAMES, MOTOR_IDS, HOME_POSITION


class MotorController:
    """Gère le contrôle des moteurs via LeRobot"""
    
    def __init__(self, motors_bus, log_callback=None):
        """
        motors_bus: Instance de FeetechMotorsBus
        log_callback: Fonction pour logger les messages (optionnel)
        """
        self.motors = motors_bus
        self.log = log_callback or (lambda msg: None)
    
    def read_positions(self, motor_names=None, normalize=False):
        """
        Lit les positions actuelles des moteurs.
        Retourne un dict {motor_name: position}
        """
        if motor_names is None:
            motor_names = MOTOR_NAMES
        
        # Essayer sync_read d'abord
        try:
            positions = self.motors.sync_read("Present_Position", motors=motor_names, normalize=normalize)
            return {name: int(positions.get(name, 0)) for name in motor_names}
        except Exception:
            # Fallback: lecture individuelle
            positions = {}
            for name in motor_names:
                try:
                    pos = self.motors.read("Present_Position", name, normalize=normalize)
                    positions[name] = int(pos)
                except Exception:
                    positions[name] = 0
                time.sleep(0.03)  # Pause pour éviter Overload
            return positions
    
    def read_present_positions_raw(self, motor_names=None):
        """Lit les positions actuelles (brutes 0-4095) pour une liste de moteurs."""
        return self.read_positions(motor_names, normalize=False)
    
    def write_positions(self, positions_dict, normalize=False):
        """
        Écrit les positions pour plusieurs moteurs.
        positions_dict: {motor_name: position}
        """
        try:
            self.motors.sync_write("Goal_Position", positions_dict, normalize=normalize)
        except Exception:
            # Fallback: écrire moteur par moteur
            for name, pos in positions_dict.items():
                self.motors.write("Goal_Position", name, int(pos), normalize=normalize)
                time.sleep(0.02)
    
    def set_torque(self, motor_names=None, enable=True):
        """
        Active ou désactive le torque sur les moteurs.
        motor_names: Liste de noms de moteurs (None = tous)
        enable: True pour activer, False pour désactiver
        """
        if motor_names is None:
            motor_names = MOTOR_NAMES
        
        torque_value = 1 if enable else 0
        
        try:
            self.motors.sync_write(
                "Torque_Enable",
                {name: torque_value for name in motor_names},
                normalize=False,
            )
        except Exception:
            # Fallback: écrire moteur par moteur
            for name in motor_names:
                self.motors.write("Torque_Enable", name, torque_value, normalize=False)
                time.sleep(0.02)
    
    def release_motors(self, motor_names=None):
        """Désactive le torque sur les moteurs"""
        self.set_torque(motor_names, enable=False)
        self.log("🔓 Moteurs relâchés - vous pouvez les bouger à la main")
    
    def hold_current_positions_and_lock(self, motor_names=None, positions_override=None):
        """
        Verrouille les moteurs SANS mouvement parasite:
        - lit Present_Position (sauf si positions_override est fourni)
        - écrit Goal_Position = Present_Position
        - active Torque_Enable
        
        positions_override: dict {motor_name: position} pour éviter de relire les positions
        """
        names = list(motor_names) if motor_names is not None else list(MOTOR_NAMES)
        
        try:
            if positions_override is not None:
                positions = {name: int(positions_override[name]) for name in names}
            else:
                positions = self.read_present_positions_raw(names)
            
            # 1) Fixer l'objectif à la position actuelle
            self.write_positions(positions, normalize=False)
            
            # 2) Activer le torque
            self.set_torque(names, enable=True)
            
            return True
        except Exception as e:
            self.log(f"❌ Erreur verrouillage (hold+lock): {e}")
            return False
    
    def lock_motors(self, motor_names=None):
        """Active le torque sur les moteurs en maintenant leur position actuelle"""
        if self.hold_current_positions_and_lock(motor_names):
            self.log("🔒 Moteurs verrouillés (sans bouger)")
    
    def go_home(self):
        """Envoie tous les moteurs à la position centrale (HOME_POSITION)"""
        try:
            # Éviter un "coup" au moment du verrouillage: définir d'abord l'objectif,
            # puis activer le torque
            self.write_positions(
                {name: HOME_POSITION for name in MOTOR_NAMES},
                normalize=False
            )
            self.set_torque(MOTOR_NAMES, enable=True)
            self.log(f"🏠 Retour à la position Home ({HOME_POSITION})")
        except Exception as e:
            self.log(f"❌ Erreur: {e}")

