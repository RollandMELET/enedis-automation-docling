# start_api.py
#
# Version: 1.18.0
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

def extract_text_from_pdf_per_page(pdf_stream):
    """Extrait le texte d'un PDF page par page en utilisant pdfminer.six."""
    pdf_stream.seek(0)
    pages_text = []
    for page_layout in extract_pages(pdf_stream):
        page_content = ""
        for element in page_layout:
            if isinstance(element, LTTextContainer):
                page_content += element.get_text() + "\n"
        pages_text.append(page_content)
    pdf_stream.seek(0)
    return pages_text

def extract_text_with_ocr(image):
    """Applique l'OCR sur une image."""
    return pytesseract.image_to_string(image, lang='fra')

# Helper to convert string to float using defined decimal and thousands separators
# Fonction parse_numeric_value inchangée depuis 1.17.0 (car elle est robuste)
def parse_numeric_value(value_str):
    if value_str is None:
        return None
    
    # Remove all spaces and dots as thousands separators.
    # The heuristic here is that in French/European format (X.XXX,XX), dot is thousands.
    # If the format is US (X,XXX.XX), comma is thousands.
    # Given your documents use "X.XXX,XX", we remove dots for thousands.
    temp_value = value_str.replace(' ', '') # Remove spaces first
    if ',' in temp_value and '.' in temp_value:
        # If both present, assume comma is decimal (European format)
        if temp_value.rfind(',') > temp_value.rfind('.'): 
            temp_value = temp_value.replace('.', '') # Remove dots (thousands)
            cleaned_value = temp_value.replace(',', '.') # Replace comma (decimal) with dot
        else: # Dot is decimal (US format or mixed, or if it's the only separator, dot is decimal)
            temp_value = temp_value.replace(',', '') # Remove commas (thousands)
            cleaned_value = temp_value # Dot is already the decimal
    elif ',' in temp_value: # Only comma present, assume it's decimal
        cleaned_value = temp_value.replace(',', '.')
    else: # Only dot present, or no separator, assume dot is decimal or integer
        cleaned_value = temp_value 

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
                    value = parse_numeric_value(value) 
                break 
        extracted_data[field_name] = value
    return extracted_data

