"""
Fonctions de normalisation avec gestion du wrap-around pour encodeurs rotatifs
Inspiré de la logique LeRobot pour les encodeurs rotatifs
"""

from config import MAX_POS


def get_path_info(pos_left, pos_right, pos_center):
    """
    Détermine le chemin de left vers right en passant par center.
    Retourne: (total_range, direction, wraps)
    """
    # 1. Vérifier si le chemin direct (sans wrap) contient le centre
    if pos_left <= pos_right:
        direct_contains_center = (pos_left <= pos_center <= pos_right)
    else:
        direct_contains_center = (pos_left >= pos_center >= pos_right)
        
    if direct_contains_center:
        # Chemin direct (pas de passage par 0)
        if pos_left <= pos_right:
            return (pos_right - pos_left, 1, False)  # Croissant
        else:
            return (pos_left - pos_right, -1, False) # Décroissant
    
    # 2. Si le centre n'est pas sur le chemin direct, c'est un wrap-around
    # Le chemin passe par 0 (4095 <-> 0)
    
    # Cas A: Left < Right, mais on passe par l'extérieur (ex: L=100, R=4000, C=50)
    if pos_left <= pos_right:
        # On va de 100 -> 0 -> 4000 (décroissant)
        total_range = pos_left + (MAX_POS - pos_right)
        return (total_range, -1, True)
        
    # Cas B: Left > Right, mais on passe par l'extérieur (ex: L=4000, R=100, C=4050)
    else:
        # On va de 4000 -> 4095 -> 0 -> 100 (croissant)
        total_range = (MAX_POS - pos_left) + pos_right
        return (total_range, 1, True)


def detect_wrap_around(pos_left, pos_right, pos_center):
    """Détermine si le range passe par 0 (wrap-around)."""
    _, _, wraps = get_path_info(pos_left, pos_right, pos_center)
    return wraps


def normalize_position(raw_pos, pos_left, pos_right, pos_center):
    """
    Normalise une position brute (0-4095) en valeur 0.0 (gauche) à 1.0 (droite).
    """
    total_range, direction, wraps = get_path_info(pos_left, pos_right, pos_center)
    
    if total_range == 0:
        return 0.5
    
    # Calculer la distance de left à raw_pos dans la bonne direction
    distance = 0
    
    if not wraps:
        # Cas simple : pas de wrap
        if direction == 1: # Croissant (Left < Right)
            distance = raw_pos - pos_left
        else: # Décroissant (Left > Right)
            distance = pos_left - raw_pos
    else:
        # Cas complexe : wrap around 0
        if direction == 1: # Croissant (Left > Right via 0)
            # Left -> 4095 -> 0 -> Right
            if raw_pos >= pos_left:
                distance = raw_pos - pos_left
            else: # raw_pos a passé 0
                distance = (MAX_POS - pos_left) + raw_pos
        else: # Décroissant (Left < Right via 0)
            # Left -> 0 -> 4095 -> Right
            if raw_pos <= pos_left:
                distance = pos_left - raw_pos
            else: # raw_pos a passé 0 (donc est grand, vers 4095)
                distance = pos_left + (MAX_POS - raw_pos)
    
    normalized = distance / total_range
    return max(0.0, min(1.0, normalized))


def denormalize_position(normalized, pos_left, pos_right, pos_center):
    """
    Convertit une valeur normalisée (0.0-1.0) en position brute (0-4095).
    """
    normalized = max(0.0, min(1.0, normalized))
    
    total_range, direction, wraps = get_path_info(pos_left, pos_right, pos_center)
    
    if total_range == 0:
        return pos_left
    
    distance = int(normalized * total_range)
    
    if not wraps:
        # Pas de wrap
        if direction == 1: # Croissant
            raw = pos_left + distance
        else: # Décroissant
            raw = pos_left - distance
    else:
        # Wrap around
        if direction == 1: # Croissant (Left > Right via 0)
            raw = pos_left + distance
            if raw >= MAX_POS:
                raw -= MAX_POS
        else: # Décroissant (Left < Right via 0)
            raw = pos_left - distance
            if raw < 0:
                raw += MAX_POS
    
    final = int(raw) % MAX_POS
    return final

