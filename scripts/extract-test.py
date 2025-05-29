# scripts/extract-test.py
#
# Version: 1.1.0
# Date: 2025-05-30
# Author: Rolland MELET & AI Senior Coder
# Description: Script pour envoyer un PDF à l'API Docling déployée et afficher la sortie JSON.
#              Accepte maintenant un nom de fichier PDF en argument.

import requests
import json
import os
import sys

# --- Configuration de l'URL de l'API Docling déployée ---
DOCLING_API_BASE_URL = "https://enedis-automation-docling.rorworld.eu" 

# --- Vérification des arguments de ligne de commande ---
if len(sys.argv) < 2:
    print("ERREUR: Veuillez spécifier le nom du fichier PDF à tester.")
    print("Exemple: python3 scripts/extract-test.py 'Commande 4801377867JPSM2025-03-19.PDF'")
    sys.exit(1) # Quitte le script si aucun argument n'est fourni

PDF_FILE_NAME = sys.argv[1] # Prend le premier argument comme nom de fichier

# Construit le chemin complet du fichier PDF à partir de l'emplacement du script
file_path_for_test = os.path.join(os.path.dirname(__file__), '..', 'tests', 'sample-pdfs', PDF_FILE_NAME)

# --- Vérification de l'existence du fichier PDF spécifié ---
if not os.path.exists(file_path_for_test):
    print(f"ERREUR: Le fichier PDF spécifié pour le test '{file_path_for_test}' n'existe pas.")
    print(f"Veuillez vérifier que le fichier '{PDF_FILE_NAME}' est bien placé dans le dossier 'enedis-automation-docling/tests/sample-pdfs/'.")
    sys.exit(1) # Quitte le script si le fichier n'est pas trouvé
else:
    print(f"Utilisation du fichier PDF ENEDIS: '{os.path.basename(file_path_for_test)}' pour le test.")

# --- Fonctions de test de l'API ---

def test_health_check():
    """Teste l'endpoint /health de l'API Docling."""
    health_url = f"{DOCLING_API_BASE_URL}/health"
    print(f"\nTentative de connexion à l'endpoint /health: {health_url}")
    try:
        response = requests.get(health_url)
        response.raise_for_status()  # Lève une exception pour les codes d'état HTTP d'erreur (4xx ou 5xx)
        print("Réponse de l'endpoint /health:")
        print(json.dumps(response.json(), indent=2))
        return True
    except requests.exceptions.RequestException as e:
        print(f"Erreur lors de la vérification de santé: {e}")
        print(f"Veuillez vérifier que l'API Docling est bien démarrée et accessible à {health_url}.")
        return False

def test_extract_api():
    """Teste l'endpoint /extract de l'API Docling en envoyant un fichier."""
    extract_url = f"{DOCLING_API_BASE_URL}/extract"
    print(f"\nTentative d'envoi du fichier à l'endpoint /extract: {extract_url}")
    
    try:
        with open(file_path_for_test, 'rb') as f:
            files = {'file': (os.path.basename(file_path_for_test), f, 'application/pdf')}
            print(f"Envoi du fichier '{os.path.basename(file_path_for_test)}'...")
            response = requests.post(extract_url, files=files, timeout=60)
            response.raise_for_status()

            print("Réponse de l'endpoint /extract:")
            print(json.dumps(response.json(), indent=2))
    except requests.exceptions.Timeout:
        print(f"Erreur: Le délai d'attente pour la requête à {extract_url} a été dépassé (60 secondes).")
        print("Le traitement du PDF pourrait être long ou l'API ne répond pas à temps.")
    except requests.exceptions.ConnectionError as e:
        print(f"Erreur de connexion à l'API: {e}.")
        print(f"Vérifiez que l'URL '{extract_url}' est correcte et que le service est en ligne.")
    except requests.exceptions.RequestException as e:
        print(f"Erreur lors de l'extraction: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print("Contenu de la réponse d'erreur (si disponible):", e.response.text)
        print(f"Veuillez vérifier que l'API Docling est bien démarrée et que l'endpoint /extract est fonctionnel à {extract_url}.")

# --- Exécution principale ---
if __name__ == "__main__":
    if test_health_check():
        test_extract_api()
    else:
        print("\nLe health check a échoué. Arrêt du test d'extraction.")