"""
Configuration et constantes pour le contrôleur SO-ARM101
"""

import sys

# Essayer d'importer LeRobot
LEROBOT_AVAILABLE = False
FeetechMotorsBus = None
Motor = None
MotorNormMode = None
MotorCalibration = None
import_error_msg = ""

try:
    # Le bon chemin pour LeRobot
    from lerobot.motors.feetech import FeetechMotorsBus
    from lerobot.motors.motors_bus import Motor, MotorNormMode
    # Essayer d'importer MotorCalibration depuis le bon endroit
    try:
        from lerobot.common.robot_devices.motors.utils import MotorCalibration
    except ImportError:
        # Fallback vers l'ancien chemin si le nouveau ne fonctionne pas
        from lerobot.motors.motors_bus import MotorCalibration
    LEROBOT_AVAILABLE = True
except ImportError as e:
    import_error_msg = str(e)
    print(f"⚠️ LeRobot non trouvé. Erreur: {e}")
    print("\nVérifiez que vous êtes dans l'environnement conda:")
    print("  conda activate lerobot")
    print("  python robot_gui.py")


# Configuration SO-101 follower
MOTOR_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
MOTOR_IDS = [1, 2, 3, 4, 5, 6]

# Fichier de calibration par défaut
DEFAULT_CALIBRATION_FILE = "calibration.json"

# Position maximale des encodeurs
MAX_POS = 4096

# Position Home par défaut
HOME_POSITION = 2048

