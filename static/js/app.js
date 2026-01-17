// Application JavaScript pour le contrôleur SO-ARM101

const MOTOR_NAMES = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper'];
const MOTOR_IDS = [1, 2, 3, 4, 5, 6];

let sliderEnabled = false;
let updateInterval = null;
let logUpdateInterval = null;
let manualPositionsInterval = null;
let calibrationModalOpen = false;
let activeCalibrationTab = 'auto';
let logUpdatesForced = false;
let cloneRunning = false;
let cloneStatusInterval = null;
let calibrationTargetRole = 'default';
let calibrationTargetPort = '';

// Initialisation
document.addEventListener('DOMContentLoaded', () => {
    initializeUI();
    fetchInitialStatus();
    updatePollingState();
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

    // Clonage
    document.getElementById('clone-refresh-ports-btn').addEventListener('click', refreshClonePorts);
    document.getElementById('clone-calibrate-leader-btn').addEventListener('click', () => openCalibrationModalForRole('leader'));
    document.getElementById('clone-calibrate-follower-btn').addEventListener('click', () => openCalibrationModalForRole('follower'));
    document.getElementById('clone-toggle-btn').addEventListener('click', toggleClone);
    
    // Modal
    const modal = document.getElementById('calibration-modal');
    const closeBtn = modal.querySelector('.close');
    closeBtn.addEventListener('click', () => {
        modal.style.display = 'none';
        calibrationModalOpen = false;
        calibrationTargetRole = 'default';
        calibrationTargetPort = '';
        updatePollingState();
    });
    
    window.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.style.display = 'none';
            calibrationModalOpen = false;
            calibrationTargetRole = 'default';
            calibrationTargetPort = '';
            updatePollingState();
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
    refreshClonePorts();
}

async function fetchInitialStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        if (data.success) {
            appState.is_connected = data.connected;
            appState.port = data.port;
            updateConnectionStatus(data.connected);
        }
    } catch (err) {
        // Ignorer silencieusement
    } finally {
        updatePollingState();
    }
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
            updatePollingState();
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
        let res;
        if (calibrationTargetRole === 'default') {
            res = await fetch('/api/calibration/info');
        } else {
            res = await fetch('/api/clone/calibration/info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: calibrationTargetRole, port: calibrationTargetPort })
            });
        }
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

