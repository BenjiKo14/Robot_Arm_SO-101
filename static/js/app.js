// Application JavaScript pour le contrôleur SO-ARM101

const MOTOR_NAMES = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper'];
const MOTOR_IDS = [1, 2, 3, 4, 5, 6];

let sliderEnabled = false;
let updateInterval = null;
let logUpdateInterval = null;

// Initialisation
document.addEventListener('DOMContentLoaded', () => {
    initializeUI();
    startStatusUpdates();
    startLogUpdates();
});

function initializeUI() {
    // Connexion
    document.getElementById('connect-btn').addEventListener('click', toggleConnection);
    
    // Contrôle
    document.getElementById('read-positions-btn').addEventListener('click', readPositions);
    document.getElementById('release-btn').addEventListener('click', releaseMotors);
    document.getElementById('lock-btn').addEventListener('click', lockMotors);
    document.getElementById('home-btn').addEventListener('click', goHome);
    
    // Sliders
    document.getElementById('slider-enable-checkbox').addEventListener('change', toggleSliders);
    document.getElementById('refresh-calib-btn').addEventListener('click', refreshCalibration);
    createSliders();
    
    // Enregistrement
    document.getElementById('record-btn').addEventListener('click', startRecording);
    document.getElementById('stop-record-btn').addEventListener('click', stopRecording);
    document.getElementById('save-btn').addEventListener('click', saveRecording);
    document.getElementById('load-btn').addEventListener('click', loadRecording);
    document.getElementById('play-btn').addEventListener('click', playRecording);
    document.getElementById('stop-play-btn').addEventListener('click', stopPlayback);
    
    // Outils
    document.getElementById('setup-motors-btn').addEventListener('click', setupMotors);
    document.getElementById('calibrate-btn').addEventListener('click', openCalibrationModal);
    document.getElementById('find-port-btn').addEventListener('click', findPort);
    
    // Modal
    const modal = document.getElementById('calibration-modal');
    const closeBtn = modal.querySelector('.close');
    closeBtn.addEventListener('click', () => {
        modal.style.display = 'none';
    });
    
    window.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.style.display = 'none';
        }
    });
    
    // Tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            switchTab(tab);
        });
    });
    
    // Calibration
    document.getElementById('start-auto-calib-btn').addEventListener('click', startAutoCalibration);
    document.getElementById('release-all-btn').addEventListener('click', releaseAllMotors);
    document.getElementById('lock-all-btn').addEventListener('click', lockAllMotors);
    
    setupManualCalibration();
}

function createSliders() {
    const container = document.getElementById('sliders-container');
    container.innerHTML = '';
    
    MOTOR_NAMES.forEach((name, index) => {
        const row = document.createElement('div');
        row.className = 'slider-row';
        row.innerHTML = `
            <div class="motor-id">${MOTOR_IDS[index]}</div>
            <div class="motor-name">${name}</div>
            <div class="calib-value left" id="calib-left-${name}">---</div>
            <input type="range" class="slider-input" id="slider-${name}" min="0" max="100" value="50" step="1">
            <div class="calib-value right" id="calib-right-${name}">---</div>
            <div class="position-value" id="position-${name}">50%</div>
            <div class="raw-value" id="raw-${name}">---</div>
        `;
        container.appendChild(row);
        
        const slider = document.getElementById(`slider-${name}`);
        slider.addEventListener('input', (e) => {
            updateSliderPosition(name, e.target.value);
        });
    });
}

function updateSliderPosition(motorName, value) {
    if (!sliderEnabled) return;
    
    document.getElementById(`position-${motorName}`).textContent = `${value}%`;
    
    fetch('/api/slider/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motor: motorName, value: value })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            document.getElementById(`raw-${motorName}`).textContent = data.raw;
        }
    })
    .catch(err => console.error('Erreur slider:', err));
}

function toggleSliders(e) {
    sliderEnabled = e.target.checked;
    
    fetch('/api/slider/enable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: sliderEnabled })
    })
    .then(res => res.json())
    .then(data => {
        if (!data.success) {
            sliderEnabled = false;
            e.target.checked = false;
        }
    });
}

async function toggleConnection() {
    const btn = document.getElementById('connect-btn');
    const port = document.getElementById('port-input').value;
    
    try {
        const res = await fetch('/api/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ port: port })
        });
        
        const data = await res.json();
        
        if (data.success) {
            appState.is_connected = !appState.is_connected;
            updateConnectionStatus(appState.is_connected);
        } else {
            alert('Erreur: ' + data.error);
        }
    } catch (err) {
        alert('Erreur de connexion: ' + err.message);
    }
}

