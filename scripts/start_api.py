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
    with open(RULES_FILE_PATH, 'r', encoding='utf-8') as f:
        extraction_rules = json.load(f)
    print(f"Règles d'extraction chargées depuis: {RULES_FILE_PATH}")
else:
    print(f"ATTENTION: Fichier de règles '{RULES_FILE_PATH}' introuvable. L'extraction sera vide.")

# --- Fonctions d'extraction ---

def extract_text_from_pdf(pdf_path):
    """Extrait tout le texte d'un PDF en utilisant pdfminer.six."""
    text_content = ""
    for page_layout in extract_pages(pdf_path):
        for element in page_layout:
            if isinstance(element, LTTextContainer):
                text_content += element.get_text() + "\n"
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
            match = re.search(pattern_str, full_text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if rule["type"] == "float":
                    value = value.replace('.', '').replace(',', '.') # Gère les séparateurs décimaux
                    value = float(value)
                # Ajout de la gestion du format de date
                if rule["type"] == "date" and "date_format" in rule:
                    try:
                        # Tente de parser et de reformater la date si nécessaire
                        # Ici, nous retournons la date telle qu'extraite pour la simplicité,
                        # la conversion de format peut être faite dans n8n si plus complexe.
                        pass # On garde la string pour l'instant
                    except ValueError:
                        pass # Laisser comme string si le format ne correspond pas
                break # Une fois un match trouvé, on passe à la règle suivante
        extracted_data[field_name] = value
    return extracted_data

def process_table_fields(full_text, rules):
    """Extrait les champs de tableau du texte."""
    # C'est une simplification pour le début.
    # L'extraction de tableaux est complexe et nécessiterait une logique plus robuste.
    # Ici, nous allons simuler en cherchant des lignes entre les mots clés de début et de fin.
    
    # Pour une véritable implémentation de Docling, cela impliquerait:
    # - Détection des régions de tableau dans le PDF (bounding boxes).
    # - Extraction du texte et de la position des caractères.
    # - Reconstitution des lignes et colonnes du tableau.
    # - Adaptation à différentes structures de tableaux.

    # Pour le MVP, on se contente de la logique de simulation existante ou d'une recherche textuelle très basique.
    # Puisque nous avons un placeholder, on retourne les données simulées.
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
            "CMDCodetPosition": "2",
            "CMDCodet": "6424704",
            "CMDCodetNom": "TR 400 C 20 KV PR S27",
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
        
        try:
            # 1. Tenter d'extraire le texte directement (si PDF textuel)
            full_text = extract_text_from_pdf(file_stream)
            print(f"Texte extrait directement (longueur: {len(full_text)}).")

            # Si l'extraction de texte est vide ou insuffisante, on pourrait envisager l'OCR.
            # Pour le test initial, on va quand même simuler la réponse même si le texte est là.
            # Une vraie logique vérifierait la pertinence du texte ou si des images sont présentes.
            if not full_text.strip(): # Si le PDF est vide ou juste des espaces, tenter l'OCR
                print("Texte PDF vide, tentative d'OCR.")
                # Revenir au début du stream pour lire comme une image si nécessaire
                file_stream.seek(0)
                # Note: L'OCR direct d'un PDF complet n'est pas simple.
                # Pour la robustesse, on convertirait chaque page en image et on ferait de l'OCR.
                # Pour ce placeholder, nous allons simplifier et toujours simuler pour l'extraction.
                # La complexité de la conversion PDF->Image->OCR pour chaque page
                # est au-delà du scope du placeholder et serait ajoutée dans l'implémentation réelle de Docling.
                # Pour l'instant, on assume que la logique de Docling gérera cela.
                
                # Placeholder pour l'OCR de l'image (non implémenté ici directement pour PDF entier)
                # Si c'était une image directement, on ferait:
                # image = Image.open(file_stream)
                # ocr_text = extract_text_with_ocr(image)
                # print(f"Texte extrait par OCR (longueur: {len(ocr_text)}).")
                # full_text = ocr_text # Utiliser le texte OCR

        except Exception as e:
            print(f"Erreur lors de la lecture du PDF avec pdfminer.six: {e}. Le document est peut-être scanné ou corrompu.")
            # Fallback potentiel: forcer l'OCR si lecture de texte échoue
            # Pour cet exemple, nous allons juste simuler.
            full_text = "" # S'assurer que full_text est vide pour le fallback simulé
        
        # Application des règles d'extraction
        general_data = process_general_fields(full_text, extraction_rules)
        line_items_data = process_table_fields(full_text, extraction_rules) # Ceci est actuellement simulé

        # Construction de la réponse finale
        extracted_output = {
            "CMDRefEnedis": general_data.get("CMDRefEnedis"),
            "CMDDateCommande": general_data.get("CMDDateCommande"),
            "TotalHT": general_data.get("CMDTotalHT"),
            "line_items": line_items_data,
            "confidence_score": 0.85, # Score de confiance simulé
            "extracted_from": file.filename,
            "extraction_method": "Simulated/Placeholder"
        }
        
        # Gérer les cas où l'extraction est vide
        if not extracted_output["CMDRefEnedis"]:
             extracted_output["extraction_method"] = "Simulated/Placeholder (Empty text extraction)"
             # Fallback logic would go here if text extraction failed and we needed to OCR
             # For now, we just return the dummy data.

        return jsonify(extracted_output), 200
    if name == 'main':
app.run(host='0.0.0.0', port=5000)