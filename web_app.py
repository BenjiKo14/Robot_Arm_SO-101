"""
Application Web pour le contrôle du bras robotique SO-ARM101
Remplace l'interface GUI Tkinter par une interface web moderne
Support du rechargement à chaud des modules Python
"""

from flask import Flask, render_template, jsonify, request, send_from_directory, Response
from flask_cors import CORS
import threading
import time
import subprocess
import sys
import os
import json
import importlib
import importlib.util
from pathlib import Path
from datetime import datetime

# Pour la détection des ports série
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# Import initial des modules
from config import (
    MOTOR_NAMES, MOTOR_IDS, LEROBOT_AVAILABLE,
    FeetechMotorsBus, Motor, MotorNormMode, HOME_POSITIONS
)
from normalization import normalize_position, denormalize_position, detect_wrap_around
from motor_control import MotorController
from calibration import CalibrationManager
from recording import RecordingManager
from camera import CameraManager

# Dictionnaire pour stocker les modules chargés et leurs chemins
_loaded_modules = {
    'config': sys.modules['config'],
    'normalization': sys.modules['normalization'],
    'motor_control': sys.modules['motor_control'],
    'calibration': sys.modules['calibration'],
    'recording': sys.modules['recording'],
    'camera': sys.modules['camera'],
}

# Chemins des fichiers de modules
_module_paths = {
    'config': Path('config.py'),
    'normalization': Path('normalization.py'),
    'motor_control': Path('motor_control.py'),
    'calibration': Path('calibration.py'),
    'recording': Path('recording.py'),
    'camera': Path('camera.py'),
}

# Timestamps de dernière modification
_module_timestamps = {}

# Constantes protocole STS3215 (Feetech)
STS_REG_ID = 0x05
STS_REG_BAUD = 0x06
STS_REG_TORQUE_ENABLE = 0x28
STS_REG_LOCK = 0x37

STS_INST_PING = 0x01
STS_INST_READ = 0x02
STS_INST_WRITE = 0x03

STS_DEFAULT_BAUD = 1000000

CLONE_LEADER_CALIB_FILE = "calibration_leader.json"
CLONE_FOLLOWER_CALIB_FILE = "calibration_follower.json"