async function updateConnectionStatus(connected) {
    const statusText = document.getElementById('status-text');
    const btn = document.getElementById('connect-btn');
    
    if (connected) {
        statusText.textContent = `Connecté sur ${appState.port}`;
        statusText.className = 'status-connected';
        btn.textContent = 'Déconnecter';
    } else {
        statusText.textContent = 'Déconnecté';
        statusText.className = 'status-disconnected';
        btn.textContent = 'Connecter';
    }
}

async function readPositions() {
    try {
        const res = await fetch('/api/positions');
        const data = await res.json();
        
        if (data.success) {
            MOTOR_NAMES.forEach(name => {
                const pos = data.positions[name];
                document.getElementById(`slider-${name}`).value = pos.percent;
                document.getElementById(`position-${name}`).textContent = `${pos.percent}%`;
                document.getElementById(`raw-${name}`).textContent = pos.raw;
            });
        }
    } catch (err) {
        console.error('Erreur lecture positions:', err);
    }
}

async function releaseMotors() {
    await fetch('/api/motors/release', { method: 'POST' });
}

async function lockMotors() {
    await fetch('/api/motors/lock', { method: 'POST' });
}

async function goHome() {
    await fetch('/api/motors/home', { method: 'POST' });
}

async function refreshCalibration() {
    try {
        const res = await fetch('/api/calibration/info');
        const data = await res.json();
        
        if (data.success) {
            MOTOR_NAMES.forEach(name => {
                const calib = data.calibrations[name];
                if (calib.pos_left !== null) {
                    document.getElementById(`calib-left-${name}`).textContent = calib.pos_left;
                }
                if (calib.pos_right !== null) {
                    document.getElementById(`calib-right-${name}`).textContent = calib.pos_right;
                }
            });
        }
    } catch (err) {
        console.error('Erreur refresh calibration:', err);
    }
}

async function startRecording() {
    const interval = parseInt(document.getElementById('interval-input').value);
    
    try {
        await fetch('/api/recording/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interval: interval })
        });
        
        document.getElementById('record-btn').disabled = true;
        document.getElementById('stop-record-btn').disabled = false;
    } catch (err) {
        alert('Erreur: ' + err.message);
    }
}

async function stopRecording() {
    await fetch('/api/recording/stop', { method: 'POST' });
    document.getElementById('record-btn').disabled = false;
    document.getElementById('stop-record-btn').disabled = true;
}

async function saveRecording() {
    const interval = parseInt(document.getElementById('interval-input').value);
    
    try {
        const res = await fetch('/api/recording/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interval: interval })
        });
        
        const data = await res.json();
        if (data.success) {
            alert(`Enregistrement sauvegardé: ${data.filename}`);
        }
    } catch (err) {
        alert('Erreur: ' + err.message);
    }
}

function loadRecording() {
    // Déclencher le sélecteur de fichiers
    const fileInput = document.getElementById('file-input');
    fileInput.click();
}

// Gérer la sélection de fichier
document.getElementById('file-input').addEventListener('change', async function(e) {
    const file = e.target.files[0];
    if (!file) {
        return;
    }
    
    // Vérifier que c'est un fichier JSON
    if (!file.name.endsWith('.json')) {
        alert('Veuillez sélectionner un fichier JSON');
        e.target.value = '';
        return;
    }
    
    try {
        // Lire le fichier
        const reader = new FileReader();
        reader.onload = async function(event) {
            try {
                const fileContent = JSON.parse(event.target.result);
                
                // Valider la structure basique
                if (!fileContent || typeof fileContent !== 'object') {
                    throw new Error('Format de fichier invalide');
                }
                
                // Envoyer le contenu au serveur
                const res = await fetch('/api/recording/load', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        filename: file.name,
                        content: fileContent 
                    })
                });
                
                const data = await res.json();
                if (data.success) {
                    showNotification(`✓ Fichier chargé: ${file.name} (${data.frames} frames)`, 'success');
                } else {
                    alert('Erreur: ' + (data.error || 'Erreur inconnue'));
                }
            } catch (parseErr) {
                alert('Erreur lors de la lecture du fichier JSON: ' + parseErr.message);
            }
        };
        
        reader.onerror = function() {
            alert('Erreur lors de la lecture du fichier');
            e.target.value = '';
        };
        
        reader.readAsText(file);
    } catch (err) {
        alert('Erreur: ' + err.message);
        e.target.value = '';
    }
    
    // Réinitialiser l'input pour permettre de sélectionner le même fichier à nouveau
    // (fait après le chargement pour éviter les problèmes)
});