async function setupMotors() {
    const btn = document.getElementById('setup-motors-btn');
    const originalText = btn.textContent;
    setLogUpdatesForced(true);
    
    // Désactiver le bouton et afficher un indicateur de chargement
    btn.disabled = true;
    btn.textContent = '🔍 Recherche des ports...';
    
    try {
        // D'abord, récupérer la liste des ports
        const res = await fetch('/api/find-port');
        const data = await res.json();
        
        if (data.success && data.ports.length > 0) {
            // Afficher la modal de sélection de port pour le setup
            showPortSelectionModalForSetup(data.ports);
        } else {
            alert('Aucun port série trouvé.\n\n' + (data.error || 'Vérifiez que votre périphérique est connecté.'));
        }
    } catch (err) {
        alert('Erreur lors de la recherche des ports: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
        if (!document.getElementById('setup-port-selection-modal')?.style?.display || document.getElementById('setup-port-selection-modal').style.display === 'none') {
            setLogUpdatesForced(false);
        }
    }
}

function showPortSelectionModalForSetup(ports) {
    // Créer la modal si elle n'existe pas
    let modal = document.getElementById('setup-port-selection-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'setup-port-selection-modal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 600px;">
                <span class="close-setup-port-modal">&times;</span>
                <h2>🔧 Configuration des Moteurs</h2>
                <p style="margin: 15px 0; color: var(--text-secondary);">
                    Sélectionnez le port série sur lequel configurer les IDs des moteurs.
                </p>
                <div id="setup-port-list" style="margin: 20px 0;"></div>
            </div>
        `;
        document.body.appendChild(modal);
        
        // Gérer la fermeture
        modal.querySelector('.close-setup-port-modal').addEventListener('click', () => {
            modal.style.display = 'none';
            setLogUpdatesForced(false);
        });
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
                setLogUpdatesForced(false);
            }
        });
    }
    
    // Remplir la liste des ports
    const portList = document.getElementById('setup-port-list');
    portList.innerHTML = '';
    
    if (ports.length === 0) {
        portList.innerHTML = '<p>Aucun port trouvé.</p>';
    } else {
        ports.forEach(port => {
            const portItem = document.createElement('div');
            portItem.className = 'port-item';
            
            let portInfo = `<strong>${port.device}</strong>`;
            if (port.description) {
                portInfo += `<span>${port.description}</span>`;
            }
            if (port.manufacturer) {
                portInfo += `<span style="font-size: 0.9em;">${port.manufacturer}</span>`;
            }
            
            portItem.innerHTML = portInfo;
            
            // Sélectionner le port au clic et lancer le setup
            portItem.addEventListener('click', async () => {
                modal.style.display = 'none';
                await executeSetupMotors(port.device);
            });
            
            portList.appendChild(portItem);
        });
    }
    
    // Afficher la modal
    modal.style.display = 'block';
    setLogUpdatesForced(true);
}

async function executeSetupMotors(port) {
    const btn = document.getElementById('setup-motors-btn');
    const originalText = btn.textContent;
    
    // Désactiver le bouton et afficher un indicateur de chargement
    btn.disabled = true;
    btn.textContent = '🔍 Lecture des IDs...';
    
    try {
        // D'abord, lire les IDs actuels
        const readRes = await fetch('/api/read-motor-ids', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ port: port })
        });
        
        const readData = await readRes.json();
        
        if (!readData.success) {
            alert('Erreur lors de la lecture des IDs:\n\n' + (readData.error || 'Erreur inconnue'));
            return;
        }
        
        // Afficher la modal de configuration des IDs
        showMotorIdConfigModal(port, readData);
        
    } catch (err) {
        alert('Erreur lors de la lecture des IDs: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

function showMotorIdConfigModal(port, data) {
    const detectedMotors = data.detected_motors || [];
    
    if (detectedMotors.length === 0) {
        alert('Aucun moteur détecté sur ce port.');
        return;
    }
    
    // Créer la modal si elle n'existe pas
    let modal = document.getElementById('motor-id-config-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'motor-id-config-modal';
        modal.className = 'modal';
        document.body.appendChild(modal);
        
        // Gérer la fermeture
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    }
    
    // Construire le contenu de la modal avec uniquement les moteurs détectés
    let motorRows = '';
    detectedMotors.forEach((motor, index) => {
        const currentId = motor.current_id;
        const motorKey = `motor_${index}`;
        
        motorRows += `
            <div class="motor-id-row" style="display: grid; grid-template-columns: 150px 100px 1fr 100px; align-items: center; gap: 15px; padding: 12px; margin-bottom: 10px; background: rgba(255, 255, 255, 0.05); border-radius: 8px;">
                <div style="font-weight: 500;">Moteur ${index + 1}</div>
                <div style="color: var(--text-secondary);">
                    <span style="font-size: 0.9em;">ID actuel:</span><br>
                    <strong style="color: var(--primary-color); font-size: 1.2em;">${currentId}</strong>
                </div>
                <div style="text-align: center;">
                    <span style="font-size: 0.9em; color: var(--text-secondary);">→</span>
                </div>
                <div>
                    <input type="number" 
                           id="new-id-${motorKey}" 
                           value="${currentId}" 
                           min="1" 
                           max="253" 
                           style="width: 80px; padding: 8px; border-radius: 6px; border: 1px solid var(--border-color); background: rgba(255, 255, 255, 0.1); color: var(--text-primary); font-size: 1em; text-align: center;">
                </div>
            </div>
        `;
    });
    
    modal.innerHTML = `
        <div class="modal-content" style="max-width: 700px;">
            <span class="close-motor-id-modal" style="color: var(--text-secondary); float: right; font-size: 32px; font-weight: bold; cursor: pointer; line-height: 1;">&times;</span>
            <h2>🔧 Configuration des IDs des Moteurs</h2>
            <p style="margin: 15px 0; color: var(--text-secondary);">
                Port: <strong style="color: var(--primary-color);">${port}</strong><br>
                ${detectedMotors.length} moteur(s) détecté(s). Modifiez les IDs si nécessaire, puis cliquez sur "Configurer".
            </p>
            <div style="margin: 20px 0;">
                <div style="display: grid; grid-template-columns: 150px 100px 1fr 100px; align-items: center; gap: 15px; padding: 12px; margin-bottom: 10px; font-weight: bold; border-bottom: 2px solid var(--border-color);">
                    <div>Moteur</div>
                    <div>ID actuel</div>
                    <div></div>
                    <div>Nouvel ID</div>
                </div>
                ${motorRows}
            </div>
            <div style="display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px;">
                <button class="btn btn-secondary" id="cancel-motor-id-btn">Annuler</button>
                <button class="btn btn-primary" id="confirm-motor-id-btn">Configurer</button>
            </div>
        </div>
    `;
    
    // Gérer la fermeture
    modal.querySelector('.close-motor-id-modal').addEventListener('click', () => {
        modal.style.display = 'none';
        setLogUpdatesForced(false);
    });
    
    modal.querySelector('#cancel-motor-id-btn').addEventListener('click', () => {
        modal.style.display = 'none';
        setLogUpdatesForced(false);
    });
    
    // Gérer la confirmation
    modal.querySelector('#confirm-motor-id-btn').addEventListener('click', async () => {
        await confirmAndSetupMotors(port, detectedMotors);
    });
    
    // Afficher la modal
    modal.style.display = 'block';
    setLogUpdatesForced(true);
}

async function confirmAndSetupMotors(port, detectedMotors) {
    const modal = document.getElementById('motor-id-config-modal');
    const btn = document.getElementById('setup-motors-btn');
    const originalText = btn.textContent;
    
    // Récupérer les nouveaux IDs pour chaque moteur détecté
    const motorIdMappings = [];
    detectedMotors.forEach((motor, index) => {
        const motorKey = `motor_${index}`;
        const input = document.getElementById(`new-id-${motorKey}`);
        if (input) {
            const newId = parseInt(input.value);
            const currentId = motor.current_id;
            
            if (newId >= 1 && newId <= 253 && newId !== currentId) {
                // Seulement ajouter si l'ID a changé
                motorIdMappings.push({
                    current_id: currentId,
                    new_id: newId
                });
            }
        }
    });
    
    if (motorIdMappings.length === 0) {
        alert('Aucun changement d\'ID détecté. Les IDs sont déjà corrects.');
        return;
    }
    
    // Confirmation avant de lancer le setup
    const idsList = motorIdMappings.map(m => `ID ${m.current_id} → ID ${m.new_id}`).join('\n');
    if (!confirm(`Voulez-vous modifier les IDs suivants sur ${port} ?\n\n${idsList}\n\nCette opération peut prendre quelques secondes.`)) {
        return;
    }
    
    // Désactiver le bouton et afficher un indicateur de chargement
    btn.disabled = true;
    btn.textContent = '⏳ Configuration en cours...';
    modal.style.display = 'none';
    setLogUpdatesForced(true);
    
    try {
        const res = await fetch('/api/setup-motors', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                port: port,
                motor_id_mappings: motorIdMappings
            })
        });
        
        const data = await res.json();
        
        if (data.success) {
            showNotification(`✓ Configuration réussie sur ${port}`, 'success');
            // Afficher les détails dans les logs si disponibles
            if (data.output) {
                console.log('Sortie de configuration:', data.output);
            }
        } else {
            alert('Erreur lors de la configuration:\n\n' + (data.error || 'Erreur inconnue'));
        }
    } catch (err) {
        alert('Erreur lors de la configuration: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
        setLogUpdatesForced(false);
    }
}

async function refreshClonePorts() {
    const leaderSelect = document.getElementById('clone-leader-port');
    const followerSelect = document.getElementById('clone-follower-port');
    const leaderValue = leaderSelect.value;
    const followerValue = followerSelect.value;

    try {
        const res = await fetch('/api/find-port');
        const data = await res.json();

        if (!data.success) {
            alert('Erreur ports: ' + (data.error || 'Erreur inconnue'));
            return;
        }

        const ports = data.ports || [];
        const options = ['<option value="">-- Sélectionner --</option>']
            .concat(ports.map(p => `<option value="${p.device}">${p.device}</option>`));

        leaderSelect.innerHTML = options.join('');
        followerSelect.innerHTML = options.join('');

        if (ports.some(p => p.device === leaderValue)) {
            leaderSelect.value = leaderValue;
        }
        if (ports.some(p => p.device === followerValue)) {
            followerSelect.value = followerValue;
        }
    } catch (err) {
        alert('Erreur chargement ports: ' + err.message);
    }
}

async function toggleClone() {
    if (cloneRunning) {
        await stopClone();
    } else {
        await startClone();
    }
}

async function startClone() {
    const leaderPort = document.getElementById('clone-leader-port').value;
    const followerPort = document.getElementById('clone-follower-port').value;

    if (!leaderPort || !followerPort) {
        alert('Sélectionnez les ports leader et follower.');
        return;
    }
    if (leaderPort === followerPort) {
        alert('Leader et follower doivent être sur des ports différents.');
        return;
    }

    setLogUpdatesForced(true);
    try {
        const res = await fetch('/api/clone/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ leader_port: leaderPort, follower_port: followerPort })
        });
        const data = await res.json();
        if (!data.success) {
            alert('Erreur clonage: ' + (data.error || 'Erreur inconnue'));
            setLogUpdatesForced(false);
            return;
        }
        cloneRunning = true;
        updateCloneStatusUI(data);
        startCloneStatusUpdates();
    } catch (err) {
        alert('Erreur clonage: ' + err.message);
        setLogUpdatesForced(false);
    }
}

async function stopClone() {
    try {
        const res = await fetch('/api/clone/stop', { method: 'POST' });
        const data = await res.json();
        if (!data.success) {
            alert('Erreur arrêt: ' + (data.error || 'Erreur inconnue'));
            return;
        }
        cloneRunning = false;
        updateCloneStatusUI(data);
        stopCloneStatusUpdates();
        setLogUpdatesForced(false);
    } catch (err) {
        alert('Erreur arrêt: ' + err.message);
    }
}

function startCloneStatusUpdates() {
    if (cloneStatusInterval) return;
    cloneStatusInterval = setInterval(fetchCloneStatus, 1000);
}

function stopCloneStatusUpdates() {
    if (cloneStatusInterval) {
        clearInterval(cloneStatusInterval);
        cloneStatusInterval = null;
    }
}

async function fetchCloneStatus() {
    try {
        const res = await fetch('/api/clone/status');
        const data = await res.json();
        if (data.success) {
            cloneRunning = data.running;
            updateCloneStatusUI(data);
            if (!cloneRunning) {
                stopCloneStatusUpdates();
                setLogUpdatesForced(false);
            }
        }
    } catch (err) {
        // Ignorer
    }
}

function updateCloneStatusUI(data) {
    const statusEl = document.getElementById('clone-status-text');
    const toggleBtn = document.getElementById('clone-toggle-btn');
    if (data && data.running) {
        statusEl.textContent = `Clonage actif (${data.leader_port} → ${data.follower_port})`;
        toggleBtn.textContent = '⏹ Arrêter le clonage';
        toggleBtn.classList.remove('btn-primary');
        toggleBtn.classList.add('btn-danger');
    } else {
        statusEl.textContent = 'Clonage arrêté';
        toggleBtn.textContent = '▶ Démarrer le clonage';
        toggleBtn.classList.add('btn-primary');
        toggleBtn.classList.remove('btn-danger');
    }
}

function openCalibrationModal() {
    calibrationTargetRole = 'default';
    calibrationTargetPort = '';
    document.getElementById('calibration-modal').style.display = 'block';
    calibrationModalOpen = true;
    refreshCalibration();
    setupAutoCalibrationCheckboxes();
    updatePollingState();
}

function openCalibrationModalForRole(role) {
    const leaderPort = document.getElementById('clone-leader-port').value;
    const followerPort = document.getElementById('clone-follower-port').value;
    const port = role === 'leader' ? leaderPort : followerPort;

    if (!port) {
        alert(`Sélectionnez d'abord le port ${role}.`);
        return;
    }

    calibrationTargetRole = role;
    calibrationTargetPort = port;
    document.getElementById('calibration-modal').style.display = 'block';
    calibrationModalOpen = true;
    refreshCalibration();
    setupAutoCalibrationCheckboxes();
    updatePollingState();
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
    activeCalibrationTab = tabName;
    updatePollingState();
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
        if (calibrationTargetRole === 'default') {
            await fetch('/api/calibration/auto', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ motors: motors })
            });
        } else {
            await fetch('/api/clone/calibration/auto', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: calibrationTargetRole, port: calibrationTargetPort, motors: motors })
            });
        }
        
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
    
    // Les mises à jour des positions sont déclenchées uniquement quand utile
}

