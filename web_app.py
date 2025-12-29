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