async function playRecording() {
    try {
        const res = await fetch('/api/recording/play', { method: 'POST' });
        const data = await res.json();
        
        if (!data.success) {
            alert('Erreur: ' + (data.error || 'Erreur inconnue'));
            return;
        }
        
        document.getElementById('play-btn').disabled = true;
        document.getElementById('stop-play-btn').disabled = false;
        
        // Afficher la barre de progression
        const progressContainer = document.getElementById('playback-progress-container');
        if (progressContainer) {
            progressContainer.style.display = 'block';
            
            // Initialiser la barre à 0%
            const progressBar = document.getElementById('progress-bar');
            const progressText = document.getElementById('progress-text');
            const progressPercent = document.getElementById('progress-percent');
            
            if (progressBar) progressBar.style.width = '0%';
            if (progressText) progressText.textContent = '0 / 0 frames';
            if (progressPercent) progressPercent.textContent = '0%';
        }
        
        // Attendre un peu pour que le serveur démarre la lecture
        setTimeout(() => {
            // Démarrer la mise à jour de la progression
            startProgressUpdate();
        }, 100);
    } catch (err) {
        alert('Erreur: ' + err.message);
    }
}

async function stopPlayback() {
    await fetch('/api/recording/stop_playback', { method: 'POST' });
    document.getElementById('play-btn').disabled = false;
    document.getElementById('stop-play-btn').disabled = true;
    
    // Cacher la barre de progression
    document.getElementById('playback-progress-container').style.display = 'none';
    
    // Arrêter la mise à jour de la progression
    stopProgressUpdate();
}

let progressUpdateInterval = null;

function startProgressUpdate() {
    // Arrêter l'ancien intervalle s'il existe
    if (progressUpdateInterval) {
        clearInterval(progressUpdateInterval);
    }
    
    // Mettre à jour immédiatement
    updateProgress();
    
    // Puis toutes les 100ms pendant la lecture
    progressUpdateInterval = setInterval(updateProgress, 100);
    console.log('🔄 Démarrage du suivi de progression');
}

function stopProgressUpdate() {
    if (progressUpdateInterval) {
        clearInterval(progressUpdateInterval);
        progressUpdateInterval = null;
    }
    
    // Réinitialiser la barre
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-text').textContent = '0 / 0 frames';
    document.getElementById('progress-percent').textContent = '0%';
}

async function updateProgress() {
    try {
        const res = await fetch('/api/recording/status');
        if (!res.ok) {
            console.error('Erreur HTTP:', res.status);
            return;
        }
        
        const data = await res.json();
        const progressContainer = document.getElementById('playback-progress-container');
        
        if (!progressContainer) {
            console.error('Élément playback-progress-container non trouvé');
            return;
        }
        
        const currentFrame = data.current_frame || 0;
        const totalFrames = data.frames || 0;
        const progress = data.progress || 0;
        
        if (data.is_playing) {
            // Vérifier si la lecture est terminée (100% ou dernière frame atteinte)
            if (totalFrames > 0 && (currentFrame >= totalFrames || progress >= 100)) {
                // Lecture terminée automatiquement
                console.log('✓ Lecture terminée automatiquement');
                
                // Mettre la barre à 100%
                const progressBar = document.getElementById('progress-bar');
                const progressText = document.getElementById('progress-text');
                const progressPercent = document.getElementById('progress-percent');
                
                if (progressBar) progressBar.style.width = '100%';
                if (progressText) progressText.textContent = `${totalFrames} / ${totalFrames} frames`;
                if (progressPercent) progressPercent.textContent = '100%';
                
                // Arrêter la lecture comme si on avait cliqué sur "Stop Lecture"
                await stopPlayback();
                
                // Garder la barre visible pendant 1 seconde puis la cacher
                setTimeout(() => {
                    if (progressContainer) progressContainer.style.display = 'none';
                }, 1000);
                
                return;
            }
            
            // Mettre à jour la barre de progression
            const progressBar = document.getElementById('progress-bar');
            const progressText = document.getElementById('progress-text');
            const progressPercent = document.getElementById('progress-percent');
            
            if (progressBar) progressBar.style.width = progress + '%';
            if (progressText) progressText.textContent = `${currentFrame} / ${totalFrames} frames`;
            if (progressPercent) progressPercent.textContent = `${Math.round(progress)}%`;
            
            progressContainer.style.display = 'block';
        } else {
            // La lecture est arrêtée (manuellement ou terminée)
            if (currentFrame === 0 || (totalFrames > 0 && currentFrame >= totalFrames)) {
                // Lecture terminée - garder la barre à 100% pendant 1 seconde
                if (totalFrames > 0) {
                    const progressBar = document.getElementById('progress-bar');
                    const progressText = document.getElementById('progress-text');
                    const progressPercent = document.getElementById('progress-percent');
                    
                    if (progressBar) progressBar.style.width = '100%';
                    if (progressText) progressText.textContent = `${totalFrames} / ${totalFrames} frames`;
                    if (progressPercent) progressPercent.textContent = '100%';
                }
                
                setTimeout(() => {
                    if (progressContainer) progressContainer.style.display = 'none';
                    stopProgressUpdate();
                }, 1000);
            } else {
                // Lecture arrêtée manuellement avant la fin
                if (progressContainer) progressContainer.style.display = 'none';
                stopProgressUpdate();
            }
        }
    } catch (err) {
        console.error('Erreur mise à jour progression:', err);
    }
}

