"""
Script de démarrage pour l'interface web
"""

import sys
import os

# Vérifier que nous sommes dans le bon environnement
try:
    from lerobot.motors.feetech import FeetechMotorsBus
except ImportError:
    print("⚠️ LeRobot non trouvé!")
    print("\nVérifiez que vous êtes dans l'environnement conda:")
    print("  conda activate lerobot")
    print("  pip install lerobot[feetech]")
    print("  python start_web.py")
    sys.exit(1)

# Lancer l'application web
if __name__ == '__main__':
    from web_app import app
    print("\n" + "="*50)
    print("🤖 SO-ARM101 Controller Web")
    print("="*50)
    print("\nInterface accessible à: http://localhost:5000")
    print("\n🔄 Mode rechargement automatique activé:")
    print("   - Modifiez les fichiers Python (.py)")
    print("   - Actualisez la page web (F5)")
    print("   - Les changements seront appliqués automatiquement")
    print("   - Le serveur ne redémarre pas, la connexion reste active")
    print("\nAppuyez sur Ctrl+C pour arrêter\n")
    app.run(
        debug=True,
        host='0.0.0.0',
        port=5000,
        use_reloader=False,  # Désactivé pour permettre le rechargement à chaud manuel
        use_debugger=True
    )

