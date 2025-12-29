"""
Point d'entrée principal pour l'application de contrôle du bras robotique SO-ARM101
"""

import tkinter as tk
from robot_gui import LeRobotGUI


def main():
    """Lance l'interface graphique du contrôleur robotique"""
    root = tk.Tk()
    app = LeRobotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