function setupMotors() {
    alert('Cette fonctionnalité doit être exécutée dans un terminal séparé.\n\nCommande: lerobot-setup-motors --robot.type=so101_follower --robot.port=COM3');
}

function openCalibrationModal() {
    document.getElementById('calibration-modal').style.display = 'block';
    refreshCalibration();
    setupAutoCalibrationCheckboxes();
}

function switchTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    document.getElementById(`${tabName}-tab`).classList.add('active');
}

function setupAutoCalibrationCheckboxes() {
    const container = document.getElementById('motor-checkboxes');
    container.innerHTML = '';
    
    MOTOR_NAMES.forEach((name, index) => {
        const checkbox = document.createElement('div');
        checkbox.className = 'motor-checkbox';
        checkbox.innerHTML = `
            <input type="checkbox" id="check-${name}" checked>
            <label for="check-${name}">${name} (ID ${MOTOR_IDS[index]})</label>
        `;
        container.appendChild(checkbox);
    });
}

async function startAutoCalibration() {
    const motors = [];
    MOTOR_NAMES.forEach(name => {
        if (document.getElementById(`check-${name}`).checked) {
            motors.push(name);
        }
    });
    
    if (motors.length === 0) {
        alert('Sélectionnez au moins un moteur');
        return;
    }
    
    const logDiv = document.getElementById('auto-calib-log');
    logDiv.innerHTML = '<div>Démarrage de la calibration...</div>';
    
    try {
        await fetch('/api/calibration/auto', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ motors: motors })
        });
        
        // Mettre à jour les logs périodiquement
        const logInterval = setInterval(async () => {
            const logsRes = await fetch('/api/logs');
            const logsData = await logsRes.json();
            if (logsData.success) {
                const recentLogs = logsData.logs.slice(-20);
                logDiv.innerHTML = recentLogs.map(log => 
                    `<div>[${log.time}] ${log.message}</div>`
                ).join('');
                logDiv.scrollTop = logDiv.scrollHeight;
            }
        }, 1000);
        
        setTimeout(() => clearInterval(logInterval), 60000);
    } catch (err) {
        alert('Erreur: ' + err.message);
    }
}

