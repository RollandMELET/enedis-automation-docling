# start_api.py
#
# Version: 1.9.0
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
    pdf_stream.seek(0)
    for page_layout in extract_pages(pdf_stream):
        for element in page_layout:
            if isinstance(element, LTTextContainer):
                text_content += element.get_text() + "\n"
    pdf_stream.seek(0)
    return text_content

def extract_text_with_ocr(image):
    """Applique l'OCR sur une image."""
    return pytesseract.image_to_string(image, lang='fra')

# Helper to convert string to float using defined decimal and thousands separators
def parse_numeric_value(value_str, decimal_sep=',', thousands_sep=' '):
    if value_str is None:
        return None
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
    print("INFO: Tentative d'extraction de tableau par blocs d'articles (Version 1.9.0).") # Updated version
    
    table_data = []
    
    table_rules = rules.get("table_fields", {})
    columns_info = table_rules.get("columns", [])

    # Trouver la section du tableau après l'en-tête
    table_start_marker_regex = r"(D\u00e9signation|Désignation|Quantit\u00e9|Quantité|P\.U\.\s*HT|Montant\s*HT).*?\n"
    match_table_start = re.search(table_start_marker_regex, full_text, re.IGNORECASE | re.DOTALL)

    table_content = ""
    if match_table_start:
        # Inclure la ligne d'en-tête et les lignes de séparateurs pour assurer la continuité contextuelle
        # On peut affiner cela plus tard pour exclure strictement l'en-tête si nécessaire.
        # Pour l'instant, on prend tout ce qui suit l'en-tête détectée.
        table_content = full_text[match_table_start.start():].strip() # Prendre un peu avant l'en-tête réelle pour plus de contexte si besoin
        print(f"Texte pour l'analyse de tableau (après en-tête détectée):\n{table_content[:700]}...")
    else:
        print("ATTENTION: Marqueur de début de tableau (en-tête de colonne) non trouvé. Analyse sur le texte brut complet.")
        table_content = full_text

    # Regex pour trouver tous les blocs d'articles
    # Capture le numéro de position (grp 1), le codet (grp 2), et tout le texte du bloc de l'article (grp 3)
    # MODIFICATION CLÉ: La lookahead de fin de bloc est simplifiée pour ne s'arrêter qu'au prochain article ou fin de string.
    item_block_regex = re.compile(
        r"^\s*(\d{5})\s*" # Group 1: CMDCodetPosition (5 digits)
        r"(\d{7,8})\s*" # Group 2: CMDCodet (7 or 8 digits)
        r"(.+?)" # Group 3: Entire item block content (non-greedy)
        # S'arrête au début du prochain article ou à la fin de la chaîne
        r"(?=\n\s*\d{5}\s*\d{7,8}|$)" 
        , re.IGNORECASE | re.DOTALL | re.MULTILINE # MULTILINE for ^ and $ to match start/end of lines
    )
    
    # Itérer sur chaque bloc d'article trouvé
    for item_block_match in item_block_regex.finditer(table_content):
        row_data = {}
        # Initialize match objects to None to avoid NameError if no match is found
        total_price_match = None
        unit_price_match = None 
        quantity_match = None

        try:
            position = item_block_match.group(1).strip()
            codet = item_block_match.group(2).strip()
            item_raw_content = item_block_match.group(3).strip() # Le contenu du bloc de l'article

            row_data["CMDCodetPosition"] = position
            row_data["CMDCodet"] = codet

            print(f"\n--- Bloc d'article trouvé pour Pos {position}, Codet {codet} ---")
            print(f"Contenu brut du bloc de l'article:\n{item_raw_content[:500]}...") # For detailed debugging

            # --- Extract Quantité, Prix Unitaire, Prix Total using separate regexes ---
            
            # 1. Extract Total Line Price (last numeric value on its line, potentially without EUR suffix)
            # Find all numbers that look like prices at the end of lines
            all_price_candidates_in_block = re.findall(r"(\d+(?:[.,]\d+)?)\s*$", item_raw_content, re.MULTILINE)
            
            # Assuming the last two unique values are Total Price and Unit Price
            # This order is based on observation from the PDF: P.U. HT, then Montant HT.
            # So, in reversed list order: Total Price, then Unit Price.
            
            # Filter unique values and reverse to get highest to lowest (or as they appear last)
            unique_price_candidates = list(dict.fromkeys(all_price_candidates_in_block)) # Remove duplicates while preserving order
            
            if len(unique_price_candidates) >= 2:
                total_line_price_str = unique_price_candidates[-1] # Last unique numeric value
                unit_price_str = unique_price_candidates[-2] # Second to last unique numeric value
            elif len(unique_price_candidates) == 1:
                total_line_price_str = unique_price_candidates[-1]
                unit_price_str = None # No distinct unit price found
            else:
                total_line_price_str = None
                unit_price_str = None

            # 2. Extract Quantity (number followed by PC, U, UNITE, etc.)
            quantity_str = None
            quantity_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:PC|U|UNITE|UNITES)\b", item_raw_content, re.IGNORECASE | re.DOTALL) # \b for word boundary
            if quantity_match:
                quantity_str = quantity_match.group(1).strip()
            
            # Apply parsing rules
            qty_rule = next((col for col in columns_info if col['field_name'] == 'CMDCodetQuantity'), {})
            unit_price_rule = next((col for col in columns_info if col['field_name'] == 'CMDCodetUnitPrice'), {})
            total_line_price_rule = next((col for col in columns_info if col['field_name'] == 'CMDCodetTotlaLinePrice'), {})
            
            row_data["CMDCodetQuantity"] = parse_numeric_value(quantity_str, qty_rule.get('decimal_separator', ','), qty_rule.get('thousands_separator', ' '))
            row_data["CMDCodetUnitPrice"] = parse_numeric_value(unit_price_str, unit_price_rule.get('decimal_separator', ','), unit_price_rule.get('thousands_separator', ' '))
            row_data["CMDCodetTotlaLinePrice"] = parse_numeric_value(total_line_price_str, total_line_price_rule.get('decimal_separator', ','), total_line_price_rule.get('thousands_separator', ' '))

            # --- Extract and clean Description (CMDCodetNom) ---
            description_raw = item_raw_content
            
            # Remove numerical values and associated units/currencies from description_raw for cleaner output
            # Replace the *matched string parts* if they were found, from the description.
            # This is done by iterating on the parts to remove.
            
            elements_to_remove = []
            if quantity_match: elements_to_remove.append(quantity_match.group(0))
            if unit_price_str: # Must reconstruct the string from the numeric value and EUR for replacement
                # This is heuristic, better to remove the exact matched span if possible
                # For this simple case, try to match the number + EUR if it exists in raw content
                price_match_candidate = re.search(re.escape(unit_price_str) + r'\s*EUR', item_raw_content, re.IGNORECASE)
                if price_match_candidate: elements_to_remove.append(price_match_candidate.group(0))
                else: elements_to_remove.append(unit_price_str) # Fallback to just the number
            if total_line_price_str: # Same logic for total price
                price_match_candidate = re.search(re.escape(total_line_price_str) + r'\s*EUR', item_raw_content, re.IGNORECASE)
                if price_match_candidate: elements_to_remove.append(price_match_candidate.group(0))
                else: elements_to_remove.append(total_line_price_str) # Fallback to just the number
            
            for elem in elements_to_remove:
                description_raw = description_raw.replace(elem, '', 1) # Replace only the first occurrence
            
            # Clean up common patterns like "Prix brut", "Appel sur contrat", and separators
            description_raw = re.sub(r"Prix\s*brut", "", description_raw, flags=re.IGNORECASE | re.DOTALL)
            description_raw = re.sub(r"Appel\s*sur\s*contrat\s*CC\d+", "", description_raw, flags=re.IGNORECASE | re.DOTALL)
            description_raw = re.sub(r"________________.*", "", description_raw, flags=re.DOTALL) # Remove lines with underscores
            description_raw = re.sub(r"\n\s*\n", "\n", description_raw) # Remove multiple empty lines
            
            description_raw = description_raw.strip()
            description_raw = description_raw.replace('\n', ' ') # Ensure single-line output
            row_data["CMDCodetNom"] = description_raw
            
            table_data.append(row_data)
            print(f"Ligne extraite: {row_data}")

        except Exception as e:
            print(f"Erreur lors du traitement d'un bloc d'article: {e}. Bloc: \n{item_block_match.group(0)[:200]}...")
            # Fallback: Add article with partial data for debugging if an error occurs
            row_data["CMDCodetNom"] = item_raw_content.replace('\n', ' ')
            row_data["CMDCodetQuantity"] = None
            row_data["CMDCodetUnitPrice"] = None
            row_data["CMDCodetTotlaLinePrice"] = None
            table_data.append(row_data)

    return table_data


# --- Routes de l'API ---

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de vérification de santé (FR-5.2)."""
    return jsonify({"status": "healthy", "service": "Docling API", "version": "1.9.0", "rules_loaded": bool(extraction_rules)}), 200 # Updated version

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