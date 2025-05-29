# start_api.py
#
# Version: 1.12.0
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
    print("INFO: Tentative d'extraction de tableau par blocs d'articles (Version 1.12.0).") # Updated version
    
    table_data = []
    
    table_rules = rules.get("table_fields", {})
    columns_info = table_rules.get("columns", [])

    # Trouver la section du tableau après l'en-tête
    table_start_marker_regex = r"(D\u00e9signation|Désignation|Quantit\u00e9|Quantité|P\.U\.\s*HT|Montant\s*HT).*?\n"
    match_table_start = re.search(table_start_marker_regex, full_text, re.IGNORECASE | re.DOTALL)

    table_content = ""
    if match_table_start:
        # On prend tout le texte *à partir* de l'en-tête de tableau jusqu'à la fin du document.
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

            # --- Extraction des prix et quantité basée sur la structure "Prix brut" ---
            # Pattern: "Prix brut" (saut de ligne) [Quantité (optionnel)] (saut de ligne) Prix Unitaire (saut de ligne) Prix Total
            
            # Pattern pour extraire toutes les valeurs numériques qui ressemblent à des prix.
            # Gère les séparateurs de milliers (espace, point) et décimaux (virgule, point).
            price_number_pattern_str = r"\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{2})?"

            # Regex qui englobe la structure complète "Prix brut" + Quantité + PU + Total.
            # On cherche une correspondance à partir de "Prix brut"
            full_price_block_regex = re.compile(
                r"Prix\s*brut\s*" + # Ancre: "Prix brut"
                r"(?:\n\s*)?" + # Optionnel: ligne vide après "Prix brut"
                r"(" + price_number_pattern_str + r")\s*(?:PC|U|UNITE|UNITES)?\s*" + # Group 1: Quantité (optionnelle), avec unité
                r"(?:\n\s*)?" + # Optionnel: ligne vide après quantité
                r"(" + price_number_pattern_str + r")\s*EUR\s*" + # Group 2: Prix Unitaire
                r"(?:\n\s*)?" + # Optionnel: ligne vide après Prix Unitaire
                r"(" + price_number_pattern_str + r")\s*EUR\s*$" # Group 3: Prix Total (jusqu'à la fin de la ligne ou du bloc)
                , re.IGNORECASE | re.DOTALL | re.MULTILINE
            )
            
            price_extraction_match = full_price_block_regex.search(item_raw_content)

            if price_extraction_match:
                quantity_str = price_extraction_match.group(1)
                unit_price_str = price_extraction_match.group(2)
                total_line_price_str = price_extraction_match.group(3)
                
                # Convertir en float
                quantity_val = parse_numeric_value(quantity_str)
                unit_price_val = parse_numeric_value(unit_price_str)
                total_line_price_val = parse_numeric_value(total_line_price_str)
            else:
                print(f"ATTENTION: Structure 'Prix brut' ou données de prix/quantité non trouvées pour {position}, {codet}.")

            # Apply parsing rules
            row_data["CMDCodetQuantity"] = quantity_val
            row_data["CMDCodetUnitPrice"] = unit_price_val 
            row_data["CMDCodetTotlaLinePrice"] = total_line_price_val 

            # --- Extract and clean Description (CMDCodetNom) ---
            description_raw = item_raw_content
            
            # Retirer la partie du texte qui contient "Prix brut" et les valeurs numériques
            if price_extraction_match:
                # Retirer la chaîne exacte qui a matché dans la regex
                description_raw = description_raw.replace(price_extraction_match.group(0), '', 1) 
            
            # Nettoyage des patterns communs
            description_raw = re.sub(r"Appel\s*sur\s*contrat\s*CC\d+", "", description_raw, flags=re.IGNORECASE | re.DOTALL)
            description_raw = re.sub(r"________________.*", "", description_raw, flags=re.DOTALL) # Remove lines with underscores
            description_raw = re.sub(r"\n\s*\n", "\n", description_raw) # Remove multiple empty lines
            
            description_raw = description_raw.strip()
            description_raw = description_raw.replace('\n', ' ') # Ensure single-line output
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
    return jsonify({"status": "healthy", "service": "Docling API", "version": "1.12.0", "rules_loaded": bool(extraction_rules)}), 200 # Updated version

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