function setupManualCalibration() {
    const container = document.getElementById('manual-calib-container');
    container.innerHTML = '';
    
    MOTOR_NAMES.forEach((name, index) => {
        const row = document.createElement('div');
        row.className = 'manual-motor-row';
        row.innerHTML = `
            <h4>${name} (ID ${MOTOR_IDS[index]})</h4>
            <div class="manual-motor-controls">
                <div class="current-position">
                    <span>Position actuelle: <strong id="manual-pos-${name}">---</strong></span>
                </div>
                <div class="calibration-buttons">
                    <button class="btn btn-small btn-secondary" onclick="recordManualPosition('${name}', 'left')">◀ Gauche</button>
                    <button class="btn btn-small btn-secondary" onclick="recordManualPosition('${name}', 'right')">Droite ▶</button>
                    <button class="btn btn-small btn-secondary" onclick="recordManualPosition('${name}', 'center')">● Milieu</button>
                    <button class="btn btn-small btn-danger" onclick="resetManualCalibration('${name}')">↺ Reset</button>
                </div>
            </div>
            <div class="calibration-values">
                <div class="calib-value-item">
                    <span class="calib-label">◀ Gauche:</span>
                    <span class="calib-value" id="manual-left-${name}">---</span>
                </div>
                <div class="calib-value-item">
                    <span class="calib-label">● Milieu:</span>
                    <span class="calib-value" id="manual-center-${name}">---</span>
                </div>
                <div class="calib-value-item">
                    <span class="calib-label">▶ Droite:</span>
                    <span class="calib-value" id="manual-right-${name}">---</span>
                </div>
            </div>
            <div class="manual-motor-status" id="manual-status-${name}">⏳ En attente</div>
        `;
        container.appendChild(row);
    });
    
    // Charger les valeurs existantes
    loadManualCalibrationValues();
    
    // Mettre à jour les positions périodiquement
    setInterval(updateManualPositions, 500);
}

async function loadManualCalibrationValues() {
    try {
        const res = await fetch('/api/calibration/info');
        const data = await res.json();
        
        if (data.success) {
            MOTOR_NAMES.forEach(name => {
                const calib = data.calibrations[name];
                if (calib) {
                    const leftEl = document.getElementById(`manual-left-${name}`);
                    const centerEl = document.getElementById(`manual-center-${name}`);
                    const rightEl = document.getElementById(`manual-right-${name}`);
                    
                    if (leftEl) leftEl.textContent = calib.pos_left !== null ? calib.pos_left : '---';
                    if (centerEl) centerEl.textContent = calib.pos_center !== null ? calib.pos_center : '---';
                    if (rightEl) rightEl.textContent = calib.pos_right !== null ? calib.pos_right : '---';
                    
                    // Mettre à jour le statut
                    updateManualCalibrationStatus(name, calib);
                }
            });
        }
    } catch (err) {
        console.error('Erreur chargement calibration:', err);
    }
}

function updateManualCalibrationStatus(motorName, calib) {
    const statusDiv = document.getElementById(`manual-status-${motorName}`);
    if (!statusDiv) return;
    
    if (calib.pos_left !== null && calib.pos_right !== null && calib.pos_center !== null) {
        statusDiv.textContent = '✓ Calibré';
        statusDiv.style.color = '#2ecc71';
    } else {
        const missing = [];
        if (calib.pos_left === null) missing.push('Gauche');
        if (calib.pos_right === null) missing.push('Droite');
        if (calib.pos_center === null) missing.push('Milieu');
        statusDiv.textContent = `⏳ Manque: ${missing.join(', ')}`;
        statusDiv.style.color = '#f39c12';
    }
}

async function updateManualPositions() {
    try {
        const res = await fetch('/api/positions');
        const data = await res.json();
        
        if (data.success) {
            MOTOR_NAMES.forEach(name => {
                document.getElementById(`manual-pos-${name}`).textContent = data.positions[name].raw;
            });
        }
    } catch (err) {
        // Ignorer les erreurs silencieusement
    }
}

async function recordManualPosition(motorName, positionType) {
    try {
        const res = await fetch('/api/calibration/manual', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ motor: motorName, type: positionType })
        });
        
        const data = await res.json();
        if (data.success) {
            // Mettre à jour l'affichage de la valeur enregistrée
            const valueEl = document.getElementById(`manual-${positionType}-${motorName}`);
            if (valueEl) {
                valueEl.textContent = data.position;
                valueEl.style.color = '#2ecc71';
                valueEl.style.fontWeight = 'bold';
                
                // Animation de confirmation
                valueEl.style.animation = 'pulse 0.5s ease';
                setTimeout(() => {
                    valueEl.style.animation = '';
                    valueEl.style.color = '';
                    valueEl.style.fontWeight = '';
                }, 500);
            }
            
            // Recharger toutes les valeurs pour mettre à jour le statut
            setTimeout(async () => {
                const calibRes = await fetch('/api/calibration/info');
                const calibData = await calibRes.json();
                if (calibData.success) {
                    const calib = calibData.calibrations[motorName];
                    if (calib) {
                        // Mettre à jour toutes les valeurs affichées
                        const leftEl = document.getElementById(`manual-left-${motorName}`);
                        const centerEl = document.getElementById(`manual-center-${motorName}`);
                        const rightEl = document.getElementById(`manual-right-${motorName}`);
                        
                        if (leftEl) leftEl.textContent = calib.pos_left !== null ? calib.pos_left : '---';
                        if (centerEl) centerEl.textContent = calib.pos_center !== null ? calib.pos_center : '---';
                        if (rightEl) rightEl.textContent = calib.pos_right !== null ? calib.pos_right : '---';
                        
                        // Mettre à jour le statut
                        updateManualCalibrationStatus(motorName, calib);
                    }
                }
            }, 300);
        }
    } catch (err) {
        alert('Erreur: ' + err.message);
    }
}

