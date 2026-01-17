"""
Application Web pour le contrôle du bras robotique SO-ARM101
Remplace l'interface GUI Tkinter par une interface web moderne
Support du rechargement à chaud des modules Python
"""

from flask import Flask, render_template, jsonify, request, send_from_directory
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

# Dictionnaire pour stocker les modules chargés et leurs chemins
_loaded_modules = {
    'config': sys.modules['config'],
    'normalization': sys.modules['normalization'],
    'motor_control': sys.modules['motor_control'],
    'calibration': sys.modules['calibration'],
    'recording': sys.modules['recording'],
}

# Chemins des fichiers de modules
_module_paths = {
    'config': Path('config.py'),
    'normalization': Path('normalization.py'),
    'motor_control': Path('motor_control.py'),
    'calibration': Path('calibration.py'),
    'recording': Path('recording.py'),
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

# État global de l'application
app_state = {
    'motors': None,
    'is_connected': False,
    'port': 'COM3',
    'motor_controller': None,
    'calibration_manager': None,
    'recording_manager': None,
    'pending_positions': {},
    'position_sender_running': False,
    'torque_enabled_for_sliders': set(),
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

# Routes API
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    """Retourne le statut de connexion"""
    return jsonify({
        'success': True,
        'connected': app_state['is_connected'],
        'port': app_state['port'],
        'lerobot_available': LEROBOT_AVAILABLE
    })

@app.route('/api/connect', methods=['POST'])
def connect():
    """Connecte ou déconnecte le robot"""
    data = request.json
    port = data.get('port', 'COM3')
    
    if not app_state['is_connected']:
        if not LEROBOT_AVAILABLE:
            return jsonify({'success': False, 'error': 'LeRobot non installé'}), 400
        
        try:
            log(f"🔌 Connexion sur {port}...")
            
            motor_config = {
                name: Motor(id=motor_id, model="sts3215", norm_mode=MotorNormMode.RANGE_0_100)
                for name, motor_id in zip(MOTOR_NAMES, MOTOR_IDS)
            }
            
            app_state['motors'] = FeetechMotorsBus(port=port, motors=motor_config)
            app_state['motors'].connect()
            
            app_state['is_connected'] = True
            app_state['port'] = port
            
            app_state['motor_controller'] = MotorController(app_state['motors'], log)
            app_state['calibration_manager'] = CalibrationManager(app_state['motors'], log)
            app_state['recording_manager'] = RecordingManager(app_state['motors'], log)
            
            app_state['calibration_manager'].load_calibration_from_file()
            
            log(f"✓ Connecté via LeRobot FeetechMotorsBus")
            
            return jsonify({'success': True})
            
        except Exception as e:
            log(f"❌ Erreur: {e}")
            return jsonify({'success': False, 'error': str(e)}), 400
    else:
        # Déconnexion
        if app_state['motors']:
            try:
                app_state['motors'].disconnect()
            except:
                pass
        
        app_state['motors'] = None
        app_state['motor_controller'] = None
        app_state['calibration_manager'] = None
        app_state['recording_manager'] = None
        app_state['is_connected'] = False
        app_state['position_sender_running'] = False
        app_state['pending_positions'] = {}
        app_state['torque_enabled_for_sliders'] = set()
        
        log("✓ Déconnecté")
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
    """Calibration automatique"""
    if not app_state['is_connected']:
        return jsonify({'success': False, 'error': 'Non connecté'}), 400
    
    data = request.json
    motors = data.get('motors', MOTOR_NAMES)
    
    def calibration_thread():
        for motor_name in motors:
            if motor_name not in MOTOR_NAMES:
                continue
            
            motor_id = MOTOR_IDS[MOTOR_NAMES.index(motor_name)]
            app_state['calibration_manager'].calibrate_motor_auto(motor_name, motor_id, log)
        
        app_state['calibration_manager'].save_calibration_to_file()
    
    threading.Thread(target=calibration_thread, daemon=True).start()
    
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

