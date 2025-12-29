"""
Création des widgets de l'interface graphique
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import time

from config import MOTOR_NAMES, MOTOR_IDS, LEROBOT_AVAILABLE


def create_connection_frame(parent, port_var, connect_callback):
    """Crée le frame de connexion"""
    frame_conn = ttk.LabelFrame(parent, text="Connexion LeRobot", padding=10)
    frame_conn.pack(fill=tk.X, padx=10, pady=5)
    
    ttk.Label(frame_conn, text="Port:").grid(row=0, column=0, padx=5, pady=5)
    ttk.Entry(frame_conn, textvariable=port_var, width=15).grid(row=0, column=1, padx=5, pady=5)
    
    btn_connect = ttk.Button(frame_conn, text="Connecter", command=connect_callback)
    btn_connect.grid(row=0, column=2, padx=5, pady=5)
    
    status_label = ttk.Label(frame_conn, text="Déconnecté", foreground="red")
    status_label.grid(row=0, column=3, padx=20, pady=5)
    
    return frame_conn, btn_connect, status_label


def create_control_frame(parent, callbacks):
    """Crée le frame de contrôle"""
    frame_control = ttk.LabelFrame(parent, text="Contrôle", padding=10)
    frame_control.pack(fill=tk.X, padx=10, pady=5)
    
    ttk.Button(frame_control, text="📊 Lire Positions", command=callbacks['read_positions']).grid(row=0, column=0, padx=5, pady=5)
    ttk.Button(frame_control, text="🔓 Relâcher Moteurs", command=callbacks['release_motors']).grid(row=0, column=1, padx=5, pady=5)
    ttk.Button(frame_control, text="🔒 Verrouiller Moteurs", command=callbacks['lock_motors']).grid(row=0, column=2, padx=5, pady=5)
    ttk.Button(frame_control, text="🏠 Position Home", command=callbacks['go_home']).grid(row=0, column=3, padx=5, pady=5)
    
    return frame_control


def create_recording_frame(parent, callbacks):
    """Crée le frame d'enregistrement/lecture"""
    frame_rec = ttk.LabelFrame(parent, text="Enregistrement / Lecture", padding=10)
    frame_rec.pack(fill=tk.X, padx=10, pady=5)
    
    ttk.Label(frame_rec, text="Intervalle (ms):").grid(row=0, column=0, padx=5, pady=5)
    sample_interval = tk.IntVar(value=100)
    ttk.Entry(frame_rec, textvariable=sample_interval, width=8).grid(row=0, column=1, padx=5, pady=5)
    
    btn_record = ttk.Button(frame_rec, text="⏺ Enregistrer", command=callbacks['start_recording'])
    btn_record.grid(row=0, column=2, padx=5, pady=5)
    
    btn_stop_record = ttk.Button(frame_rec, text="⏹ Stop", command=callbacks['stop_recording'], state=tk.DISABLED)
    btn_stop_record.grid(row=0, column=3, padx=5, pady=5)
    
    ttk.Button(frame_rec, text="💾 Sauvegarder", command=callbacks['save_recording']).grid(row=1, column=0, padx=5, pady=5)
    ttk.Button(frame_rec, text="📂 Charger", command=callbacks['load_recording']).grid(row=1, column=1, padx=5, pady=5)
    
    btn_play = ttk.Button(frame_rec, text="▶ Lire", command=callbacks['play_recording'])
    btn_play.grid(row=1, column=2, padx=5, pady=5)
    
    btn_stop_play = ttk.Button(frame_rec, text="⏸ Stop Lecture", command=callbacks['stop_playback'], state=tk.DISABLED)
    btn_stop_play.grid(row=1, column=3, padx=5, pady=5)
    
    record_status = ttk.Label(frame_rec, text="")
    record_status.grid(row=2, column=0, columnspan=4, pady=5)
    
    return frame_rec, sample_interval, btn_record, btn_stop_record, btn_play, btn_stop_play, record_status