async function loadManualCalibrationValues() {
    try {
        let res;
        if (calibrationTargetRole === 'default') {
            res = await fetch('/api/calibration/info');
        } else {
            res = await fetch('/api/clone/calibration/info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: calibrationTargetRole, port: calibrationTargetPort })
            });
        }
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
    if (!calibrationModalOpen || activeCalibrationTab !== 'manual') {
        return;
    }
    if (calibrationTargetRole === 'default' && !appState.is_connected) {
        return;
    }
    try {
        let res;
        if (calibrationTargetRole === 'default') {
            res = await fetch('/api/positions');
        } else {
            res = await fetch('/api/clone/positions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: calibrationTargetRole, port: calibrationTargetPort })
            });
        }
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

function startManualPositionsUpdates() {
    if (manualPositionsInterval) return;
    manualPositionsInterval = setInterval(updateManualPositions, 500);
}

function stopManualPositionsUpdates() {
    if (manualPositionsInterval) {
        clearInterval(manualPositionsInterval);
        manualPositionsInterval = null;
    }
}

async function recordManualPosition(motorName, positionType) {
    try {
        let res;
        if (calibrationTargetRole === 'default') {
            res = await fetch('/api/calibration/manual', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ motor: motorName, type: positionType })
            });
        } else {
            res = await fetch('/api/clone/calibration/manual', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: calibrationTargetRole, port: calibrationTargetPort, motor: motorName, type: positionType })
            });
        }
        
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
                let calibRes;
                if (calibrationTargetRole === 'default') {
                    calibRes = await fetch('/api/calibration/info');
                } else {
                    calibRes = await fetch('/api/clone/calibration/info', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ role: calibrationTargetRole, port: calibrationTargetPort })
                    });
                }
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
    if (calibrationTargetRole === 'default') {
        await releaseMotors();
        return;
    }
    try {
        const res = await fetch('/api/clone/motors/release', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: calibrationTargetRole, port: calibrationTargetPort })
        });
        const data = await res.json();
        if (!data.success) {
            alert('Erreur relâchement: ' + (data.error || 'Erreur inconnue'));
        }
    } catch (err) {
        alert('Erreur relâchement: ' + err.message);
    }
}

