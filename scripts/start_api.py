# start_api.py
#
# Version: 1.2.0
# Date: 2025-05-29
# Author: Rolland MELET & AI Senior Coder
# Description: API Flask pour le moteur d'extraction de commandes ENEDIS.
#              Initialise les règles d'extraction, gère la lecture des PDF et l'application des règles.
#              Expose un endpoint /health et un endpoint /extract pour le traitement des documents.

from flask import Flask, request, jsonify
import os
import json
import io
import re
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTChar, LTFigure
from PIL import Image
import pytesseract

app = Flask(__name__)

# Chemin vers le fichier de règles d'extraction
RULES_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'extraction-rules.json')

# Chargement des règles d'extraction au démarrage de l'application
extraction_rules = {}
if os.path.exists(RULES_FILE_PATH):
    try:
        with open(RULES_FILE_PATH, 'r', encoding='utf-8') as f:
            extraction_rules = json.load(f)
        print(f"Règles d'extraction chargées depuis: {RULES_FILE_PATH}")
    except json.JSONDecodeError as e:
        print(f"ERREUR: Erreur de format JSON dans '{RULES_FILE_PATH}': {e}. L'extraction sera vide.")
    except Exception as e:
        print(f"ERREUR: Impossible de charger les règles '{RULES_FILE_PATH}': {e}. L'extraction sera vide.")
else:
    print(f"ATTENTION: Fichier de règles '{RULES_FILE_PATH}' introuvable. L'extraction sera vide.")

# --- Fonctions d'extraction ---

def extract_text_from_pdf(pdf_stream):
    """Extrait tout le texte d'un PDF en utilisant pdfminer.six."""
    text_content = ""
    # Réinitialise le stream au début pour la lecture par pdfminer.six
    pdf_stream.seek(0)
    for page_layout in extract_pages(pdf_stream):
        for element in page_layout:
            if isinstance(element, LTTextContainer):
                text_content += element.get_text() + "\n"
    pdf_stream.seek(0) # Réinitialise le stream à nouveau si d'autres lectures sont prévues
    return text_content

def extract_text_with_ocr(image):
    """Applique l'OCR sur une image."""
    # Pour une meilleure précision, on peut pré-traiter l'image (resize, binarisation)
    # Mais pour commencer, on utilise Tesseract directement
    return pytesseract.image_to_string(image, lang='fra')

def process_general_fields(full_text, rules):
    """Extrait les champs généraux du texte en utilisant les règles."""
    extracted_data = {}
    for rule in rules.get("general_fields", []):
        field_name = rule["field_name"]
        patterns = rule["patterns"]
        value = None
        for pattern_str in patterns:
            # Utilise re.IGNORECASE pour une recherche insensible à la casse
            # re.DOTALL permet à . de correspondre à tout caractère, y compris le retour à la ligne
            match = re.search(pattern_str, full_text, re.IGNORECASE | re.DOTALL)
            if match:
                value = match.group(1).strip()
                if rule["type"] == "float":
                    # Supprime tous les espaces (milliers) et remplace la virgule par un point (décimal)
                    value = value.replace(' ', '').replace('.', '').replace(',', '.') 
                    try:
                        value = float(value)
                    except ValueError:
                        value = None # Garde la valeur None si la conversion échoue
                # Ajout de la gestion du format de date (ici on garde la string, la conversion peut être faite dans n8n)
                break # Une fois un match trouvé, on passe à la règle suivante (pour ce champ)
        extracted_data[field_name] = value
    return extracted_data

