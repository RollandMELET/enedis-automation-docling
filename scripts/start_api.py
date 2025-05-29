# start_api.py
#
# Version: 1.5.0
# Date: 2025-05-30
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

# Helper to convert string to float using defined decimal and thousands separators
def parse_numeric_value(value_str, decimal_sep=',', thousands_sep=' '):
    if value_str is None:
        return None
    # Normalize decimal separator to '.' for float conversion
    cleaned_value = value_str.replace(thousands_sep, '').replace(decimal_sep, '.') 
    try:
        return float(cleaned_value)
    except ValueError:
        return None

def process_general_fields(full_text, rules):
    """Extrait les champs généraux du texte en utilisant les règles."""
    extracted_data = {}
    for rule in rules.get("general_fields", []):
        field_name = rule["field_name"]
        patterns = rule["patterns"]
        value = None
        for pattern_str in patterns:
            match = re.search(pattern_str, full_text, re.IGNORECASE | re.DOTALL)
            if match:
                value = match.group(1).strip()
                if rule["type"] == "float":
                    value = value.replace(' ', '').replace('.', '').replace(',', '.') 
                    try:
                        value = float(value)
                    except ValueError:
                        value = None 
                break 
        extracted_data[field_name] = value
    return extracted_data

def process_table_fields(full_text, rules):
    """
    Extrait les champs de tableau du texte en utilisant une approche par blocs d'articles.
    Recherche le début de chaque article par son numéro de position et son codet,
    puis extrait les informations à l'intérieur de ce bloc.
    """
    print("INFO: Tentative d'extraction de tableau par blocs d'articles (Version 1.5.0).")
    
    table_data = []
    
    table_rules = rules.get("table_fields", {})
    columns_info = table_rules.get("columns", [])

    # Trouver la section du tableau après l'en-tête
    table_start_marker_regex = r"(D\u00e9signation|Désignation|Quantit\u00e9|Quantité|P\.U\.\s*HT|Montant\s*HT).*?\n"
    match_table_start = re.search(table_start_marker_regex, full_text, re.IGNORECASE | re.DOTALL)

    table_content = ""
    if match_table_start:
        table_content = full_text[match_table_start.end():].strip()
        print(f"Texte pour l'analyse de tableau (après en-tête détectée):\n{table_content[:700]}...")
    else:
        print("ATTENTION: Marqueur de début de tableau (en-tête de colonne) non trouvé. Analyse sur le texte brut complet.")
        table_content = full_text

    # Regex pour trouver tous les blocs d'articles
    # Capture le numéro de position (grp 1), le codet (grp 2), et tout le texte du bloc de l'article (grp 3)
    item_block_regex = re.compile(
        r"^\s*(\d{5})\s*" # Group 1: CMDCodetPosition (5 digits)
        r"(\d{7,8})\s*" # Group 2: CMDCodet (7 or 8 digits)
        r"(.+?)" # Group 3: Entire item block content
        r"(?=\n\s*\d{5}\s*\d{7,8}|$|\s*Total\s*HT\s*de\s*la\s*commande|Interlocuteur|Consignes d'expédition)"
        , re.IGNORECASE | re.DOTALL | re.MULTILINE # MULTILINE for ^ and $ to match start/end of lines
    )
    
    # Itérer sur chaque bloc d'article trouvé
    for item_block_match in item_block_regex.finditer(table_content):
        row_data = {}
        try:
            position = item_block_match.group(1).strip()
            codet = item_block_match.group(2).strip()
            item_raw_content = item_block_match.group(3).strip() # Le contenu du bloc de l'article

            row_data["CMDCodetPosition"] = position
            row_data["CMDCodet"] = codet

            print(f"\n--- Bloc d'article trouvé pour Pos {position}, Codet {codet} ---")
            # print(f"Contenu brut du bloc:\n{item_raw_content[:500]}...") # Pour un débogage intense

            # Regex pour Quantité, P.U. HT, Montant HT à l'intérieur du bloc
            # Ces valeurs sont souvent en fin de bloc, après beaucoup d'espaces ou de sauts de ligne.
            # Elles sont souvent précédées par "Prix brut" ou "Prix brut" sur sa propre ligne.
            
            # Cette regex cherche spécifiquement la séquence (nombre) (unit) (nombre) EUR (nombre) EUR
            # en se concentrant sur les dernières apparitions dans le bloc.
            price_regex = re.compile(
                r"(\d+(?:[.,]\d+)?)\s*(?:PC|U|EUR|T|Kg|l|UNITE|UNITES)?\s*\n?" # Possible quantity and unit (Group 1)
                r"(\d+(?:[.,]\d+)?)\s*EUR\s*\n?" # Unit Price (Group 2)
                r"(\d+(?:[.,]\d+)?)\s*EUR$" # Total Line Price (Group 3)
                , re.IGNORECASE | re.DOTALL
            )

            # Find the last match in the item_raw_content for price and quantity
            price_match = None
            for m in price_regex.finditer(item_raw_content):
                price_match = m # Keep the last match (assumes last occurrence is the correct one)

            if price_match:
                qty_rule = next((col for col in columns_info if col['field_name'] == 'CMDCodetQuantity'), {})
                unit_price_rule = next((col for col in columns_info if col['field_name'] == 'CMDCodetUnitPrice'), {})
                total_line_price_rule = next((col for col in columns_info if col['field_name'] == 'CMDCodetTotlaLinePrice'), {})
                
                row_data["CMDCodetQuantity"] = parse_numeric_value(price_match.group(1).strip(), qty_rule.get('decimal_separator', ','), qty_rule.get('thousands_separator', ' '))
                row_data["CMDCodetUnitPrice"] = parse_numeric_value(price_match.group(2).strip(), unit_price_rule.get('decimal_separator', ','), unit_price_rule.get('thousands_separator', ' '))
                row_data["CMDCodetTotlaLinePrice"] = parse_numeric_value(price_match.group(3).strip(), total_line_price_rule.get('decimal_separator', ','), total_line_price_rule.get('thousands_separator', ' '))

                # Extract description: It's everything in item_raw_content *before* the price_match
                # This needs to be robust, perhaps using position, or just by removing known parts.
                description_raw = item_raw_content[:price_match.start()].strip()
                
                # Clean up the description
                description_raw = re.sub(r"Prix\s*brut", "", description_raw, flags=re.IGNORECASE | re.DOTALL)
                description_raw = re.sub(r"Appel\s*sur\s*contrat\s*CC\d+", "", description_raw, flags=re.IGNORECASE | re.DOTALL)
                description_raw = re.sub(r"________________.*", "", description_raw, flags=re.DOTALL) # Remove lines with underscores
                description_raw = re.sub(r"\n\s*\n", "\n", description_raw) # Remove multiple empty lines
                description_raw = description_raw.strip() # Remove leading/trailing whitespace
                description_raw = description_raw.replace('\n', ' ') # Replace newlines in description with space for single-line output
                row_data["CMDCodetNom"] = description_raw
                
                table_data.append(row_data)
                print(f"Ligne extraite: {row_data}")

            else:
                print(f"ATTENTION: Prix ou quantité non trouvés dans le bloc d'article pour position {position}, codet {codet}. Bloc analysé: \n{item_raw_content[:200]}...")
                # Fallback: Si les prix ne sont pas trouvés, ajouter juste position, codet, et la description brute.
                row_data["CMDCodetNom"] = item_raw_content.replace('\n', ' ')
                row_data["CMDCodetQuantity"] = None
                row_data["CMDCodetUnitPrice"] = None
                row_data["CMDCodetTotlaLinePrice"] = None
                table_data.append(row_data) # Ajouter même les éléments incomplets pour inspection


        except Exception as e:
            print(f"Erreur lors du traitement d'un bloc d'article: {e}. Bloc: \n{item_block_match.group(0)[:200]}...")
            # pass # Ignorer les blocs qui causent des erreurs (décommenter si tu veux que le script continue même en cas d'erreur grave sur une ligne)

    return table_data


