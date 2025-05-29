# start_api.py
#
# Version: 1.19.0
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
def parse_numeric_value(value_str):
    if value_str is None:
        return None
    
    # Remove all spaces and dots as thousands separators.
    # Heuristic: assume dot is thousands, comma is decimal for European format (X.XXX,XX)
    cleaned_value = value_str.replace(' ', '') # Remove spaces first
    
    # Handle cases like "1.000" where dot might be decimal or thousands.
    # Assume dot is thousands unless it's the only one and not followed by enough digits (e.g. "1.00" -> 1.0)
    # For now, remove all dots assuming they are thousands separators.
    cleaned_value = cleaned_value.replace('.', '') 

    # Replace comma (decimal) with dot for float conversion
    cleaned_value = cleaned_value.replace(',', '.') 

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
    print("INFO: Tentative d'extraction de tableau par blocs d'articles (Version 1.19.0).") # Updated version
    
    table_data = []
    
    table_rules = rules.get("table_fields", {})
    columns_info = table_rules.get("columns", []) # CORRECTION BUG: maintenant prend depuis table_rules

    table_content = full_text_for_table 
    print(f"DEBUG: Contenu de table_content avant split:\n{table_content[:700]}...")

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
    print(f"DEBUG: Nombre de blocs d'articles trouvés: {len(raw_item_blocks)}")

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

            print("--- Début du débogage des prix/quantités ---") 
            
            # 1. Extraire la Quantité (souvent un nombre suivi de PC, U, etc., n'importe où dans le bloc)
            quantity_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:PC|U|UNITE|UNITES)\b", item_raw_content, re.IGNORECASE | re.DOTALL) 
            if quantity_match:
                quantity_str = quantity_match.group(1).strip()
                quantity_val = parse_numeric_value(quantity_str)
                print(f"Quantité trouvée (str): {quantity_str}, (val): {quantity_val}")
            else:
                print("Quantité: Non trouvée.")
            
            # 2. Extraire les Prix (Unitaire et Total) - Chercher dans la partie après "Prix brut"
            price_start_match = re.search(r"Prix\s*brut", item_raw_content, re.IGNORECASE | re.DOTALL)
            
            all_raw_price_strings_in_segment = []
            parsed_price_values_from_segment = []

            if price_start_match:
                print(f"'Prix brut' trouvé à l'index: {price_start_match.start()}")
                text_after_prix_brut = item_raw_content[price_start_match.end():].strip()
                print(f"Texte après 'Prix brut':\n{text_after_prix_brut}")
                
                # CORRECTION REGEX: `price_number_pattern_str` doit être la même que `parse_numeric_value` s'attend.
                # On capture les nombres avec points ou virgules, qu'on nettoiera avec parse_numeric_value.
                price_number_pattern_str = r"\d{1,3}(?:[ .]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?" # Capture numbers like 1.000,00 or 1000.00 or 1,00

                all_raw_price_strings_in_segment = re.findall(
                    r"(" + price_number_pattern_str + r")",
                    text_after_prix_brut,
                    re.IGNORECASE | re.DOTALL
                )
                
                print(f"Tous les candidats prix bruts trouvés dans le segment: {all_raw_price_strings_in_segment}")

                parsed_price_values_from_segment = [
                    parse_numeric_value(s_val) for s_val in all_raw_price_strings_in_segment 
                    if parse_numeric_value(s_val) is not None
                ]
                
                print(f"Valeurs numériques parsées après 'Prix brut': {parsed_price_values_from_segment}")
                
                # Heuristique: le dernier nombre est le Total, l'avant-dernier est le Prix Unitaire.
                if len(parsed_price_values_from_segment) >= 2:
                    total_line_price_val = parsed_price_values_from_segment[-1]
                    unit_price_val = parsed_price_values_from_segment[-2]
                    print(f"Dédution: Total={total_line_price_val}, Unit={unit_price_val}")
                elif len(parsed_price_values_from_segment) == 1:
                    total_line_price_val = parsed_price_values_from_segment[0]
                    if quantity_val == 1.0: 
                        unit_price_val = parsed_price_values_from_segment[0]
                    else:
                        unit_price_val = None 
                    print(f"Dédution: Total={total_line_price_val}, Unit={unit_price_val} (single value, Qty=1 check)")
                else:
                    total_line_price_val = None
                    unit_price_val = None
                    print("Dédution: Pas assez de prix trouvés.")
                
                print("--- Fin du débogage des prix/quantités ---")

            else:
                print(f"ATTENTION: 'Prix brut' non trouvé dans le bloc pour {position}, {codet}. Les prix ne seront pas extraits.")
                print("--- Fin du débogage des prix/quantités ---")

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
            if price_start_match:
                description_raw = re.sub(r"Prix\s*brut", "", description_raw, flags=re.IGNORECASE | re.DOTALL)
                
                elements_to_remove_from_description = []
                for s_val_to_remove in all_raw_price_strings_in_segment: 
                    # Add optional EUR/units as they might be present in the raw text and need removal
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
    return jsonify({"status": "healthy", "service": "Docling API", "version": "1.19.0", "rules_loaded": bool(extraction_rules)}), 200 # Updated version

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
        
        # Regex pour les éléments à supprimer par page. Elles sont moins agressives maintenant.
        page_header_pattern_start = r"(?:Commande de livraison\s*N°\s*\d{4}-\d{10,}\s*\(A\s*rappeler\s*dans\s*toute\s*correspondance\))"
        page_footer_pattern_start = r"(?:Enedis,\s*SA\s*à\s*directoire(?:.|\n)*?PAGE\s*\d+\s*\/\s*\d+)" # Capture full footer block

        for i, page_text in enumerate(pages_raw_text):
            cleaned_page_content = page_text
            
            # Remove main document header (only if on page 1)
            if i == 0: # Only on the first page, remove the main header block
                match_header = re.search(page_header_pattern_start, cleaned_page_content, re.IGNORECASE | re.DOTALL)
                if match_header:
                    cleaned_page_content = cleaned_page_content.replace(match_header.group(0), '', 1) # Remove the header block
                    print(f"INFO: Removed main header from page {i+1}.")
            
            # Remove main document footer from each page
            match_footer = re.search(page_footer_pattern_start, cleaned_page_content, re.IGNORECASE | re.DOTALL)
            if match_footer:
                cleaned_page_content = cleaned_page_content.replace(match_footer.group(0), '', 1) # Remove the footer block
                print(f"INFO: Removed footer from page {i+1}.")
            
            # Remove general table header line if it appears on a page (to keep item content clean)
            # This is specific for the "Désignation | Quantité | P.U. HT | Montant HT" line.
            # Only remove it if it's the *only* thing on the line or very prominent, to avoid affecting item names.
            # It should ideally be handled by table_start_marker_regex in process_table_fields, but removing here too.
            # For now, let's keep this out, as it might remove item descriptions if they match.
            # The previous table_start_marker_regex in process_table_fields takes care of the header *before* splitting items.

            # Remove separator lines that appear frequently - This is usually safe.
            cleaned_page_content = re.sub(r"________________.*", "", cleaned_page_content, flags=re.DOTALL)
            
            cleaned_pages_for_table.append(cleaned_page_content.strip())
        
        # Concaténer les pages nettoyées pour le traitement du tableau
        full_text_cleaned_for_table = "\n".join(cleaned_pages_for_table) 
        print(f"--- Texte nettoyé pour le tableau (longueur: {len(full_text_cleaned_for_table)}) ---")
        print(full_text_cleaned_for_table[:1500]) # Print more characters for debug
        print("--- Fin du texte nettoyé pour le tableau ---")

        if not full_text_cleaned_for_table.strip():
            print("Texte PDF vide ou trop nettoyé, une logique d'OCR serait appliquée ici pour les PDF scannés.")

        # --- ÉTAPE 3: Traitement des champs ---
        general_data = process_general_fields(full_text_raw, extraction_rules) 
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