def process_table_fields(full_text, rules):
    """Extrait les champs de tableau du texte."""
    # Cette fonction est une simplification pour le début.
    # L'extraction de tableaux est complexe et nécessiterait une logique plus robuste,
    # potentiellement basée sur des positions (bounding boxes) plutôt que juste du texte brut.
    # Pour une véritable implémentation de Docling, cela impliquerait:
    # - Détection des régions de tableau dans le PDF (bounding boxes).
    # - Extraction du texte et de la position des caractères.
    # - Reconstitution des lignes et colonnes du tableau.
    # - Adaptation à différentes structures de tableaux.

    print("INFO: L'extraction de tableau est actuellement simulée. La logique Docling réelle sera implémentée ici.")
    
    # Retourne les données simulées comme avant pour garder le contrat de l'API.
    return [
        {
            "CMDCodetPosition": "1",
            "CMDCodet": "7395078",
            "CMDCodetNom": "Tableau monobloc extensible",
            "CMDCodetQuantity": 1,
            "CMDCodetUnitPrice": 10000.00,
            "CMDCodetTotlaLinePrice": 10000.00
        },
        {
            "CMDCodet": "6424704",
            "CMDCodetNom": "TR 400 C 20 KV PR S27",
            "CMDCodetPosition": "2",
            "CMDCodetQuantity": 1,
            "CMDCodetUnitPrice": 5000.00,
            "CMDCodetTotlaLinePrice": 5000.00
        }
    ]

# --- Routes de l'API ---

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de vérification de santé (FR-5.2)."""
    return jsonify({"status": "healthy", "service": "Docling API", "version": "0.1.1", "rules_loaded": bool(extraction_rules)}), 200

@app.route('/extract', methods=['POST'])
def extract_document():
    """Endpoint pour l'extraction de documents."""
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file:
        file_stream = io.BytesIO(file.read())
        
        full_text = ""
        try:
            # Tenter d'extraire le texte directement (si PDF textuel)
            full_text = extract_text_from_pdf(file_stream)
            print(f"Texte extrait directement (longueur: {len(full_text)}).")
            # --- DÉBUT DU TEXTE BRUT DU PDF (pour débogage) ---
            print("--- DÉBUT DU TEXTE BRUT DU PDF (pour débogage) ---")
            print(full_text) # Cette ligne affiche le texte brut dans les logs Coolify
            print("--- FIN DU TEXTE BRUT DU PDF ---")
            # --- FIN DU TEXTE BRUT DU PDF ---

            # Optionnel: Si le texte est très court ou vide, tenter l'OCR
            # Pour l'instant, on assume que si le texte est là, on l'utilise.
            # L'implémentation de l'OCR pour les PDF scannés est plus complexe
            # (nécessite la conversion page par page en image, puis OCR).
            # Cette logique est pour l'implémentation réelle de Docling.
            if not full_text.strip():
                print("Texte PDF vide, une logique d'OCR serait appliquée ici pour les PDF scannés.")
                # Si le document était une image directement, on pourrait faire:
                # image = Image.open(file_stream)
                # full_text = extract_text_with_ocr(image)

        except Exception as e:
            print(f"Erreur lors de la lecture du PDF avec pdfminer.six: {e}. Le document est peut-être scanné ou corrompu.")
            full_text = "" # Réinitialise le texte en cas d'erreur pour que les règles ne trouvent rien
        
        # Application des règles d'extraction
        general_data = process_general_fields(full_text, extraction_rules)
        # La ligne d'articles est TOUJOURS simulée pour le moment, quelle que soit l'extraction de texte.
        line_items_data = process_table_fields(full_text, extraction_rules) 

        # Construction de la réponse finale
        extracted_output = {
            "CMDRefEnedis": general_data.get("CMDRefEnedis"),
            "CMDDateCommande": general_data.get("CMDDateCommande"),
            "TotalHT": general_data.get("TotalHT"), # Utilise le nom de champ correct pour la réponse
            "line_items": line_items_data,
            "confidence_score": 0.85, # Score de confiance simulé
            "extracted_from": file.filename,
            "extraction_method": "Textual PDF processing" if full_text.strip() else "Simulated/Placeholder (Text extraction failed or empty)"
        }
        
        return jsonify(extracted_output), 200

# Le point d'entrée de l'application Flask
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)