def create_tools_frame(parent, callbacks):
    """Crée le frame des outils LeRobot"""
    frame_tools = ttk.LabelFrame(parent, text="Outils LeRobot (ligne de commande)", padding=10)
    frame_tools.pack(fill=tk.X, padx=10, pady=5)
    
    ttk.Button(frame_tools, text="🔧 Setup Moteurs", command=callbacks['setup_motors']).grid(row=0, column=0, padx=5, pady=5)
    ttk.Button(frame_tools, text="📐 Calibrer", command=callbacks['calibrate']).grid(row=0, column=1, padx=5, pady=5)
    ttk.Button(frame_tools, text="🔍 Trouver Port", command=callbacks['find_port']).grid(row=0, column=2, padx=5, pady=5)
    
    return frame_tools


def create_sliders_frame(parent, slider_change_callback, slider_toggle_callback, refresh_callback, slider_enabled=None):
    """Crée le frame des sliders de contrôle manuel"""
    frame_sliders = ttk.LabelFrame(parent, text="Contrôle Manuel des Moteurs (Calibré)", padding=10)
    frame_sliders.pack(fill=tk.X, padx=10, pady=5)
    
    if slider_enabled is None:
        slider_enabled = tk.BooleanVar(value=False)
    motor_sliders = {}
    motor_labels = {}
    motor_calib_labels = {}
    
    # En-tête
    header_frame = ttk.Frame(frame_sliders)
    header_frame.pack(fill=tk.X, pady=2)
    ttk.Label(header_frame, text="ID", width=3, font=("Arial", 8, "bold")).pack(side=tk.LEFT)
    ttk.Label(header_frame, text="Moteur", width=12, font=("Arial", 8, "bold")).pack(side=tk.LEFT)
    ttk.Label(header_frame, text="Gauche ◀", width=8, font=("Arial", 8), foreground="blue").pack(side=tk.LEFT)
    ttk.Label(header_frame, text="Slider (0-100%)", width=20, font=("Arial", 8, "bold")).pack(side=tk.LEFT, padx=20)
    ttk.Label(header_frame, text="▶ Droite", width=8, font=("Arial", 8), foreground="red").pack(side=tk.LEFT)
    ttk.Label(header_frame, text="Position", width=8, font=("Arial", 8, "bold")).pack(side=tk.LEFT, padx=5)
    ttk.Label(header_frame, text="Brut", width=6, font=("Arial", 8)).pack(side=tk.LEFT)
    
    for name, motor_id in zip(MOTOR_NAMES, MOTOR_IDS):
        row_frame = ttk.Frame(frame_sliders)
        row_frame.pack(fill=tk.X, pady=1)
        
        ttk.Label(row_frame, text=str(motor_id), width=3, font=("Consolas", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(row_frame, text=f"{name}", width=12).pack(side=tk.LEFT)
        
        left_label = ttk.Label(row_frame, text="---", width=6, foreground="blue", font=("Consolas", 9))
        left_label.pack(side=tk.LEFT, padx=2)
        
        slider = ttk.Scale(row_frame, from_=0, to=100, orient=tk.HORIZONTAL, length=180,
                          command=lambda v, n=name: slider_change_callback(n, v))
        slider.set(50)
        slider.pack(side=tk.LEFT, padx=5)
        motor_sliders[name] = slider
        
        right_label = ttk.Label(row_frame, text="---", width=6, foreground="red", font=("Consolas", 9))
        right_label.pack(side=tk.LEFT, padx=2)
        
        pct_label = ttk.Label(row_frame, text="50%", width=5, font=("Consolas", 9, "bold"))
        pct_label.pack(side=tk.LEFT, padx=5)
        motor_labels[name] = pct_label
        
        raw_label = ttk.Label(row_frame, text="---", width=6, font=("Consolas", 8), foreground="gray")
        raw_label.pack(side=tk.LEFT)
        
        motor_calib_labels[name] = {
            'left': left_label,
            'right': right_label,
            'raw': raw_label
        }
    
    # Ligne de contrôle
    control_frame = ttk.Frame(frame_sliders)
    control_frame.pack(fill=tk.X, pady=5)
    
    slider_checkbox = ttk.Checkbutton(control_frame, text="✓ Activer contrôle par sliders", 
                   variable=slider_enabled, command=slider_toggle_callback)
    slider_checkbox.pack(side=tk.LEFT, padx=10)
    
    ttk.Button(control_frame, text="↻ Rafraîchir calibration", 
              command=refresh_callback).pack(side=tk.LEFT, padx=10)
    
    ttk.Label(control_frame, text="(Les sliders utilisent la calibration chargée)", 
             foreground="gray", font=("Arial", 8)).pack(side=tk.LEFT, padx=10)
    
    return frame_sliders, None, motor_sliders, motor_labels, motor_calib_labels


def create_debug_frame(parent, motors_bus, log_callback):
    """Crée le frame de debug"""
    frame_debug = ttk.LabelFrame(parent, text="Outils de Debug (Bypass Calibration)", padding=10)
    frame_debug.pack(fill=tk.X, padx=10, pady=5)
    
    ttk.Label(frame_debug, text="Moteur:").pack(side=tk.LEFT)
    debug_motor_var = tk.StringVar(value="gripper")
    motor_cb = ttk.Combobox(frame_debug, textvariable=debug_motor_var, values=MOTOR_NAMES, width=12)
    motor_cb.pack(side=tk.LEFT, padx=5)
    
    ttk.Label(frame_debug, text="Pos (0-4095):").pack(side=tk.LEFT)
    debug_val = tk.IntVar(value=2048)
    ttk.Entry(frame_debug, textvariable=debug_val, width=8).pack(side=tk.LEFT, padx=5)
    
    # Variable pour suivre si un mouvement continu est en cours
    continuous_movement_running = {"active": False, "direction": 0}
    
    def send_raw():
        m = debug_motor_var.get()
        v = debug_val.get()
        try:
            motors_bus.write("Torque_Enable", m, 1, normalize=False)
            motors_bus.write("Goal_Position", m, v, normalize=False)
            log_callback(f"CMD > {m}: {v}")
        except Exception as e:
            log_callback(f"ERR > {e}")
    
    def move_until_limit(direction):
        """Mouvement progressif jusqu'à la butée, par petits pas"""
        m = debug_motor_var.get()
        
        # Arrêter le mouvement précédent
        if continuous_movement_running["active"]:
            continuous_movement_running["active"] = False
            time.sleep(0.2)
        
        continuous_movement_running["active"] = True
        
        def movement_thread():
            motor_name = m
            step = 100  # Pas de déplacement
            
            try:
                # Activer le torque d'abord
                try:
                    motors_bus.write("Torque_Enable", motor_name, 1, normalize=False)
                    time.sleep(0.1)
                except Exception as e:
                    log_callback(f"❌ ERR Torque: {e}")
                    continuous_movement_running["active"] = False
                    return
                
                # Lire position de départ
                try:
                    start_pos = int(motors_bus.read("Present_Position", motor_name, normalize=False))
                    current_pos = start_pos
                except Exception as e:
                    log_callback(f"❌ ERR lecture: {e}")
                    continuous_movement_running["active"] = False
                    return
                
                direction_str = "GAUCHE (diminuer)" if direction < 0 else "DROITE (augmenter)"
                log_callback(f"▶ {motor_name}: {direction_str} depuis {start_pos}")
                log_callback(f"   Pas: {step * direction:+d} par itération")
                
                no_move_count = 0
                iteration = 0
                
                while continuous_movement_running["active"] and no_move_count < 5 and iteration < 50:
                    iteration += 1
                    
                    # IMPORTANT: Relire la position RÉELLE actuelle du moteur
                    try:
                        actual_pos = int(motors_bus.read("Present_Position", motor_name, normalize=False))
                    except:
                        time.sleep(0.05)
                        continue
                    
                    # Calculer nouvelle cible BASÉE SUR LA POSITION RÉELLE
                    goal = actual_pos + (step * direction)
                    goal = max(0, min(4095, goal))  # Limiter aux bornes
                    
                    # Envoyer la cible
                    try:
                        motors_bus.write("Goal_Position", motor_name, goal, normalize=False)
                    except:
                        pass
                    
                    # Attendre le mouvement
                    time.sleep(0.12)
                    
                    # Lire la nouvelle position
                    try:
                        new_pos = int(motors_bus.read("Present_Position", motor_name, normalize=False))
                        debug_val.set(new_pos)
                    except:
                        continue
                    
                    # Calculer le mouvement effectué (depuis la position réelle)
                    move = new_pos - actual_pos
                    
                    # Log (seulement les 5 premières ou si mouvement significatif)
                    if iteration <= 5 or abs(move) > 10:
                        log_callback(f"   [{iteration}] pos_réelle={actual_pos}, goal={goal}, nouvelle={new_pos}, Δ={move:+d})")
                    
                    # Vérifier si on bouge dans la bonne direction
                    if direction > 0:
                        # On veut augmenter
                        if move < 5:  # Pas de mouvement positif
                            no_move_count += 1
                        else:
                            no_move_count = 0
                    else:
                        # On veut diminuer
                        if move > -5:  # Pas de mouvement négatif
                            no_move_count += 1
                        else:
                            no_move_count = 0
                    
                    current_pos = new_pos
                    
                    # Si on atteint les limites du range
                    if goal == 0 or goal == 4095:
                        log_callback(f"   ⚠️ Limite numérique atteinte ({goal})")
                        break
                
                # Résultat final
                total_move = current_pos - start_pos
                log_callback(f"🛑 {motor_name}: Position finale {current_pos}")
                log_callback(f"   Mouvement total: {total_move:+d}")
                
                if abs(total_move) < 20:
                    log_callback(f"   ⚠️ Presque aucun mouvement - déjà à la butée?")
                elif (total_move > 0 and direction > 0) or (total_move < 0 and direction < 0):
                    log_callback(f"   ✅ Mouvement correct dans la direction demandée!")
                else:
                    log_callback(f"   ⚠️ Mouvement dans la direction opposée!")
                
            except Exception as e:
                log_callback(f"❌ ERR: {e}")
            finally:
                continuous_movement_running["active"] = False
        
        threading.Thread(target=movement_thread, daemon=True).start()
    
    def inc_raw(delta):
        """Ancienne fonction pour mouvement par pas (conservée pour compatibilité)"""
        v = debug_val.get() + delta
        if v < 0: v += 4096
        if v > 4095: v -= 4096
        debug_val.set(v)
        send_raw()
    
    ttk.Button(frame_debug, text="GO", command=send_raw).pack(side=tk.LEFT, padx=5)
    
    def stop_movement():
        if continuous_movement_running["active"]:
            continuous_movement_running["active"] = False
            log_callback("⏹ Mouvement arrêté par l'utilisateur")
        else:
            log_callback("ℹ️ Aucun mouvement en cours")
    
    # Note: le gripper a son sens inversé (+ va vers -, - va vers +)
    ttk.Button(frame_debug, text="◀ Butée GAUCHE", command=lambda: move_until_limit(+1)).pack(side=tk.LEFT, padx=2)
    ttk.Button(frame_debug, text="▶ Butée DROITE", command=lambda: move_until_limit(-1)).pack(side=tk.LEFT, padx=2)
    ttk.Button(frame_debug, text="⏹ Arrêter", command=stop_movement).pack(side=tk.LEFT, padx=2)
    
    ttk.Label(frame_debug, text=" | ").pack(side=tk.LEFT, padx=5)
    
    def read_raw():
        m = debug_motor_var.get()
        try:
            p = motors_bus.read("Present_Position", m, normalize=False)
            log_callback(f"READ < {m}: {p}")
            debug_val.set(int(p))
        except Exception as e:
            log_callback(f"ERR < {e}")
    
    ttk.Button(frame_debug, text="LIRE", command=read_raw).pack(side=tk.LEFT, padx=5)
    
    return frame_debug


def create_log_frame(parent, log_callback=None):
    """Crée le frame de log"""
    frame_log = ttk.LabelFrame(parent, text="Journal", padding=10)
    frame_log.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
    
    log_text = scrolledtext.ScrolledText(frame_log, height=12, wrap=tk.WORD)
    log_text.pack(fill=tk.BOTH, expand=True)
    
    # Message de bienvenue (seulement si callback fourni)
    # Note: Le callback sera appelé après que log_text soit assigné dans robot_gui.py
    if log_callback:
        log_callback("🤖 SO-ARM101 Controller avec LeRobot")
        log_callback("   Documentation: https://huggingface.co/docs/lerobot/so101")
        if LEROBOT_AVAILABLE:
            log_callback("✓ LeRobot disponible")
        else:
            log_callback("❌ LeRobot non disponible")
            log_callback("")
            log_callback("Pour installer:")
            log_callback("  1. conda activate lerobot")
            log_callback("  2. pip install lerobot[feetech]")
            log_callback("  3. python robot_gui.py")
    
    return frame_log, log_text