# --- Routes de l'API ---

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de vérification de santé (FR-5.2)."""
    return jsonify({"status": "healthy", "service": "Docling API", "version": "1.5.0", "rules_loaded": bool(extraction_rules)}), 200

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
            full_text = extract_text_from_pdf(file_stream)
            print(f"Texte extrait directement (longueur: {len(full_text)}).")
            print("--- DÉBUT DU TEXTE BRUT DU PDF (pour débogage) ---")
            print(full_text)
            print("--- FIN DU TEXTE BRUT DU PDF ---")

            if not full_text.strip():
                print("Texte PDF vide, une logique d'OCR serait appliquée ici pour les PDF scannés.")

        except Exception as e:
            print(f"Erreur lors de la lecture du PDF avec pdfminer.six: {e}. Le document est peut-être scanné ou corrompu.")
            full_text = ""
        
        general_data = process_general_fields(full_text, extraction_rules)
        line_items_data = process_table_fields(full_text, extraction_rules) 

        extracted_output = {
            "CMDRefEnedis": general_data.get("CMDRefEnedis"),
            "CMDDateCommande": general_data.get("CMDDateCommande"),
            "TotalHT": general_data.get("TotalHT"),
            "line_items": line_items_data,
            "confidence_score": 0.85, 
            "extracted_from": file.filename,
            "extraction_method": "Textual PDF processing (with item block parsing)" if full_text.strip() else "Failed Text Extraction/OCR needed"
        }
        
        return jsonify(extracted_output), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)