async function resetManualCalibration(motorName) {
    if (!confirm(`Voulez-vous réinitialiser la calibration de ${motorName} ?`)) {
        return;
    }
    
    try {
        // Réinitialiser les valeurs affichées
        const leftEl = document.getElementById(`manual-left-${motorName}`);
        const centerEl = document.getElementById(`manual-center-${motorName}`);
        const rightEl = document.getElementById(`manual-right-${motorName}`);
        const statusDiv = document.getElementById(`manual-status-${motorName}`);
        
        if (leftEl) leftEl.textContent = '---';
        if (centerEl) centerEl.textContent = '---';
        if (rightEl) rightEl.textContent = '---';
        if (statusDiv) {
            statusDiv.textContent = '⏳ En attente';
            statusDiv.style.color = '#bdc3c7';
        }
        
        // Note: La réinitialisation côté serveur nécessiterait une route API supplémentaire
        // Pour l'instant, on réinitialise juste l'affichage
        showNotification(`Calibration de ${motorName} réinitialisée`, 'info');
    } catch (err) {
        alert('Erreur: ' + err.message);
    }
}

async function releaseAllMotors() {
    await releaseMotors();
}

async function lockAllMotors() {
    await lockMotors();
}

function findPort() {
    alert('Cette fonctionnalité doit être exécutée dans un terminal séparé.\n\nCommande: lerobot-find-port');
}

// Mise à jour périodique du statut
let appState = { is_connected: false, port: 'COM3' };

async function startStatusUpdates() {
    updateInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            
            if (data.success) {
                appState.is_connected = data.connected;
                appState.port = data.port;
                updateConnectionStatus(data.connected);
                
                // Mettre à jour le statut d'enregistrement
                const recRes = await fetch('/api/recording/status');
                const recData = await recRes.json();
                
                if (recData.is_recording) {
                    document.getElementById('record-status').textContent = 
                        `Enregistrement: ${recData.frames} frames`;
                } else {
                    document.getElementById('record-status').textContent = '';
                }
                
                // La progression de la lecture est gérée par updateProgress()
            }
        } catch (err) {
            // Ignorer les erreurs silencieusement
        }
        
        // Vérifier et recharger les modules Python modifiés (en mode debug)
        if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
            try {
                const reloadRes = await fetch('/api/reload', { method: 'POST' });
                const reloadData = await reloadRes.json();
                if (reloadData.success && reloadData.reloaded.length > 0) {
                    console.log('🔄 Modules rechargés:', reloadData.reloaded);
                    // Optionnel: afficher une notification
                    if (reloadData.reloaded.length > 0) {
                        showNotification(`Modules rechargés: ${reloadData.reloaded.join(', ')}`, 'info');
                    }
                }
            } catch (err) {
                // Ignorer silencieusement
            }
        }
    }, 1000);
}

function showNotification(message, type = 'info') {
    // Créer une notification temporaire
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${type === 'info' ? '#3498db' : '#2ecc71'};
        color: white;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        z-index: 10000;
        animation: slideIn 0.3s ease;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Ajouter les animations CSS pour les notifications
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

async function startLogUpdates() {
    logUpdateInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/logs');
            const data = await res.json();
            
            if (data.success) {
                const container = document.getElementById('log-container');
                const recentLogs = data.logs.slice(-50);
                container.innerHTML = recentLogs.map(log => 
                    `<div class="log-entry">
                        <span class="log-time">[${log.time}]</span>
                        <span>${log.message}</span>
                    </div>`
                ).join('');
                container.scrollTop = container.scrollHeight;
            }
        } catch (err) {
            // Ignorer les erreurs silencieusement
        }
    }, 2000);
}