def process_table_fields(full_text_for_table, rules): 
    """
    Extrait les champs de tableau du texte pré-nettoyé page par page.
    """
    print("INFO: Tentative d'extraction de tableau par blocs d'articles (Version 1.18.0).") # Updated version
    
    table_data = []
    
    table_rules = rules.get("table_fields", {})
    columns_info = table_rules.get("columns", []) # CORRECTION BUG: maintenant prend depuis table_rules

    table_content = full_text_for_table 

    # Utiliser re.split pour découper le contenu en blocs d'articles fiables.
    item_start_delimiter_regex = re.compile(
        r"^\s*(\d{5})\s*(\d{7,8})\s*", # Group 1: CMDCodetPosition, Group 2: CMDCodet
        re.IGNORECASE | re.MULTILINE
    )

    split_parts = item_start_delimiter_regex.split(table_content)
    
    raw_item_blocks = []
    if split_parts and len(split_parts) > 1:
        for i in range(1, len(split_parts), 3):
            if i + 2 < len(split_parts):
                raw_item_blocks.append({
                    "position": split_parts[i],
                    "codet": split_parts[i+1],
                    "content": split_parts[i+2].strip()
                })
    
    for item_raw_data in raw_item_blocks:
        row_data = {}
        quantity_val = None
        unit_price_val = None
        total_line_price_val = None

        try:
            position = item_raw_data["position"]
            codet = item_raw_data["codet"]
            item_raw_content = item_raw_data["content"]

            row_data["CMDCodetPosition"] = position
            row_data["CMDCodet"] = codet

            print(f"\n--- Bloc d'article trouvé pour Pos {position}, Codet {codet} ---")
            print(f"Contenu brut du bloc de l'article (complet):\n{item_raw_content}")

            # --- Extraction des prix et quantité ---
            print("--- Début du débogage des prix/quantités ---") # DEBUG PRINT
            
            # 1. Extraire la Quantité (souvent un nombre suivi de PC, U, etc., n'importe où dans le bloc)
            quantity_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:PC|U|UNITE|UNITES)\b", item_raw_content, re.IGNORECASE | re.DOTALL) 
            if quantity_match:
                quantity_str = quantity_match.group(1).strip()
                quantity_val = parse_numeric_value(quantity_str)
                print(f"Quantité trouvée (str): {quantity_str}, (val): {quantity_val}") # DEBUG PRINT
            
            # 2. Extraire les Prix (Unitaire et Total) - Chercher dans la partie après "Prix brut"
            price_start_match = re.search(r"Prix\s*brut", item_raw_content, re.IGNORECASE | re.DOTALL)
            
            all_raw_price_strings_in_segment = []
            parsed_price_values_from_segment = []

            if price_start_match:
                print(f"'Prix brut' trouvé à l'index: {price_start_match.start()}") # DEBUG PRINT
                text_after_prix_brut = item_raw_content[price_start_match.end():].strip()
                print(f"Texte après 'Prix brut':\n{text_after_prix_brut}") # DEBUG PRINT
                
                price_number_pattern_str = r"\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{1,2})?" # Allow 1 or 2 decimal digits
                
                all_raw_price_strings_in_segment = re.findall(
                    r"(" + price_number_pattern_str + r")",
                    text_after_prix_brut,
                    re.IGNORECASE | re.DOTALL
                )
                
                print(f"Tous les candidats prix bruts trouvés dans le segment: {all_raw_price_strings_in_segment}") # DEBUG PRINT

                parsed_price_values_from_segment = [
                    parse_numeric_value(s_val) for s_val in all_raw_price_strings_in_segment 
                    if parse_numeric_value(s_val) is not None
                ]
                
                print(f"Valeurs numériques parsées après 'Prix brut': {parsed_price_values_from_segment}") # DEBUG PRINT
                
                # Heuristique: le dernier nombre est le Total, l'avant-dernier est le Prix Unitaire.
                if len(parsed_price_values_from_segment) >= 2:
                    total_line_price_val = parsed_price_values_from_segment[-1]
                    unit_price_val = parsed_price_values_from_segment[-2]
                    print(f"Dédution: Total={total_line_price_val}, Unit={unit_price_val}") # DEBUG PRINT
                elif len(parsed_price_values_from_segment) == 1:
                    total_line_price_val = parsed_price_values_from_segment[0]
                    if quantity_val == 1.0: 
                        unit_price_val = parsed_price_values_from_segment[0]
                    else:
                        unit_price_val = None 
                    print(f"Dédution: Total={total_line_price_val}, Unit={unit_price_val} (single value, Qty=1 check)") # DEBUG PRINT
                else:
                    total_line_price_val = None
                    unit_price_val = None
                    print("Dédution: Pas assez de prix trouvés.") # DEBUG PRINT
                
                print("--- Fin du débogage des prix/quantités ---") # DEBUG PRINT

            else:
                print(f"ATTENTION: 'Prix brut' non trouvé dans le bloc pour {position}, {codet}. Les prix ne seront pas extraits.")
                print("--- Fin du débogage des prix/quantités ---") # DEBUG PRINT

            # Apply parsed values
            row_data["CMDCodetQuantity"] = quantity_val
            row_data["CMDCodetUnitPrice"] = unit_price_val 
            row_data["CMDCodetTotlaLinePrice"] = total_line_price_val 

            # --- Extract and clean Description (CMDCodetNom) ---
            description_raw = item_raw_content
            
            # Remove detected quantity string occurrences. Use original matched string for removal.
            if quantity_match:
                description_raw = description_raw.replace(quantity_match.group(0), '', 1) 
            
            # Remove "Prix brut" and the associated price lines from description_raw
            if price_start_match: # Check if "Prix brut" was found to proceed with removal
                description_raw = re.sub(r"Prix\s*brut", "", description_raw, flags=re.IGNORECASE | re.DOTALL)
                
                elements_to_remove_from_description = []
                for s_val_to_remove in all_raw_price_strings_in_segment: 
                    elements_to_remove_from_description.append(r'\s*' + re.escape(s_val_to_remove) + r'(?:\s*EUR)?(?:\s*PC|\s*U|\s*UNITE|\s*UNITES)?\s*')
                
                elements_to_remove_from_description.sort(key=len, reverse=True) 

                for elem_pattern in elements_to_remove_from_description:
                    description_raw = re.sub(elem_pattern, ' ', description_raw, flags=re.IGNORECASE | re.MULTILINE)
                    description_raw = re.sub(r'\s{2,}', ' ', description_raw)

            # Nettoyage des patterns communs restants
            description_raw = re.sub(r"Appel\s*sur\s*contrat\s*CC\d+", "", description_raw, flags=re.IGNORECASE | re.DOTALL)
            description_raw = re.sub(r"________________.*", "", description_raw, flags=re.DOTALL) 
            description_raw = re.sub(r"\n\s*\n", "\n", description_raw) 
            
            description_raw = description_raw.strip()
            description_raw = description_raw.replace('\n', ' ') 
            row_data["CMDCodetNom"] = description_raw
            
            table_data.append(row_data)
            print(f"Ligne extraite: {row_data}")

        except Exception as e:
            print(f"Erreur lors du traitement d'un bloc d'article: {e}. Bloc: \n{item_raw_data['content'][:200]}...")
            row_data["CMDCodetNom"] = item_raw_data['content'].replace('\n', ' ')
            row_data["CMDCodetQuantity"] = None
            row_data["CMDCodetUnitPrice"] = None
            row_data["CMDCodetTotlaLinePrice"] = None
            table_data.append(row_data)

    return table_data


