# start_api.py
#
# Version: 1.13.0
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
    """
    print("INFO: Tentative d'extraction de tableau par blocs d'articles (Version 1.13.0).") # Updated version
    
    table_data = []
    
    table_rules = rules.get("table_fields", {})
    columns_info = table_rules.get("columns", [])

    # Trouver la section du tableau après l'en-tête
    table_start_marker_regex = r"(D\u00e9signation|Désignation|Quantit\u00e9|Quantité|P\.U\.\s**HT|Montant\s*HT).*?\n"
    match_table_start = re.search(table_start_marker_regex, full_text, re.IGNORECASE | re.DOTALL)

    table_content = ""
    if match_table_start:
        table_content = full_text[match_table_start.start():].strip() 
        print(f"Texte pour l'analyse de tableau (après en-tête détectée):\n{table_content[:700]}...")
    else:
        print("ATTENTION: Marqueur de début de tableau (en-tête de colonne) non trouvé. Analyse sur le texte brut complet.")
        table_content = full_text

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
            
            # 1. Extraire la Quantité (souvent un nombre suivi de PC, U, etc., n'importe où dans le bloc)
            quantity_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:PC|U|UNITE|UNITES)\b", item_raw_content, re.IGNORECASE | re.DOTALL) 
            if quantity_match:
                quantity_str = quantity_match.group(1).strip()
                quantity_val = parse_numeric_value(quantity_str)
            
            # 2. Extraire les Prix (Unitaire et Total) - Chercher dans la partie après "Prix brut" ou dans les dernières lignes
            price_start_index = item_raw_content.lower().find("prix brut")
            if price_start_index != -1:
                # Si "Prix brut" est trouvé, on cherche les prix dans le texte qui suit.
                text_after_prix_brut = item_raw_content[price_start_index:].strip()
                
                # Regex pour trouver les deux derniers nombres dans la section "après Prix brut"
                # On utilise price_number_pattern_str pour les nombres.
                price_number_pattern_str = r"\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{2})?"
                
                # Trouver tous les nombres potentiels dans cette section
                all_price_candidates_in_segment = re.findall(
                    r"(" + price_number_pattern_str + r")",
                    text_after_prix_brut,
                    re.IGNORECASE | re.DOTALL
                )
                
                # Convertir en float et filtrer les doublons, en conservant l'ordre d'apparition
                unique_numeric_values_after_prix_brut = []
                seen_values_after_prix_brut = set()
                for s_val in all_price_candidates_in_segment:
                    f_val = parse_numeric_value(s_val)
                    if f_val is not None and f_val not in seen_values_after_prix_brut:
                        unique_numeric_values_after_prix_brut.append(f_val)
                        seen_values_after_prix_brut.add(f_val)
                
                # Heuristique: les 2 derniers nombres uniques sont le Prix Unitaire et le Prix Total
                if len(unique_numeric_values_after_prix_brut) >= 2:
                    total_line_price_val = unique_numeric_values_after_prix_brut[-1]
                    unit_price_val = unique_numeric_values_after_prix_brut[-2]
                elif len(unique_numeric_values_after_prix_brut) == 1:
                    total_line_price_val = unique_numeric_values_after_prix_brut[0]
                    unit_price_val = None
                else:
                    total_line_price_val = None
                    unit_price_val = None
            else:
                print(f"ATTENTION: 'Prix brut' non trouvé dans le bloc pour {position}, {codet}. Les prix ne seront pas extraits.")
                # Fallback: Si "Prix brut" n'est pas trouvé, les prix restent None.

            # Apply parsed values
            row_data["CMDCodetQuantity"] = quantity_val
            row_data["CMDCodetUnitPrice"] = unit_price_val 
            row_data["CMDCodetTotlaLinePrice"] = total_line_price_val 

            # --- Extract and clean Description (CMDCodetNom) ---
            description_raw = item_raw_content
            
            # Remove detected quantity string occurrences
            if quantity_match:
                description_raw = description_raw.replace(quantity_match.group(0), '', 1) 
            
            # Remove "Prix brut" and the associated price lines from description_raw
            if price_start_index != -1:
                # Try to remove the part from "Prix brut" to the end of prices
                # This is a bit tricky, but we can try to locate the numerical values (unit and total) in the raw text
                # and remove them. Given the consistent pattern, we can also remove 'Prix brut' and lines around it.
                
                # Remove "Prix brut" itself.
                description_raw = re.sub(r"Prix\s*brut", "", description_raw, flags=re.IGNORECASE | re.DOTALL)
                
                # Remove the actual numerical price strings found if they exist in the raw content
                if unit_price_val is not None:
                    # Replace with comma decimal for string comparison/removal
                    str_val = str(unit_price_val).replace('.',',')
                    description_raw = re.sub(r'\s*' + re.escape(str_val) + r'\s*EUR\s*$', '', description_raw, flags=re.IGNORECASE | re.MULTILINE)
                    description_raw = re.sub(r'\s*' + re.escape(str_val) + r'\s*$', '', description_raw, flags=re.IGNORECASE | re.MULTILINE)
                if total_line_price_val is not None:
                    str_val = str(total_line_price_val).replace('.',',')
                    description_raw = re.sub(r'\s*' + re.escape(str_val) + r'\s*EUR\s*$', '', description_raw, flags=re.IGNORECASE | re.MULTILINE)
                    description_raw = re.sub(r'\s*' + re.escape(str_val) + r'\s*$', '', description_raw, flags=re.IGNORECASE | re.MULTILINE)

            # Nettoyage des patterns communs restants
            description_raw = re.sub(r"Appel\s*sur\s*contrat\s*CC\d+", "", description_raw, flags=re.IGNORECASE | re.DOTALL)
            description_raw = re.sub(r"________________.*", "", description_raw, flags=re.DOTALL) 
            description_raw = re.sub(r"\n\s*\n", "\n", description_raw) # Remove multiple empty lines
            
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
    return jsonify({"status": "healthy", "service": "Docling API", "version": "1.13.0", "rules_loaded": bool(extraction_rules)}), 200 # Updated version

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