# region agent log
_DEBUG_LOG_PATH = r"c:\Users\Benjamin\Documents\Robot_Arm_SO-101\.cursor\debug.log"
def _dbg(hypothesisId, location, message, data=None, runId="run1"):
    try:
        payload = {
            "sessionId": "debug-session",
            "runId": runId,
            "hypothesisId": hypothesisId,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# endregion

def _sts_checksum(data):
    return (~sum(data)) & 0xFF

def _sts_send_packet(ser, servo_id, instruction, params=None):
    if params is None:
        params = []
    length = len(params) + 2
    packet = [0xFF, 0xFF, servo_id, length, instruction] + params
    checksum = _sts_checksum(packet[2:])
    packet.append(checksum)
    ser.reset_input_buffer()
    ser.write(bytes(packet))
    time.sleep(0.02)
    return ser.read(100)

def _sts_ping(ser, servo_id):
    for _ in range(3):
        response = _sts_send_packet(ser, servo_id, STS_INST_PING, [])
        if len(response) >= 6 and response[0] == 0xFF and response[1] == 0xFF and response[2] == servo_id:
            return True
        time.sleep(0.01)
    return False

def _sts_write_byte(ser, servo_id, address, value):
    _sts_send_packet(ser, servo_id, STS_INST_WRITE, [address, value & 0xFF])
    time.sleep(0.02)

def _sts_change_id(ser, old_id, new_id):
    if old_id == new_id:
        return True, None
    _sts_write_byte(ser, old_id, STS_REG_LOCK, 0)
    _sts_write_byte(ser, old_id, STS_REG_TORQUE_ENABLE, 0)
    _sts_write_byte(ser, old_id, STS_REG_ID, new_id)
    time.sleep(0.2)
    _sts_write_byte(ser, new_id, STS_REG_LOCK, 1)
    time.sleep(0.05)
    if _sts_ping(ser, new_id):
        return True, None
    if _sts_ping(ser, old_id):
        return False, "Le servo répond toujours à l'ancien ID"
    return False, "Le servo ne répond pas au nouvel ID"

def reload_module(module_name):
    """Recharge un module Python à chaud"""
    if module_name not in _loaded_modules:
        return False
    
    try:
        module = _loaded_modules[module_name]
        importlib.reload(module)
        
        # Mettre à jour les références globales
        if module_name == 'config':
            globals()['MOTOR_NAMES'] = module.MOTOR_NAMES
            globals()['MOTOR_IDS'] = module.MOTOR_IDS
            globals()['LEROBOT_AVAILABLE'] = module.LEROBOT_AVAILABLE
            globals()['FeetechMotorsBus'] = module.FeetechMotorsBus
            globals()['Motor'] = module.Motor
            globals()['MotorNormMode'] = module.MotorNormMode
            globals()['HOME_POSITIONS'] = module.HOME_POSITIONS
        elif module_name == 'normalization':
            globals()['normalize_position'] = module.normalize_position
            globals()['denormalize_position'] = module.denormalize_position
            globals()['detect_wrap_around'] = module.detect_wrap_around
        elif module_name == 'motor_control':
            globals()['MotorController'] = module.MotorController
        elif module_name == 'calibration':
            globals()['CalibrationManager'] = module.CalibrationManager
        elif module_name == 'recording':
            globals()['RecordingManager'] = module.RecordingManager
        elif module_name == 'camera':
            globals()['CameraManager'] = module.CameraManager
        
        log(f"🔄 Module {module_name} rechargé")
        return True
    except Exception as e:
        log(f"❌ Erreur rechargement {module_name}: {e}")
        return False

def check_and_reload_modules():
    """Vérifie les modifications de fichiers et recharge les modules si nécessaire"""
    reloaded = []
    
    for module_name, filepath in _module_paths.items():
        if not filepath.exists():
            continue
        
        current_mtime = filepath.stat().st_mtime
        
        if module_name in _module_timestamps:
            if current_mtime > _module_timestamps[module_name]:
                if reload_module(module_name):
                    reloaded.append(module_name)
                    _module_timestamps[module_name] = current_mtime
        else:
            _module_timestamps[module_name] = current_mtime
    
    return reloaded

app = Flask(__name__)
CORS(app)

# État global unifié de l'application
app_state = {
    # Bras Follower (Principal : exécute les ordres, répond aux sliders, enregistre)
    'follower_port': None,
    'follower_bus': None,
    'is_follower_connected': False,

    # Bras Leader (Téléopération : optionnel, guide le Follower)
    'leader_port': None,
    'leader_bus': None,
    'is_leader_connected': False,

    # Rétrocompatibilité avec les modules existants
    'motors': None,          # pointe vers follower_bus
    'is_connected': False,    # équivalent à is_follower_connected
    'port': 'COM5',          # équivalent à follower_port
    'motor_controller': None,
    'calibration_manager': None,
    'recording_manager': None,

    'leader_calibration_manager': None,

    # Sliders
    'pending_positions': {},
    'position_sender_running': False,
    'torque_enabled_for_sliders': set(),

    # Téléopération / Clonage
    'teleop_running': False,
    'teleop_thread': None,
    'teleop_stop_event': threading.Event(),
    'teleop_last_error': None,

    # Caméra Vision Embarquée
    'camera_manager': None,

    # Logs
    'log_messages': [],
    'log_lock': threading.Lock()
}

def log(message):
    """Ajoute un message au log"""
    with app_state['log_lock']:
        app_state['log_messages'].append({
            'time': time.strftime('%H:%M:%S'),
            'message': message
        })
        # Garder seulement les 1000 derniers messages
        if len(app_state['log_messages']) > 1000:
            app_state['log_messages'] = app_state['log_messages'][-1000:]

# Initialisation du CameraManager avec logging centralisé
app_state['camera_manager'] = CameraManager(log_fn=log)

# Proxy de compatibilité pour clone_state
clone_state = {
    'leader_port': None,
    'follower_port': None,
    'leader_bus': None,
    'follower_bus': None,
    'leader_calibration_manager': None,
    'follower_calibration_manager': None,
    'running': False,
    'thread': None,
    'stop_event': app_state['teleop_stop_event'],
    'last_error': None
}

# État calibration auto (interrompable)
calib_state = {
    'running': False,
    'stop_event': threading.Event(),
    'role': None
}

def _start_position_sender():
    """Démarre le thread d'envoi des positions pour les sliders"""
    if app_state['position_sender_running']:
        return
    
    app_state['position_sender_running'] = True
    
    def send_positions():
        overload_cooldown = {}
        
        while app_state['position_sender_running']:
            if not app_state['pending_positions']:
                time.sleep(0.02)
                continue
            
            positions_to_send = app_state['pending_positions'].copy()
            app_state['pending_positions'].clear()
            
            current_time = time.time()
            
            for motor_name, raw_pos in positions_to_send.items():
                if motor_name in overload_cooldown:
                    if current_time < overload_cooldown[motor_name]:
                        continue
                    else:
                        del overload_cooldown[motor_name]
                
                try:
                    if motor_name not in app_state['torque_enabled_for_sliders']:
                        app_state['motors'].write("Torque_Enable", motor_name, 1, normalize=False)
                        app_state['torque_enabled_for_sliders'].add(motor_name)
                        time.sleep(0.01)
                    
                    app_state['motors'].write("Goal_Position", motor_name, raw_pos, normalize=False)
                    
                except Exception as e:
                    error_msg = str(e)
                    if "Overload" in error_msg:
                        if motor_name not in overload_cooldown:
                            log(f"⚠️ {motor_name}: Surcharge détectée - pause 2s")
                            overload_cooldown[motor_name] = current_time + 2.0
                    else:
                        log(f"Erreur envoi {motor_name}: {e}")
                
                time.sleep(0.02)
            
            time.sleep(0.03)
        
        app_state['position_sender_running'] = False
    
    threading.Thread(target=send_positions, daemon=True).start()

def _convert_slider_to_raw_direct(motor_name, normalized):
    """Convertit le slider (0.0-1.0) en valeurs brutes"""
    if motor_name == "gripper":
        GRIPPER_CLOSED = 2029
        GRIPPER_OPEN = 3204
        return int(GRIPPER_CLOSED + (normalized * (GRIPPER_OPEN - GRIPPER_CLOSED)))
    
    if not app_state['calibration_manager'] or motor_name not in app_state['calibration_manager'].calibrations:
        return int(normalized * 4095)
    
    calib = app_state['calibration_manager'].calibrations[motor_name]
    pos_left = calib.get('pos_left')
    pos_right = calib.get('pos_right')
    
    if pos_left is None or pos_right is None:
        return int(normalized * 4095)
    
    return int(pos_left + (normalized * (pos_right - pos_left)))

def _get_normalized_position(motor_name, raw_pos):
    """Normalise une position brute"""
    if not app_state['calibration_manager'] or motor_name not in app_state['calibration_manager'].calibrations:
        return None
    
    calib = app_state['calibration_manager'].calibrations[motor_name]
    pos_left = calib.get('pos_left')
    pos_right = calib.get('pos_right')
    pos_center = calib.get('pos_center')
    
    if pos_left is None or pos_right is None or pos_center is None:
        return None
    
    return normalize_position(raw_pos, pos_left, pos_right, pos_center)

def _extract_lrcenter(calib):
    """
    Extrait (left, right, center) depuis une calibration.
    Supporte:
    - format manuel: pos_left/pos_right/pos_center
    - format auto: min_position/max_position (center calculé)
    """
    if not calib:
        return None, None, None

    pos_left = calib.get('pos_left')
    pos_right = calib.get('pos_right')
    pos_center = calib.get('pos_center')

    # Compat ancien/auto: min/max
    if pos_left is None and 'min_position' in calib:
        pos_left = calib.get('min_position')
    if pos_right is None and 'max_position' in calib:
        pos_right = calib.get('max_position')
    if pos_center is None and pos_left is not None and pos_right is not None:
        try:
            pos_center = (int(pos_left) + int(pos_right)) // 2
        except Exception:
            pos_center = None

    return pos_left, pos_right, pos_center

def _normalize_with_calib(raw_pos, calib):
    """Normalise une position brute avec une calibration (manuel ou auto)."""
    pos_left, pos_right, pos_center = _extract_lrcenter(calib)
    if pos_left is None or pos_right is None or pos_center is None:
        return None
    return normalize_position(raw_pos, pos_left, pos_right, pos_center)

def _denormalize_with_calib(normalized, calib):
    """Convertit une position normalisée en brut avec une calibration (manuel ou auto)."""
    pos_left, pos_right, pos_center = _extract_lrcenter(calib)
    if pos_left is None or pos_right is None or pos_center is None:
        return None
    return int(denormalize_position(normalized, pos_left, pos_right, pos_center))

def _build_motor_config():
    return {
        name: Motor(id=motor_id, model="sts3215", norm_mode=MotorNormMode.RANGE_0_100)
        for name, motor_id in zip(MOTOR_NAMES, MOTOR_IDS)
    }

# Routes API
@app.route('/')
def index():
    return render_template('index.html')

def _connect_follower(port):
    """Connecte le bras Follower (principal)"""
    if app_state['is_follower_connected']:
        if app_state['follower_port'] == port:
            return True, None
        _disconnect_follower()

    if not LEROBOT_AVAILABLE:
        return False, "LeRobot non installé"

    try:
        log(f"🔌 [Follower] Connexion sur {port}...")
        motor_config = _build_motor_config()
        bus = FeetechMotorsBus(port=port, motors=motor_config)
        bus.connect()

        app_state['follower_port'] = port
        app_state['follower_bus'] = bus
        app_state['is_follower_connected'] = True

        # Rétrocompatibilité interne
        app_state['port'] = port
        app_state['motors'] = bus
        app_state['is_connected'] = True

        app_state['motor_controller'] = MotorController(bus, log)
        app_state['calibration_manager'] = CalibrationManager(bus, log, calibration_file=CLONE_FOLLOWER_CALIB_FILE)
        app_state['calibration_manager'].load_calibration_from_file()
        app_state['recording_manager'] = RecordingManager(bus, log)

        # Mettre à jour clone_state proxy
        clone_state['follower_port'] = port
        clone_state['follower_bus'] = bus
        clone_state['follower_calibration_manager'] = app_state['calibration_manager']

        log(f"✅ Follower connecté sur {port}")
        return True, None
    except Exception as e:
        _disconnect_follower()
        log(f"❌ Erreur connexion Follower: {e}")
        return False, str(e)

def _disconnect_follower():
    """Déconnecte le bras Follower"""
    if app_state['teleop_running']:
        _stop_teleoperation()

    if app_state['follower_bus']:
        try:
            app_state['follower_bus'].disconnect()
        except Exception:
            pass

    app_state['follower_bus'] = None
    app_state['follower_port'] = None
    app_state['is_follower_connected'] = False

    app_state['motors'] = None
    app_state['is_connected'] = False
    app_state['motor_controller'] = None
    app_state['calibration_manager'] = None
    app_state['recording_manager'] = None
    app_state['position_sender_running'] = False
    app_state['pending_positions'].clear()
    app_state['torque_enabled_for_sliders'].clear()

    clone_state['follower_port'] = None
    clone_state['follower_bus'] = None
    clone_state['follower_calibration_manager'] = None

    log("✓ Follower déconnecté")

def _connect_leader(port):
    """Connecte le bras Leader (téléopération / guidage)"""
    if app_state['is_leader_connected']:
        if app_state['leader_port'] == port:
            return True, None
        _disconnect_leader()

    if not LEROBOT_AVAILABLE:
        return False, "LeRobot non installé"

    try:
        log(f"🎮 [Leader] Connexion sur {port}...")
        motor_config = _build_motor_config()
        bus = FeetechMotorsBus(port=port, motors=motor_config)
        bus.connect()

        # Sur le bras Leader, relâcher immédiatement le couple pour manipulation manuelle
        for name in MOTOR_NAMES:
            try:
                bus.write("Torque_Enable", name, 0, normalize=False)
            except Exception:
                pass

        app_state['leader_port'] = port
        app_state['leader_bus'] = bus
        app_state['is_leader_connected'] = True

        app_state['leader_calibration_manager'] = CalibrationManager(bus, log, calibration_file=CLONE_LEADER_CALIB_FILE)
        app_state['leader_calibration_manager'].load_calibration_from_file()

        # Mettre à jour clone_state proxy
        clone_state['leader_port'] = port
        clone_state['leader_bus'] = bus
        clone_state['leader_calibration_manager'] = app_state['leader_calibration_manager']

        log(f"✅ Leader connecté sur {port} (couple relâché pour guidage)")
        return True, None
    except Exception as e:
        _disconnect_leader()
        log(f"❌ Erreur connexion Leader: {e}")
        return False, str(e)

def _disconnect_leader():
    """Déconnecte le bras Leader"""
    if app_state['teleop_running']:
        _stop_teleoperation()

    if app_state['leader_bus']:
        try:
            app_state['leader_bus'].disconnect()
        except Exception:
            pass

    app_state['leader_bus'] = None
    app_state['leader_port'] = None
    app_state['is_leader_connected'] = False
    app_state['leader_calibration_manager'] = None

    clone_state['leader_port'] = None
    clone_state['leader_bus'] = None
    clone_state['leader_calibration_manager'] = None

    log("✓ Leader déconnecté")

def _teleop_thread_loop():
    """Boucle temps réel de téléopération (Leader ➜ Follower)"""
    leader_bus = app_state['leader_bus']
    follower_bus = app_state['follower_bus']
    leader_calib = app_state['leader_calibration_manager']
    follower_calib = app_state['calibration_manager']

    try:
        # Verrouiller le couple sur le Follower
        for name in MOTOR_NAMES:
            try:
                follower_bus.write("Torque_Enable", name, 1, normalize=False)
            except Exception:
                pass
        # S'assurer que le Leader est libre
        for name in MOTOR_NAMES:
            try:
                leader_bus.write("Torque_Enable", name, 0, normalize=False)
            except Exception:
                pass

        overload_cooldown = {}
        last_sent = {}
        last_sent_ts = {}

        while not app_state['teleop_stop_event'].is_set():
            try:
                positions = leader_bus.sync_read("Present_Position", motors=MOTOR_NAMES, normalize=False)
                now = time.time()
                for name in MOTOR_NAMES:
                    if name in overload_cooldown and now < overload_cooldown[name]:
                        continue
                    elif name in overload_cooldown and now >= overload_cooldown[name]:
                        del overload_cooldown[name]

                    raw = int(positions.get(name, 0))
                    norm = _normalize_with_calib(raw, leader_calib.calibrations.get(name) if leader_calib else None)
                    if norm is not None:
                        target = _denormalize_with_calib(norm, follower_calib.calibrations.get(name) if follower_calib else None)
                    else:
                        target = raw
                    if target is None:
                        target = raw

                    try:
                        target_int = max(0, min(4095, int(target)))
                    except Exception:
                        target_int = raw

                    prev = last_sent.get(name)
                    prev_ts = last_sent_ts.get(name, 0.0)
                    if prev is not None and abs(target_int - prev) <= 1 and (now - prev_ts) < 0.15:
                        continue

                    try:
                        follower_bus.write("Goal_Position", name, target_int, normalize=False)
                        last_sent[name] = target_int
                        last_sent_ts[name] = now
                    except Exception as we:
                        err_str = str(we)
                        if "Overload" in err_str:
                            overload_cooldown[name] = now + 2.0
                        elif "status packet" in err_str or "TxRxResult" in err_str:
                            overload_cooldown[name] = now + 1.0

                    time.sleep(0.002)
                time.sleep(0.02)
            except Exception as e:
                app_state['teleop_last_error'] = str(e)
                log(f"❌ Téléopération interrompue: {e}")
                break
    finally:
        app_state['teleop_running'] = False
        clone_state['running'] = False
        log("⏹ Téléopération arrêtée")

def _start_teleoperation():
    """Démarre le clonage Leader -> Follower"""
    if not app_state['is_follower_connected'] or not app_state['is_leader_connected']:
        return False, "Le Follower et le Leader doivent tous deux être connectés."
    if app_state['follower_port'] == app_state['leader_port']:
        return False, "Le Leader et le Follower ne peuvent pas partager le même port."
    if app_state['teleop_running']:
        return True, None

    app_state['teleop_running'] = True
    clone_state['running'] = True
    app_state['teleop_stop_event'].clear()
    app_state['teleop_last_error'] = None
    app_state['teleop_thread'] = threading.Thread(target=_teleop_thread_loop, daemon=True)
    app_state['teleop_thread'].start()
    log("🧬 Téléopération démarrée (Leader ➜ Follower)")
    return True, None

def _stop_teleoperation():
    """Arrête le clonage Leader -> Follower"""
    if app_state['teleop_running']:
        app_state['teleop_stop_event'].set()
        if app_state['teleop_thread']:
            app_state['teleop_thread'].join(timeout=2)
        app_state['teleop_running'] = False
        clone_state['running'] = False
        app_state['teleop_thread'] = None
    return True, None

# ==================== ROUTES DE CONNEXION ET STATUT UNIFIÉES ====================

@app.route('/api/status')
def get_status():
    """Retourne le statut unifié des deux bras, de la téléopération et de la caméra"""
    cam_status = app_state['camera_manager'].get_status() if app_state['camera_manager'] else {'connected': False}
    return jsonify({
        'success': True,
        'lerobot_available': LEROBOT_AVAILABLE,
        'follower': {
            'connected': app_state['is_follower_connected'],
            'port': app_state['follower_port']
        },
        'leader': {
            'connected': app_state['is_leader_connected'],
            'port': app_state['leader_port']
        },
        'teleop': {
            'running': app_state['teleop_running'],
            'can_start': app_state['is_follower_connected'] and app_state['is_leader_connected'],
            'last_error': app_state['teleop_last_error']
        },
        'camera': cam_status,
        # Rétrocompatibilité avec les scripts ou appels existants
        'connected': app_state['is_follower_connected'],
        'port': app_state['follower_port'] or app_state['port']
    })

@app.route('/api/arm/connect', methods=['POST'])
def arm_connect():
    """Connecte un bras spécifique ('follower' ou 'leader')"""
    data = request.json or {}
    role = data.get('role', 'follower').lower()
    port = data.get('port')
    if not port:
        return jsonify({'success': False, 'error': 'Port requis'}), 400

    if role == 'leader' and app_state['is_follower_connected'] and app_state['follower_port'] == port:
        return jsonify({'success': False, 'error': f"Le port {port} est déjà utilisé par le Follower."}), 400
    if role == 'follower' and app_state['is_leader_connected'] and app_state['leader_port'] == port:
        return jsonify({'success': False, 'error': f"Le port {port} est déjà utilisé par le Leader."}), 400

    if role == 'follower':
        ok, err = _connect_follower(port)
    elif role == 'leader':
        ok, err = _connect_leader(port)
    else:
        return jsonify({'success': False, 'error': f"Rôle inconnu : {role}"}), 400

    if not ok:
        return jsonify({'success': False, 'error': err}), 400
    return jsonify({'success': True, 'role': role, 'port': port})

@app.route('/api/arm/disconnect', methods=['POST'])
def arm_disconnect():
    """Déconnecte un bras spécifique ('follower' ou 'leader')"""
    data = request.json or {}
    role = data.get('role', 'follower').lower()
    if role == 'follower':
        _disconnect_follower()
    elif role == 'leader':
        _disconnect_leader()
    else:
        return jsonify({'success': False, 'error': f"Rôle inconnu : {role}"}), 400
    return jsonify({'success': True, 'role': role})

@app.route('/api/disconnect-all', methods=['POST'])
def disconnect_all():
    """Déconnecte tous les bras (Follower et Leader), stoppe la téléopération et la caméra"""
    if app_state['teleop_running']:
        _stop_teleoperation()
    _disconnect_follower()
    _disconnect_leader()
    if app_state['camera_manager']:
        app_state['camera_manager'].stop()
    log("🛑 Déconnexion globale effectuée (tous les bras & caméra)")
    return jsonify({'success': True})

@app.route('/api/teleop/toggle', methods=['POST'])
def teleop_toggle():
    """Bascule le mode téléopération / clonage"""
    if app_state['teleop_running']:
        _stop_teleoperation()
        return jsonify({'success': True, 'running': False})
    else:
        ok, err = _start_teleoperation()
        if not ok:
            return jsonify({'success': False, 'error': err}), 400
        return jsonify({'success': True, 'running': True})

# ==================== ROUTES CAMÉRA (VISION EMBARQUÉE) ====================

@app.route('/api/camera/list')
def camera_list():
    """Détecte et liste les caméras disponibles"""
    cm = app_state['camera_manager']
    if not cm:
        return jsonify({'success': False, 'error': 'CameraManager non disponible'}), 500
    try:
        cameras = cm.list_cameras()
        return jsonify({
            'success': True,
            'cameras': cameras,
            'status': cm.get_status()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/camera/status')
def camera_status():
    """Retourne l'état courant de la caméra"""
    cm = app_state['camera_manager']
    if not cm:
        return jsonify({'success': False, 'error': 'CameraManager non disponible'}), 500
    return jsonify({
        'success': True,
        'camera': cm.get_status()
    })

@app.route('/api/camera/connect', methods=['POST'])
def camera_connect():
    """Connecte et active une caméra par son index"""
    cm = app_state['camera_manager']
    if not cm:
        return jsonify({'success': False, 'error': 'CameraManager non disponible'}), 500

    data = request.json or {}
    try:
        index = int(data.get('index', 0))
    except (ValueError, TypeError):
        index = 0

    ok, err = cm.start(index=index)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400

    return jsonify({
        'success': True,
        'camera': cm.get_status()
    })

@app.route('/api/camera/disconnect', methods=['POST'])
def camera_disconnect():
    """Déconnecte et libère la caméra"""
    cm = app_state['camera_manager']
    if not cm:
        return jsonify({'success': True})
    cm.stop()
    return jsonify({
        'success': True,
        'camera': cm.get_status()
    })

@app.route('/api/camera/settings', methods=['POST'])
def camera_settings():
    """Met à jour les paramètres d'orientation et d'affichage"""
    cm = app_state['camera_manager']
    if not cm:
        return jsonify({'success': False, 'error': 'CameraManager non disponible'}), 500

    data = request.json or {}
    updated_status = cm.update_settings(
        show_crosshair=data.get('show_crosshair'),
        rotate_180=data.get('rotate_180'),
        flip_h=data.get('flip_h')
    )
    return jsonify({
        'success': True,
        'camera': updated_status
    })

@app.route('/api/camera/stream')
def camera_stream():
    """Flux vidéo MJPEG temps réel pour balise <img src='/api/camera/stream'>"""
    cm = app_state['camera_manager']
    if not cm or not cm.is_running:
        return "Camera not active", 404

    def generate():
        while cm and cm.is_running:
            jpeg = cm.get_jpeg_frame()
            if jpeg:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
            time.sleep(0.025)

    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/api/camera/snapshot', methods=['POST'])
def camera_snapshot():
    """Prend une capture instantanée et retourne l'URL du fichier"""
    cm = app_state['camera_manager']
    if not cm:
        return jsonify({'success': False, 'error': 'CameraManager non disponible'}), 500

    ok, filename_or_err, _ = cm.take_snapshot(save_dir="snapshots")
    if not ok:
        return jsonify({'success': False, 'error': filename_or_err}), 400

    return jsonify({
        'success': True,
        'filename': filename_or_err,
        'url': f'/snapshots/{filename_or_err}'
    })

@app.route('/snapshots/<path:filename>')
def serve_snapshot(filename):
    """Sert un snapshot pour affichage ou téléchargement"""
    snapshot_dir = Path("snapshots").resolve()
    return send_from_directory(str(snapshot_dir), filename, as_attachment=True)

# Rétrocompatibilité : /api/connect
@app.route('/api/connect', methods=['POST'])
def connect():
    """Connecte ou déconnecte le Follower (rétrocompatibilité)"""
    data = request.json or {}
    port = data.get('port', 'COM5')

    if not app_state['is_follower_connected']:
        ok, err = _connect_follower(port)
        if not ok:
            return jsonify({'success': False, 'error': err}), 400
        return jsonify({'success': True})
    else:
        _disconnect_follower()
        return jsonify({'success': True})

# Rétrocompatibilité : /api/clone/*
@app.route('/api/clone/status')
def clone_status():
    return jsonify({
        'success': True,
        'running': app_state['teleop_running'],
        'leader_port': app_state['leader_port'],
        'follower_port': app_state['follower_port'],
        'last_error': app_state['teleop_last_error']
    })

@app.route('/api/clone/start', methods=['POST'])
def clone_start():
    data = request.json or {}
    leader_port = data.get('leader_port') or app_state['leader_port']
    follower_port = data.get('follower_port') or app_state['follower_port']

    if leader_port and not app_state['is_leader_connected']:
        ok, err = _connect_leader(leader_port)
        if not ok: return jsonify({'success': False, 'error': err}), 400
    if follower_port and not app_state['is_follower_connected']:
        ok, err = _connect_follower(follower_port)
        if not ok: return jsonify({'success': False, 'error': err}), 400

    ok, err = _start_teleoperation()
    if not ok:
        return jsonify({'success': False, 'error': err}), 400
    return jsonify({'success': True, 'running': True})

@app.route('/api/clone/stop', methods=['POST'])
def clone_stop():
    _stop_teleoperation()
    return jsonify({'success': True, 'running': False})

def _start_clone_calibration(port, calib_file, role='follower'):
    # Si le bras est déjà connecté sur ce port, utiliser son bus sans réouverture !
    existing_bus = None
    if role == 'leader' and app_state['is_leader_connected'] and app_state['leader_port'] == port:
        existing_bus = app_state['leader_bus']
    elif role == 'follower' and app_state['is_follower_connected'] and app_state['follower_port'] == port:
        existing_bus = app_state['follower_bus']

    if existing_bus:
        calib_mgr = CalibrationManager(existing_bus, log)
        calib_mgr.calibration_file = calib_file
        def calib_thread():
            for motor_name in MOTOR_NAMES:
                motor_id = MOTOR_IDS[MOTOR_NAMES.index(motor_name)]
                calib_mgr.calibrate_motor_auto(motor_name, motor_id, log)
            calib_mgr.save_calibration_to_file()
            log(f"✅ Calibration [{role}] sauvegardée dans {calib_file}")
        threading.Thread(target=calib_thread, daemon=True).start()
    else:
        motor_config = _build_motor_config()
        motors = FeetechMotorsBus(port=port, motors=motor_config)
        motors.connect()
        calib_mgr = CalibrationManager(motors, log)
        calib_mgr.calibration_file = calib_file
        def calib_thread():
            try:
                for motor_name in MOTOR_NAMES:
                    motor_id = MOTOR_IDS[MOTOR_NAMES.index(motor_name)]
                    calib_mgr.calibrate_motor_auto(motor_name, motor_id, log)
                calib_mgr.save_calibration_to_file()
                log(f"✅ Calibration [{role}] sauvegardée dans {calib_file}")
            finally:
                try: motors.disconnect()
                except Exception: pass
        threading.Thread(target=calib_thread, daemon=True).start()

@app.route('/api/clone/calibration/leader', methods=['POST'])
def clone_calibration_leader():
    data = request.json or {}
    port = data.get('port') or app_state['leader_port']
    if not port:
        return jsonify({'success': False, 'error': 'Port leader requis'}), 400
    if app_state['teleop_running']:
        return jsonify({'success': False, 'error': 'Arrêtez la téléopération avant calibration'}), 400
    _start_clone_calibration(port, CLONE_LEADER_CALIB_FILE, role='leader')
    return jsonify({'success': True})

@app.route('/api/clone/calibration/follower', methods=['POST'])
def clone_calibration_follower():
    data = request.json or {}
    port = data.get('port') or app_state['follower_port']
    if not port:
        return jsonify({'success': False, 'error': 'Port follower requis'}), 400
    if app_state['teleop_running']:
        return jsonify({'success': False, 'error': 'Arrêtez la téléopération avant calibration'}), 400
    _start_clone_calibration(port, CLONE_FOLLOWER_CALIB_FILE, role='follower')
    return jsonify({'success': True})

@app.route('/api/positions', methods=['GET'])
def read_positions():
    """Lit les positions actuelles"""
    if not app_state['is_connected']:
        return jsonify({'success': False, 'error': 'Non connecté'}), 400
    
    try:
        positions = app_state['motor_controller'].read_positions(normalize=False)
        result = {}
        
        for name in MOTOR_NAMES:
            raw_pos = int(positions.get(name, 0))
            normalized = _get_normalized_position(name, raw_pos)
            
            result[name] = {
                'raw': raw_pos,
                'normalized': normalized,
                'percent': int(normalized * 100) if normalized is not None else int((raw_pos / 4095) * 100)
            }
        
        return jsonify({'success': True, 'positions': result})
        
    except Exception as e:
        log(f"❌ Erreur lecture: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/motors/release', methods=['POST'])
def release_motors():
    """Relâche les moteurs"""
    if not app_state['is_connected']:
        return jsonify({'success': False, 'error': 'Non connecté'}), 400
    
    app_state['motor_controller'].release_motors()
    return jsonify({'success': True})

@app.route('/api/motors/lock', methods=['POST'])
def lock_motors():
    """Verrouille les moteurs"""
    if not app_state['is_connected']:
        return jsonify({'success': False, 'error': 'Non connecté'}), 400
    
    app_state['motor_controller'].lock_motors()
    return jsonify({'success': True})

@app.route('/api/motors/home', methods=['POST'])
def go_home():
    """Envoie les moteurs à la position home"""
    if not app_state['is_connected']:
        return jsonify({'success': False, 'error': 'Non connecté'}), 400
    
    app_state['motor_controller'].go_home()
    return jsonify({'success': True})

@app.route('/api/slider/update', methods=['POST'])
def update_slider():
    """Met à jour la position d'un slider"""
    data = request.json
    motor_name = data.get('motor')
    value = data.get('value')  # 0-100
    
    if not app_state['is_connected']:
        return jsonify({'success': False, 'error': 'Non connecté'}), 400
    
    try:
        normalized = float(value) / 100.0
        raw_pos = _convert_slider_to_raw_direct(motor_name, normalized)
        app_state['pending_positions'][motor_name] = raw_pos
        _start_position_sender()
        
        return jsonify({'success': True, 'raw': raw_pos})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/slider/enable', methods=['POST'])
def enable_sliders():
    """Active ou désactive le contrôle par sliders"""
    data = request.json
    enabled = data.get('enabled', False)
    
    if enabled:
        app_state['pending_positions'] = {}
        app_state['position_sender_running'] = False
        app_state['torque_enabled_for_sliders'] = set()
    else:
        app_state['position_sender_running'] = False
        app_state['torque_enabled_for_sliders'] = set()
    
    return jsonify({'success': True})

@app.route('/api/calibration/info', methods=['GET'])
def get_calibration_info():
    """Retourne les informations de calibration"""
    if not app_state['calibration_manager']:
        return jsonify({'success': True, 'calibrations': {}})
    
    calibrations = {}
    for motor_name in MOTOR_NAMES:
        if motor_name in app_state['calibration_manager'].calibrations:
            calib = app_state['calibration_manager'].calibrations[motor_name]
            calibrations[motor_name] = {
                'pos_left': calib.get('pos_left'),
                'pos_right': calib.get('pos_right'),
                'pos_center': calib.get('pos_center')
            }
        else:
            calibrations[motor_name] = {
                'pos_left': None,
                'pos_right': None,
                'pos_center': None
            }
    
    return jsonify({'success': True, 'calibrations': calibrations})

@app.route('/api/recording/start', methods=['POST'])
def start_recording():
    """Démarre l'enregistrement"""
    if not app_state['is_connected']:
        return jsonify({'success': False, 'error': 'Non connecté'}), 400
    
    data = request.json
    interval = data.get('interval', 100)
    
    app_state['motor_controller'].release_motors()
    app_state['recording_manager'].start_recording(interval, None)
    
    return jsonify({'success': True})

@app.route('/api/recording/stop', methods=['POST'])
def stop_recording():
    """Arrête l'enregistrement"""
    app_state['recording_manager'].stop_recording(app_state['motor_controller'].lock_motors)
    return jsonify({'success': True})

@app.route('/api/recording/save', methods=['POST'])
def save_recording():
    """Sauvegarde l'enregistrement"""
    data = request.json
    interval = data.get('interval', 100)
    
    if not app_state['recording_manager'].recorded_frames:
        return jsonify({'success': False, 'error': 'Aucun enregistrement'}), 400
    
    # Sauvegarder dans un fichier
    filename = f"recording_{int(time.time())}.json"
    filepath = os.path.join(os.getcwd(), filename)
    
    data_to_save = {
        "name": "recording",
        "sample_period_s": interval / 1000.0,
        "servo_ids": MOTOR_IDS,
        "frames": app_state['recording_manager'].recorded_frames
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data_to_save, f, indent=2, ensure_ascii=False)
    
    log(f"💾 Sauvegardé: {filename}")
    return jsonify({'success': True, 'filename': filename})

@app.route('/api/recording/load', methods=['POST'])
def load_recording():
    """Charge un enregistrement depuis un fichier uploadé ou un fichier local"""
    data = request.json
    
    # Si le contenu est fourni directement (upload depuis navigateur)
    if 'content' in data:
        data_loaded = data['content']
        filename = data.get('filename', 'uploaded_file.json')
    else:
        # Sinon, charger depuis un fichier local
        filename = data.get('filename')
        if not filename:
            return jsonify({'success': False, 'error': 'Nom de fichier requis'}), 400
        
        filepath = os.path.join(os.getcwd(), filename)
        
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'Fichier non trouvé'}), 400
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data_loaded = json.load(f)
    
    # Valider la structure du fichier
    if not isinstance(data_loaded, dict):
        return jsonify({'success': False, 'error': 'Format de fichier invalide'}), 400
    
    frames = data_loaded.get('frames', [])
    if not isinstance(frames, list):
        return jsonify({'success': False, 'error': 'Format de fichier invalide: frames manquants'}), 400
    
    app_state['recording_manager'].recorded_frames = frames
    log(f"📂 Chargé: {filename} ({len(frames)} frames)")
    
    return jsonify({'success': True, 'frames': len(frames)})

@app.route('/api/recording/play', methods=['POST'])
def play_recording():
    """Joue l'enregistrement"""
    if not app_state['is_connected']:
        return jsonify({'success': False, 'error': 'Non connecté'}), 400
    
    if not app_state['recording_manager'].recorded_frames:
        return jsonify({'success': False, 'error': 'Aucun enregistrement'}), 400
    
    app_state['motor_controller'].lock_motors()
    app_state['recording_manager'].play_recording(None, None)
    
    return jsonify({'success': True})

@app.route('/api/recording/stop_playback', methods=['POST'])
def stop_playback():
    """Arrête la lecture"""
    app_state['recording_manager'].stop_playback()
    return jsonify({'success': True})

@app.route('/api/recording/status', methods=['GET'])
def recording_status():
    """Retourne le statut de l'enregistrement"""
    if not app_state['recording_manager']:
        return jsonify({
            'is_recording': False,
            'is_playing': False,
            'frames': 0,
            'current_frame': 0,
            'progress': 0
        })
    
    total_frames = len(app_state['recording_manager'].recorded_frames)
    current_frame = app_state['recording_manager'].current_frame
    progress = (current_frame / total_frames * 100) if total_frames > 0 else 0
    
    return jsonify({
        'is_recording': app_state['recording_manager'].is_recording,
        'is_playing': app_state['recording_manager'].is_playing,
        'frames': total_frames,
        'current_frame': current_frame,
        'progress': round(progress, 2)
    })

@app.route('/api/calibration/auto', methods=['POST'])
def calibrate_auto():
    """Calibration automatique (interrompable)"""
    if not app_state['is_connected']:
        return jsonify({'success': False, 'error': 'Non connecté'}), 400
    if calib_state['running']:
        return jsonify({'success': False, 'error': 'Une calibration est déjà en cours'}), 400
    
    data = request.json or {}
    motors = data.get('motors', MOTOR_NAMES)
    
    calib_state['running'] = True
    calib_state['stop_event'].clear()
    
    def calibration_thread():
        try:
            for motor_name in motors:
                if calib_state['stop_event'].is_set():
                    log("⏹ Calibration automatique interrompue par l'utilisateur.")
                    break
                if motor_name not in MOTOR_NAMES:
                    continue
                
                motor_id = MOTOR_IDS[MOTOR_NAMES.index(motor_name)]
                ok = app_state['calibration_manager'].calibrate_motor_auto(
                    motor_name, motor_id, log, stop_event=calib_state['stop_event']
                )
                if not ok and calib_state['stop_event'].is_set():
                    break
            
            if not calib_state['stop_event'].is_set():
                app_state['calibration_manager'].save_calibration_to_file()
                log("✅ Calibration automatique terminée et enregistrée.")
        finally:
            calib_state['running'] = False
            # Par sécurité, relâcher les moteurs après arrêt
            if calib_state['stop_event'].is_set() and app_state['motors']:
                try:
                    for name in MOTOR_NAMES:
                        app_state['motors'].write("Torque_Enable", name, 0, normalize=False)
                except Exception:
                    pass
    
    threading.Thread(target=calibration_thread, daemon=True).start()
    return jsonify({'success': True, 'running': True})

@app.route('/api/calibration/stop', methods=['POST'])
def calibrate_stop():
    """Arrête immédiatement la calibration automatique et coupe le couple"""
    calib_state['stop_event'].set()
    calib_state['running'] = False
    log("🛑 Arrêt d'urgence de la calibration demandé...")
    for bus in (app_state['follower_bus'], app_state['leader_bus'], app_state['motors']):
        if bus:
            for name in MOTOR_NAMES:
                try:
                    bus.write("Torque_Enable", name, 0, normalize=False)
                except Exception:
                    pass
    log("✓ Couple désactivé sur tous les moteurs.")
    return jsonify({'success': True})

@app.route('/api/calibration/manual', methods=['POST'])
def calibrate_manual():
    """Enregistre une position de calibration manuelle"""
    if not app_state['is_connected']:
        return jsonify({'success': False, 'error': 'Non connecté'}), 400
    
    data = request.json
    motor_name = data.get('motor')
    position_type = data.get('type')  # 'left', 'right', 'center'
    
    try:
        pos = app_state['motors'].read("Present_Position", motor_name, normalize=False, num_retry=2)
        pos_int = int(pos)
        
        if motor_name not in app_state['calibration_manager'].calibrations:
            app_state['calibration_manager'].calibrations[motor_name] = {
                'motor_id': MOTOR_IDS[MOTOR_NAMES.index(motor_name)],
                'pos_left': None,
                'pos_right': None,
                'pos_center': None
            }
        
        app_state['calibration_manager'].calibrations[motor_name][f'pos_{position_type}'] = pos_int
        app_state['calibration_manager'].save_calibration_to_file()
        
        log(f"✓ {motor_name}: {position_type} = {pos_int}")
        
        return jsonify({'success': True, 'position': pos_int})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

def _get_clone_calib_file(role):
    if role == 'leader':
        return CLONE_LEADER_CALIB_FILE
    if role == 'follower':
        return CLONE_FOLLOWER_CALIB_FILE
    return None

def _get_active_bus(role, port=None):
    """Retourne le bus déjà connecté s'il correspond au rôle (et au port si spécifié)."""
    if role == 'follower' and app_state['is_follower_connected']:
        if not port or app_state['follower_port'] == port:
            return app_state['follower_bus']
    elif role == 'leader' and app_state['is_leader_connected']:
        if not port or app_state['leader_port'] == port:
            return app_state['leader_bus']
    elif role is None or role == 'default':
        if app_state['is_connected'] and (not port or app_state['port'] == port):
            return app_state['motors']
    return None

def _build_calibration_info(calibrations):
    info = {}
    for motor_name in MOTOR_NAMES:
        if motor_name in calibrations:
            calib = calibrations[motor_name]
            info[motor_name] = {
                'pos_left': calib.get('pos_left'),
                'pos_right': calib.get('pos_right'),
                'pos_center': calib.get('pos_center')
            }
        else:
            info[motor_name] = {
                'pos_left': None,
                'pos_right': None,
                'pos_center': None
            }
    return info

def _read_calibration_file_raw(filepath):
    """Lit un fichier calibration sans filtrer (accepte valeurs partielles)."""
    if not filepath or not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _write_calibration_file_raw(filepath, data):
    """Écrit un fichier calibration (format dict), en conservant les valeurs partielles."""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True, None
    except Exception as e:
        return False, str(e)

def _normalize_calib_entry(entry):
    """Normalise une entrée calibration en {motor_id,pos_left,pos_right,pos_center} sans exclure les None."""
    if not isinstance(entry, dict):
        return {'motor_id': None, 'pos_left': None, 'pos_right': None, 'pos_center': None}

    motor_id = entry.get('motor_id')
    pos_left = entry.get('pos_left')
    pos_right = entry.get('pos_right')
    pos_center = entry.get('pos_center')

    # Compatibilité ancien format min/max
    if pos_left is None and 'min_position' in entry:
        pos_left = entry.get('min_position')
    if pos_right is None and 'max_position' in entry:
        pos_right = entry.get('max_position')
    if pos_center is None and pos_left is not None and pos_right is not None:
        pos_center = (int(pos_left) + int(pos_right)) // 2

    return {
        'motor_id': motor_id,
        'pos_left': pos_left,
        'pos_right': pos_right,
        'pos_center': pos_center
    }

@app.route('/api/clone/calibration/info', methods=['POST'])
def clone_calibration_info():
    data = request.json
    role = data.get('role')
    calib_file = _get_clone_calib_file(role)
    if not calib_file:
        return jsonify({'success': False, 'error': 'Rôle invalide'}), 400
    raw = _read_calibration_file_raw(calib_file)
    # Retourner exactement comme la calibration ordinaire: valeurs potentiellement partielles.
    calibrations = {}
    for motor_name in MOTOR_NAMES:
        if motor_name in raw:
            calibrations[motor_name] = _normalize_calib_entry(raw[motor_name])
        else:
            calibrations[motor_name] = {'motor_id': MOTOR_IDS[MOTOR_NAMES.index(motor_name)], 'pos_left': None, 'pos_right': None, 'pos_center': None}
    return jsonify({'success': True, 'calibrations': _build_calibration_info(calibrations)})

@app.route('/api/clone/positions', methods=['POST'])
def clone_positions():
    data = request.json or {}
    role = data.get('role')
    port = data.get('port')
    if not port or role not in ('leader', 'follower'):
        return jsonify({'success': False, 'error': 'Port ou rôle invalide'}), 400
    if not LEROBOT_AVAILABLE:
        return jsonify({'success': False, 'error': 'LeRobot non installé'}), 400

    active_bus = _get_active_bus(role, port)
    if active_bus:
        try:
            positions = active_bus.sync_read("Present_Position", motors=MOTOR_NAMES, normalize=False)
            result = {}
            for name in MOTOR_NAMES:
                raw_pos = int(positions.get(name, 0))
                result[name] = {'raw': raw_pos}
            return jsonify({'success': True, 'positions': result})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400

    motor_config = _build_motor_config()
    motors = FeetechMotorsBus(port=port, motors=motor_config)
    try:
        motors.connect()
        positions = motors.sync_read("Present_Position", motors=MOTOR_NAMES, normalize=False)
        result = {}
        for name in MOTOR_NAMES:
            raw_pos = int(positions.get(name, 0))
            result[name] = {'raw': raw_pos}
        return jsonify({'success': True, 'positions': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        try:
            motors.disconnect()
        except Exception:
            pass

def _clone_set_torque(port, enable: bool, role: str = None):
    active_bus = _get_active_bus(role, port) if role else None
    if not active_bus and not role:
        if app_state['is_follower_connected'] and app_state['follower_port'] == port:
            active_bus = app_state['follower_bus']
        elif app_state['is_leader_connected'] and app_state['leader_port'] == port:
            active_bus = app_state['leader_bus']

    if active_bus:
        for name in MOTOR_NAMES:
            try:
                active_bus.write("Torque_Enable", name, 1 if enable else 0, normalize=False)
            except Exception:
                pass
        return True, None

    motor_config = _build_motor_config()
    motors = FeetechMotorsBus(port=port, motors=motor_config)
    try:
        motors.connect()
        for name in MOTOR_NAMES:
            try:
                motors.write("Torque_Enable", name, 1 if enable else 0, normalize=False)
            except Exception:
                pass
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        try:
            motors.disconnect()
        except Exception:
            pass

@app.route('/api/clone/motors/release', methods=['POST'])
def clone_release_motors():
    data = request.json or {}
    role = data.get('role')
    port = data.get('port')
    if not port or role not in ('leader', 'follower'):
        return jsonify({'success': False, 'error': 'Port ou rôle invalide'}), 400
    if clone_state['running']:
        return jsonify({'success': False, 'error': 'Arrêtez le clonage avant relâchement'}), 400
    if not LEROBOT_AVAILABLE:
        return jsonify({'success': False, 'error': 'LeRobot non installé'}), 400
    ok, err = _clone_set_torque(port, enable=False, role=role)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400
    log(f"🔓 [{role}] Moteurs relâchés sur {port}")
    return jsonify({'success': True})

@app.route('/api/clone/motors/lock', methods=['POST'])
def clone_lock_motors():
    data = request.json or {}
    role = data.get('role')
    port = data.get('port')
    if not port or role not in ('leader', 'follower'):
        return jsonify({'success': False, 'error': 'Port ou rôle invalide'}), 400
    if clone_state['running']:
        return jsonify({'success': False, 'error': 'Arrêtez le clonage avant verrouillage'}), 400
    if not LEROBOT_AVAILABLE:
        return jsonify({'success': False, 'error': 'LeRobot non installé'}), 400
    ok, err = _clone_set_torque(port, enable=True, role=role)
    if not ok:
        return jsonify({'success': False, 'error': err}), 400
    log(f"🔒 [{role}] Moteurs verrouillés sur {port}")
    return jsonify({'success': True})

@app.route('/api/clone/calibration/auto', methods=['POST'])
def clone_calibration_auto():
    data = request.json or {}
    role = data.get('role')
    port = data.get('port')
    motors_list = data.get('motors', MOTOR_NAMES)
    if not port or role not in ('leader', 'follower'):
        return jsonify({'success': False, 'error': 'Port ou rôle invalide'}), 400
    if clone_state['running']:
        return jsonify({'success': False, 'error': 'Arrêtez le clonage avant calibration'}), 400
    if not LEROBOT_AVAILABLE:
        return jsonify({'success': False, 'error': 'LeRobot non installé'}), 400

    calib_file = _get_clone_calib_file(role)
    motor_config = _build_motor_config()

    existing_bus = _get_active_bus(role, port)

    calib_state['running'] = True
    calib_state['stop_event'].clear()

    if existing_bus:
        calib_mgr = CalibrationManager(existing_bus, log, calibration_file=calib_file)
        def calibration_thread():
            try:
                for motor_name in motors_list:
                    if calib_state['stop_event'].is_set():
                        log(f"⏹ Calibration [{role}] interrompue.")
                        break
                    if motor_name not in MOTOR_NAMES:
                        continue
                    motor_id = MOTOR_IDS[MOTOR_NAMES.index(motor_name)]
                    calib_mgr.calibrate_motor_auto(motor_name, motor_id, log, stop_event=calib_state['stop_event'])
                if not calib_state['stop_event'].is_set():
                    calib_mgr.save_calibration_to_file()
                    log(f"✅ Calibration [{role}] sauvegardée dans {calib_file}")
            finally:
                calib_state['running'] = False
        threading.Thread(target=calibration_thread, daemon=True).start()
    else:
        motors = FeetechMotorsBus(port=port, motors=motor_config)
        calib_mgr = CalibrationManager(motors, log, calibration_file=calib_file)

        def calibration_thread():
            try:
                motors.connect()
                for motor_name in motors_list:
                    if calib_state['stop_event'].is_set():
                        log(f"⏹ Calibration [{role}] interrompue.")
                        break
                    if motor_name not in MOTOR_NAMES:
                        continue
                    motor_id = MOTOR_IDS[MOTOR_NAMES.index(motor_name)]
                    calib_mgr.calibrate_motor_auto(motor_name, motor_id, log, stop_event=calib_state['stop_event'])
                if not calib_state['stop_event'].is_set():
                    calib_mgr.save_calibration_to_file()
                    log(f"✅ Calibration [{role}] sauvegardée dans {calib_file}")
            finally:
                try:
                    motors.disconnect()
                except Exception:
                    pass
                calib_state['running'] = False

        threading.Thread(target=calibration_thread, daemon=True).start()
    return jsonify({'success': True, 'running': True})

@app.route('/api/clone/calibration/manual', methods=['POST'])
def clone_calibration_manual():
    data = request.json or {}
    role = data.get('role')
    port = data.get('port')
    motor_name = data.get('motor')
    position_type = data.get('type')
    if not port or role not in ('leader', 'follower'):
        return jsonify({'success': False, 'error': 'Port ou rôle invalide'}), 400
    if motor_name not in MOTOR_NAMES:
        return jsonify({'success': False, 'error': 'Moteur invalide'}), 400
    if position_type not in ('left', 'right', 'center'):
        return jsonify({'success': False, 'error': 'Type invalide'}), 400
    if clone_state['running']:
        return jsonify({'success': False, 'error': 'Arrêtez le clonage avant calibration'}), 400
    if not LEROBOT_AVAILABLE:
        return jsonify({'success': False, 'error': 'LeRobot non installé'}), 400

    calib_file = _get_clone_calib_file(role)
    active_bus = _get_active_bus(role, port)

    try:
        if active_bus:
            pos = active_bus.read("Present_Position", motor_name, normalize=False, num_retry=2)
            pos_int = int(pos)
        else:
            motor_config = _build_motor_config()
            motors = FeetechMotorsBus(port=port, motors=motor_config)
            try:
                motors.connect()
                pos = motors.read("Present_Position", motor_name, normalize=False, num_retry=2)
                pos_int = int(pos)
            finally:
                try:
                    motors.disconnect()
                except Exception:
                    pass

        # Charger et mettre à jour SANS filtrer (même logique que calibration ordinaire)
        raw = _read_calibration_file_raw(calib_file)
        if motor_name not in raw or not isinstance(raw.get(motor_name), dict):
            raw[motor_name] = {
                'motor_id': MOTOR_IDS[MOTOR_NAMES.index(motor_name)],
                'pos_left': None,
                'pos_right': None,
                'pos_center': None
            }
        raw[motor_name][f'pos_{position_type}'] = pos_int

        ok, err = _write_calibration_file_raw(calib_file, raw)
        if not ok:
            return jsonify({'success': False, 'error': err}), 400

        # Synchroniser le calibration manager actif en mémoire
        if role == 'follower' and app_state['calibration_manager']:
            app_state['calibration_manager'].load_calibration_from_file()
        elif role == 'leader' and app_state['leader_calibration_manager']:
            app_state['leader_calibration_manager'].load_calibration_from_file()

        log(f"✓ [{role}] {motor_name}: {position_type} = {pos_int}")
        return jsonify({'success': True, 'position': pos_int})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Retourne les messages de log"""
    with app_state['log_lock']:
        return jsonify({'success': True, 'logs': app_state['log_messages']})

@app.route('/api/files/list', methods=['GET'])
def list_files():
    """Liste les fichiers d'enregistrement disponibles"""
    files = [f for f in os.listdir('.') if f.endswith('.json') and f.startswith('recording_')]
    return jsonify({'success': True, 'files': files})

@app.route('/api/reload', methods=['POST'])
def reload_modules():
    """Recharge les modules Python modifiés"""
    reloaded = check_and_reload_modules()
    return jsonify({
        'success': True,
        'reloaded': reloaded,
        'message': f'Modules rechargés: {", ".join(reloaded) if reloaded else "Aucun"}'
    })

@app.route('/api/find-port', methods=['GET'])
def find_port():
    """Trouve les ports série disponibles"""
    ports = []
    
    # Méthode 1: Utiliser pyserial si disponible
    if SERIAL_AVAILABLE:
        try:
            available_ports = serial.tools.list_ports.comports()
            for port in available_ports:
                ports.append({
                    'device': port.device,
                    'description': port.description,
                    'manufacturer': port.manufacturer if port.manufacturer else '',
                    'hwid': port.hwid
                })
            log(f"🔍 {len(ports)} port(s) série trouvé(s)")
            return jsonify({
                'success': True,
                'ports': ports,
                'method': 'pyserial'
            })
        except Exception as e:
            log(f"⚠️ Erreur détection ports (pyserial): {e}")
    
    # Méthode 2: Essayer d'exécuter lerobot-find-port
    try:
        result = subprocess.run(
            ['lerobot-find-port'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Parser la sortie de lerobot-find-port
            output_lines = result.stdout.strip().split('\n')
            for line in output_lines:
                if line.strip() and not line.startswith('#'):
                    # Format typique: COM3 - Description
                    parts = line.split(' - ', 1)
                    if len(parts) >= 1:
                        device = parts[0].strip()
                        description = parts[1].strip() if len(parts) > 1 else ''
                        ports.append({
                            'device': device,
                            'description': description,
                            'manufacturer': '',
                            'hwid': ''
                        })
            log(f"🔍 {len(ports)} port(s) trouvé(s) via lerobot-find-port")
            return jsonify({
                'success': True,
                'ports': ports,
                'method': 'lerobot-find-port'
            })
    except FileNotFoundError:
        log("⚠️ lerobot-find-port non trouvé")
    except subprocess.TimeoutExpired:
        log("⚠️ Timeout lors de l'exécution de lerobot-find-port")
    except Exception as e:
        log(f"⚠️ Erreur exécution lerobot-find-port: {e}")
    
    # Méthode 3: Sur Windows, essayer de lister COM1-COM20
    if sys.platform == 'win32':
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DEVICEMAP\SERIALCOMM"
            )
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    ports.append({
                        'device': value,
                        'description': name,
                        'manufacturer': '',
                        'hwid': ''
                    })
                    i += 1
                except (OSError, FileNotFoundError):
                    break
            winreg.CloseKey(key)
            log(f"🔍 {len(ports)} port(s) trouvé(s) via registre Windows")
            return jsonify({
                'success': True,
                'ports': ports,
                'method': 'windows_registry'
            })
        except Exception as e:
            log(f"⚠️ Erreur lecture registre Windows: {e}")
    
    # Si aucune méthode n'a fonctionné
    return jsonify({
        'success': False,
        'error': 'Impossible de détecter les ports série. Installez pyserial: pip install pyserial',
        'ports': []
    }), 400

@app.route('/api/read-motor-ids', methods=['POST'])
def read_motor_ids():
    """Détecte les moteurs présents sur un port et lit leurs IDs actuels"""
    data = request.json
    port = data.get('port')
    
    if not port:
        return jsonify({'success': False, 'error': 'Port requis'}), 400
    
    if not SERIAL_AVAILABLE:
        return jsonify({'success': False, 'error': 'pyserial non installé'}), 400
    
    ser = None
    try:
        log(f"🔍 Détection des moteurs sur {port}...")
        ser = serial.Serial(port, STS_DEFAULT_BAUD, timeout=0.5)
        time.sleep(0.1)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        detected_motors = []
        scan_range = list(range(1, 11))
        for motor_id in scan_range:
            if _sts_ping(ser, motor_id):
                detected_motors.append({
                    'current_id': motor_id
                })
                log(f"  ✓ Moteur détecté: ID {motor_id}")
        
        if not detected_motors:
            log("⚠️ Aucun moteur détecté sur ce port")
            return jsonify({
                'success': False,
                'error': 'Aucun moteur détecté sur ce port. Vérifiez la connexion.',
                'detected_motors': []
            }), 400
        
        log(f"✓ {len(detected_motors)} moteur(s) détecté(s)")
        
        return jsonify({
            'success': True,
            'detected_motors': detected_motors
        })
        
    except Exception as e:
        if ser and ser.is_open:
            ser.close()
        error_msg = f'Erreur lors de la détection des moteurs: {str(e)}'
        log(f"❌ {error_msg}")
        return jsonify({
            'success': False,
            'error': error_msg,
            'detected_motors': []
        }), 400
    finally:
        if ser and ser.is_open:
            ser.close()

@app.route('/api/setup-motors', methods=['POST'])
def setup_motors():
    """Modifie de façon permanente l'ID des moteurs détectés"""
    data = request.json
    port = data.get('port')
    motor_id_mappings = data.get('motor_id_mappings', [])  # Liste de {current_id, new_id}
    
    if not port:
        return jsonify({'success': False, 'error': 'Port requis'}), 400
    
    if not SERIAL_AVAILABLE:
        return jsonify({'success': False, 'error': 'pyserial non installé'}), 400
    
    if not motor_id_mappings:
        return jsonify({'success': False, 'error': 'Aucun changement d\'ID demandé'}), 400
    
    current_ids = []
    new_ids = []
    for mapping in motor_id_mappings:
        current_id = int(mapping.get('current_id', 0))
        new_id = int(mapping.get('new_id', 0))
        if current_id < 1 or current_id > 253 or new_id < 1 or new_id > 253:
            return jsonify({'success': False, 'error': 'IDs invalides (1-253)'}), 400
        current_ids.append(current_id)
        new_ids.append(new_id)
    
    if len(set(new_ids)) != len(new_ids):
        return jsonify({'success': False, 'error': 'IDs en doublon dans les nouveaux IDs'}), 400
    
    ser = None
    try:
        log(f"🔧 Modification permanente des IDs sur {port}...")
        for mapping in motor_id_mappings:
            log(f"  ID {mapping['current_id']} → ID {mapping['new_id']}")
        
        ser = serial.Serial(port, STS_DEFAULT_BAUD, timeout=0.5)
        time.sleep(0.1)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        remaining = {int(m['current_id']): int(m['new_id']) for m in motor_id_mappings}
        used_ids = set(current_ids)
        all_ids = set(current_ids + new_ids)
        temp_id = next((i for i in range(1, 254) if i not in all_ids), None)
        
        def apply_change(old_id, new_id):
            ok, err = _sts_change_id(ser, old_id, new_id)
            if not ok:
                raise RuntimeError(f"ID {old_id} → {new_id} échoué: {err}")
        
        while remaining:
            progress = False
            for old_id, new_id in list(remaining.items()):
                if new_id not in remaining:
                    apply_change(old_id, new_id)
                    used_ids.discard(old_id)
                    used_ids.add(new_id)
                    del remaining[old_id]
                    progress = True
            if progress:
                continue
            if temp_id is None:
                return jsonify({'success': False, 'error': 'Conflit d\'IDs. Changez un moteur à la fois.'}), 400
            old_id, new_id = next(iter(remaining.items()))
            apply_change(old_id, temp_id)
            del remaining[old_id]
            remaining[temp_id] = new_id
            used_ids.discard(old_id)
            used_ids.add(temp_id)
        
        return jsonify({
            'success': True,
            'message': f'IDs modifiés avec succès sur {port}'
        })
    except Exception as e:
        error_msg = f'Erreur lors du changement d\'ID: {str(e)}'
        log(f"❌ {error_msg}")
        return jsonify({'success': False, 'error': error_msg}), 400
    finally:
        if ser and ser.is_open:
            ser.close()

@app.before_request
def before_request():
    """Vérifie et recharge les modules avant chaque requête en mode debug"""
    # Ne recharger que si on n'est pas déjà en train de recharger
    # pour éviter les boucles infinies
    if app.debug and not hasattr(app, '_reloading'):
        try:
            app._reloading = True
            check_and_reload_modules()
        finally:
            app._reloading = False

if __name__ == '__main__':
    log("🤖 SO-ARM101 Controller Web")
    log("   Documentation: https://huggingface.co/docs/lerobot/so101")
    if LEROBOT_AVAILABLE:
        log("✓ LeRobot disponible")
    else:
        log("❌ LeRobot non disponible")
    
    log("🔄 Mode rechargement automatique activé")
    log("   Modifiez les fichiers Python et actualisez la page web")
    log("   Les modules seront rechargés automatiquement sans redémarrer le serveur")
    
    # Initialiser les timestamps
    for module_name, filepath in _module_paths.items():
        if filepath.exists():
            _module_timestamps[module_name] = filepath.stat().st_mtime
    
    # Lancer avec rechargement automatique activé
    # Note: use_reloader=False pour éviter que Flask redémarre le serveur
    # On gère le rechargement manuellement avec notre système
    app.run(
        debug=True,
        host='0.0.0.0',
        port=5000,
        use_reloader=False,  # Désactivé pour permettre le rechargement à chaud manuel
        use_debugger=True
    )