# --- Routes de l'API ---

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de vérification de santé (FR-5.2)."""
    return jsonify({"status": "healthy", "service": "Docling API", "version": "1.18.0", "rules_loaded": bool(extraction_rules)}), 200 # Updated version

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
        
        # --- ÉTAPE 1: Extraction initiale de tout le texte du PDF, page par page ---
        pages_raw_text = []
        try:
            pages_raw_text = extract_text_from_pdf_per_page(file_stream)
            full_text_raw = "\n".join(pages_raw_text) # Concaténer tout le texte pour les champs généraux
            print(f"Texte extrait directement (longueur: {len(full_text_raw)}).")
            print("--- DÉBUT DU TEXTE BRUT DU PDF (pour débogage) ---")
            print(full_text_raw)
            print("--- FIN DU TEXTE BRUT DU PDF ---")
        except Exception as e:
            print(f"Erreur lors de la lecture du PDF avec pdfminer.six: {e}. Le document est peut-être scanné ou corrompu.")
            pages_raw_text = []
            full_text_raw = ""

        # --- ÉTAPE 2: Pré-traitement et nettoyage de chaque page pour les données de tableau ---
        cleaned_pages_for_table = []
        page_header_regex = r"(?:Commande de livraison\s*N°.*?\(A\s*rappeler\s*dans\s*toute\s*correspondance\))" # Top left header
        page_footer_regex = r"(?:Enedis,\s*SA\s*à\s*directoire(?:.|\n)*?PAGE\s*\d+\s*\/\s*\d+)" # Bottom footer block
        # Generic table header line if it appears on multiple pages
        generic_table_header_line_regex = r"D\u00e9signation\s*Quantit\u00e9\s*\|\s*P\.U\.\s*HT\s*Montant\s*HT(?:.|\n)*?EUR" 

        for i, page_text in enumerate(pages_raw_text):
            cleaned_page_content = page_text
            
            # Remove top page header from each page
            cleaned_page_content = re.sub(page_header_regex, "", cleaned_page_content, flags=re.IGNORECASE | re.DOTALL)
            
            # Remove bottom page footer from each page
            cleaned_page_content = re.sub(page_footer_regex, "", cleaned_page_content, flags=re.IGNORECASE | re.DOTALL)
            
            # Remove table header line (as the table_start_marker in process_table_fields will handle it)
            # This is to prevent re-matching headers as part of item content.
            cleaned_page_content = re.sub(generic_table_header_line_regex, "", cleaned_page_content, flags=re.IGNORECASE | re.DOTALL)

            # Remove separator lines that appear frequently
            cleaned_page_content = re.sub(r"________________.*", "", cleaned_page_content, flags=re.DOTALL)
            
            cleaned_pages_for_table.append(cleaned_page_content.strip())
        
        # Concaténer les pages nettoyées pour le traitement du tableau
        full_text_cleaned_for_table = "\n".njoin(cleaned_pages_for_table) 
        print(f"--- Texte nettoyé pour le tableau (longueur: {len(full_text_cleaned_for_table)}) ---")
        print(full_text_cleaned_for_table[:700]) # First 700 chars for debug
        print("--- Fin du texte nettoyé pour le tableau ---")

        if not full_text_cleaned_for_table.strip():
            print("Texte PDF vide ou trop nettoyé, une logique d'OCR serait appliquée ici pour les PDF scannés.")

        # --- ÉTAPE 3: Traitement des champs ---
        # Les champs généraux sont souvent sur la première page et peuvent inclure des éléments des en-têtes globaux.
        # Utiliser le texte brut complet pour les champs généraux.
        general_data = process_general_fields(full_text_raw, extraction_rules) 
        
        # Les données du tableau sont extraites du texte nettoyé et concaténé.
        line_items_data = process_table_fields(full_text_cleaned_for_table, extraction_rules) 

        extracted_output = {
            "CMDRefEnedis": general_data.get("CMDRefEnedis"),
            "CMDDateCommande": general_data.get("CMDDateCommande"),
            "TotalHT": general_data.get("TotalHT"),
            "line_items": line_items_data,
            "confidence_score": 0.85, 
            "extracted_from": file.filename,
            "extraction_method": "Textual PDF processing (with item block parsing)" if full_text_raw.strip() else "Failed Text Extraction/OCR needed"
        }
        
        return jsonify(extracted_output), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)