async function lockAllMotors() {
    if (calibrationTargetRole === 'default') {
        await lockMotors();
        return;
    }
    try {
        const res = await fetch('/api/clone/motors/lock', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: calibrationTargetRole, port: calibrationTargetPort })
        });
        const data = await res.json();
        if (!data.success) {
            alert('Erreur verrouillage: ' + (data.error || 'Erreur inconnue'));
        }
    } catch (err) {
        alert('Erreur verrouillage: ' + err.message);
    }
}

async function findPort() {
    const btn = document.getElementById('find-port-btn');
    const originalText = btn.textContent;
    
    // Désactiver le bouton et afficher un indicateur de chargement
    btn.disabled = true;
    btn.textContent = '🔍 Recherche...';
    
    try {
        const res = await fetch('/api/find-port');
        const data = await res.json();
        
        if (data.success && data.ports.length > 0) {
            // Créer un message avec la liste des ports
            let message = `🔍 Ports série trouvés (${data.ports.length}):\n\n`;
            data.ports.forEach((port, index) => {
                message += `${index + 1}. ${port.device}`;
                if (port.description) {
                    message += ` - ${port.description}`;
                }
                if (port.manufacturer) {
                    message += ` (${port.manufacturer})`;
                }
                message += '\n';
            });
            message += '\nCliquez sur un port pour le sélectionner.';
            
            // Créer une modal pour afficher les ports et permettre la sélection
            showPortSelectionModal(data.ports);
        } else {
            alert('Aucun port série trouvé.\n\n' + (data.error || 'Vérifiez que votre périphérique est connecté.'));
        }
    } catch (err) {
        alert('Erreur lors de la recherche des ports: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

function showPortSelectionModal(ports) {
    // Créer la modal si elle n'existe pas
    let modal = document.getElementById('port-selection-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'port-selection-modal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 600px;">
                <span class="close-port-modal">&times;</span>
                <h2>🔍 Ports Série Disponibles</h2>
                <div id="port-list" style="margin: 20px 0;"></div>
            </div>
        `;
        document.body.appendChild(modal);
        
        // Gérer la fermeture
        modal.querySelector('.close-port-modal').addEventListener('click', () => {
            modal.style.display = 'none';
        });
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    }
    
    // Remplir la liste des ports
    const portList = document.getElementById('port-list');
    portList.innerHTML = '';
    
    if (ports.length === 0) {
        portList.innerHTML = '<p>Aucun port trouvé.</p>';
    } else {
        ports.forEach(port => {
            const portItem = document.createElement('div');
            portItem.className = 'port-item';
            
            let portInfo = `<strong>${port.device}</strong>`;
            if (port.description) {
                portInfo += `<span>${port.description}</span>`;
            }
            if (port.manufacturer) {
                portInfo += `<span style="font-size: 0.9em;">${port.manufacturer}</span>`;
            }
            
            portItem.innerHTML = portInfo;
            
            // Sélectionner le port au clic
            portItem.addEventListener('click', () => {
                document.getElementById('port-input').value = port.device;
                modal.style.display = 'none';
                showNotification(`Port sélectionné: ${port.device}`, 'success');
            });
            
            portList.appendChild(portItem);
        });
    }
    
    // Afficher la modal
    modal.style.display = 'block';
}

// Mise à jour périodique du statut
let appState = { is_connected: false, port: 'COM3' };

function updatePollingState() {
    if (appState.is_connected) {
        startStatusUpdates();
        startLogUpdates();
    } else {
        stopStatusUpdates();
        if (!logUpdatesForced) {
            stopLogUpdates();
        } else {
            startLogUpdates();
        }
        stopManualPositionsUpdates();
    }

    if (calibrationModalOpen && activeCalibrationTab === 'manual') {
        if (appState.is_connected || calibrationTargetRole !== 'default') {
            startManualPositionsUpdates();
        } else {
            stopManualPositionsUpdates();
        }
    } else {
        stopManualPositionsUpdates();
    }
}

function setLogUpdatesForced(enabled) {
    logUpdatesForced = enabled;
    updatePollingState();
}

function startStatusUpdates() {
    if (updateInterval) return;
    updateInterval = setInterval(async () => {
        if (!appState.is_connected) {
            return;
        }
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            
            if (data.success) {
                const wasConnected = appState.is_connected;
                appState.is_connected = data.connected;
                appState.port = data.port;
                updateConnectionStatus(data.connected);
                if (wasConnected !== appState.is_connected) {
                    updatePollingState();
                }
                
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
        if (appState.is_connected && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) {
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

function stopStatusUpdates() {
    if (updateInterval) {
        clearInterval(updateInterval);
        updateInterval = null;
    }
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
    if (logUpdateInterval) return;
    logUpdateInterval = setInterval(async () => {
        if (!appState.is_connected && !logUpdatesForced) {
            return;
        }
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

function stopLogUpdates() {
    if (logUpdateInterval) {
        clearInterval(logUpdateInterval);
        logUpdateInterval = null;
    }
}

