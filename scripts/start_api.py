# start_api.py
#
# Version: 1.17.0
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
# NOUVELLE VERSION : plus robuste pour la détection des séparateurs
def parse_numeric_value(value_str):
    if value_str is None:
        return None
    
    # Standardize to a format float() can understand (e.g., '1234.56')
    # First, handle thousands separators (space or dot)
    cleaned_value = value_str.replace(' ', '').replace('.', '') # Remove all spaces and dots as thousands separators

    # Then, handle decimal separator (comma or dot)
    if ',' in cleaned_value:
        cleaned_value = cleaned_value.replace(',', '.') # Replace comma with dot for float conversion
    
    # Additional check: if original had multiple dots (e.g., 1.234.567,89) and we removed all,
    # and it ended up with a single dot, it might still be a thousands separator.
    # We assume standard European format (dot for thousands, comma for decimals) or US format.
    # Given your documents use "X.XXX,XX", let's assume dot is thousands and comma is decimal.
    # If it was "X,XXX.XX", then comma is thousands and dot is decimal.

    # Re-evaluate based on most common format in your document (X.XXX,XX) where dot is thousands, comma is decimal.
    # So, remove dots, replace comma with dot for final float conversion.
    temp_value = value_str.replace(' ', '') # Remove spaces first
    if ',' in temp_value and '.' in temp_value:
        # Check which one is the decimal separator by its position (last one)
        if temp_value.rfind(',') > temp_value.rfind('.'): # Comma is decimal
            temp_value = temp_value.replace('.', '') # Remove dots (thousands)
            cleaned_value = temp_value.replace(',', '.') # Replace comma (decimal) with dot
        else: # Dot is decimal
            temp_value = temp_value.replace(',', '') # Remove commas (thousands)
            cleaned_value = temp_value # Dot is already the decimal
    elif ',' in temp_value: # Only comma present, assume it's decimal
        cleaned_value = temp_value.replace(',', '.')
    else: # Only dot present, or no separator, assume dot is decimal or integer
        cleaned_value = temp_value # No change needed if it's already dot or no separator

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
                    # Call new parse_numeric_value without specific separators
                    value = parse_numeric_value(value) 
                break 
        extracted_data[field_name] = value
    return extracted_data

def process_table_fields(full_text_for_table, rules): # Renommé pour clarté
    """
    Extrait les champs de tableau du texte pré-nettoyé.
    """
    print("INFO: Tentative d'extraction de tableau par blocs d'articles (Version 1.17.0).") # Updated version
    
    table_data = []
    
    table_rules = rules.get("table_fields", {})
    columns_info = rules.get("columns", []) # CORRECTION: columns_info doit venir de rules direct

    table_content = full_text_for_table 

    # Utiliser re.split pour découper le contenu en blocs d'articles fiables.
    item_start_delimiter_regex = re.compile(
        r"^\s*(\d{5})\s*(\d{7,8})\s*", # Group 1: CMDCodetPosition, Group 2: CMDCodet
        re.IGNORECASE | re.MULTILINE
    )

    split_parts = item_start_delimiter_regex.split(table_content)
    
    raw_item_blocks = []
    if split_parts and len(split_parts) > 1:
        # The first element is empty if the text starts with a delimiter. We start at index 1.
        for i in range(1, len(split_parts), 3):
            if i + 2 < len(split_parts): # Ensure there's position, codet, and content
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
            print(f"Contenu brut du bloc de l'article (complet):\n{item_raw_content}") # Now print full content, should be complete

            # --- Extraction des prix et quantité ---
            
            # 1. Extraire la Quantité (souvent un nombre suivi de PC, U, etc., n'importe où dans le bloc)
            quantity_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:PC|U|UNITE|UNITES)\b", item_raw_content, re.IGNORECASE | re.DOTALL) 
            if quantity_match:
                quantity_str = quantity_match.group(1).strip()
                quantity_val = parse_numeric_value(quantity_str)
                print(f"Quantité trouvée (str): {quantity_str}, (val): {quantity_val}") # DEBUG PRINT
            
            # 2. Extraire les Prix (Unitaire et Total) - Chercher dans la partie après "Prix brut"
            price_start_match = re.search(r"Prix\s*brut", item_raw_content, re.IGNORECASE | re.DOTALL)
            
            # Initialize these lists/values even if 'Prix brut' is not found
            all_raw_price_strings_in_segment = []
            parsed_price_values_from_segment = []

            if price_start_match:
                print(f"'Prix brut' trouvé à l'index: {price_start_match.start()}") # DEBUG PRINT
                text_after_prix_brut = item_raw_content[price_start_match.end():].strip()
                print(f"Texte après 'Prix brut':\n{text_after_prix_brut}") # DEBUG PRINT
                
                # Pattern pour extraire toutes les valeurs numériques qui ressemblent à des prix.
                # Doit être très robuste.
                # Capture les nombres avec un ou deux chiffres après la virgule/point décimal,
                # et gère les séparateurs de milliers (espace, point).
                price_number_pattern_str = r"\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{1,2})?" # Allow 1 or 2 decimal digits
                
                # Trouver toutes les chaînes de nombres potentielles dans cette section
                all_raw_price_strings_in_segment = re.findall(
                    r"(" + price_number_pattern_str + r")",
                    text_after_prix_brut,
                    re.IGNORECASE | re.DOTALL
                )
                
                print(f"Tous les candidats prix bruts trouvés dans le segment: {all_raw_price_strings_in_segment}") # DEBUG PRINT

                # Convertir en float et filtrer les doublons, en conservant l'ordre d'apparition
                parsed_price_values_from_segment = [
                    parse_numeric_value(s_val) for s_val in all_raw_price_strings_in_segment 
                    if parse_numeric_value(s_val) is not None
                ]
                
                print(f"Valeurs numériques uniques parsées après 'Prix brut': {parsed_price_values_from_segment}") # DEBUG PRINT
                
                # Heuristique: le dernier nombre est le Total, l'avant-dernier est le Prix Unitaire.
                if len(parsed_price_values_from_segment) >= 2:
                    total_line_price_val = parsed_price_values_from_segment[-1]
                    unit_price_val = parsed_price_values_from_segment[-2]
                    print(f"Dédution: Total={total_line_price_val}, Unit={unit_price_val}") # DEBUG PRINT
                elif len(parsed_price_values_from_segment) == 1:
                    total_line_price_val = parsed_price_values_from_segment[0]
                    # If quantity is 1 and only one price is found, assume it's both Unit and Total price.
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
                
                # Remove the actual numerical price strings found if they exist in the raw content
                # To be robust, use the exact string representations that were parsed, with optional EUR suffix.
                # Sort elements to remove by length (longest first) to avoid partial replacements.
                
                elements_to_remove_from_description = []
                # Use all_raw_price_strings_in_segment (the raw strings from re.findall)
                for s_val_to_remove in all_raw_price_strings_in_segment: 
                    # Try to remove the number with optional EUR/unit
                    # Use re.escape to handle special characters like '.' or ',' in the number string
                    # Add optional spaces before and after the number string
                    elements_to_remove_from_description.append(r'\s*' + re.escape(s_val_to_remove) + r'(?:\s*EUR)?(?:\s*PC|\s*U|\s*UNITE|\s*UNITES)?\s*')
                
                elements_to_remove_from_description.sort(key=len, reverse=True) # Sort longest pattern first

                for elem_pattern in elements_to_remove_from_description:
                    # Use re.sub to remove all occurrences of this pattern in the description_raw
                    description_raw = re.sub(elem_pattern, ' ', description_raw, flags=re.IGNORECASE | re.MULTILINE)
                    # Clean up multiple spaces after replacement
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
    return jsonify({"status": "healthy", "service": "Docling API", "version": "1.17.0", "rules_loaded": bool(extraction_rules)}), 200 # Updated version

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

            # --- NOUVELLE ÉTAPE DE PRÉ-TRAITEMENT POUR ISOLER LE CONTENU PERTINENT ---
            full_text_cleaned = full_text # Initialiser avec le texte complet
            
            # 1. Trouver le début de la section du contenu principal / tableau
            # Chercher le début de la première page de commande ou le premier en-tête de tableau
            main_content_start_marker = r"(?:Commande de livraison\s*N°\s*\d{4}-\d{10,}|D\u00e9signation\s*Quantit\u00e9\s*\|\s*P\.U\.\s*HT\s*Montant\s*HT)"
            match_main_content_start = re.search(main_content_start_marker, full_text, re.IGNORECASE | re.DOTALL)
            
            if match_main_content_start:
                # Commencer le texte nettoyé à partir de la première occurrence de ce marqueur
                full_text_cleaned = full_text[match_main_content_start.start():].strip()
            else:
                print("ATTENTION: Marqueur de début de contenu principal/tableau non trouvé. Traitement du texte complet.")

            # 2. Trouver la fin de la section du contenu principal (avant le pied de page)
            # Ajout d'expressions régulières plus robustes pour les pieds de page
            footer_start_regex = r"(?:Enedis,\s*SA\s*à\s*directoire(?:.|\n)*?PAGE\s*\d+\s*\/\s*\d+)" # Capture from "Enedis, SA" to "PAGE X / Y"
            match_footer_start = re.search(footer_start_regex, full_text_cleaned, re.IGNORECASE | re.DOTALL)
            if match_footer_start:
                # Tronquer le texte nettoyé juste avant le début du pied de page
                full_text_cleaned = full_text_cleaned[:match_footer_start.start()].strip()
                print("INFO: Document content truncated before footer.")
            else:
                print("INFO: No footer detected for truncation.")

            # Ajout d'une dernière troncation pour le cas où "Total HT de la commande" global apparaît après les tableaux
            # et n'est pas déjà traité par le footer.
            total_ht_global_end_regex = r"(?:Total\s*HT\s*de\s*la\s*commande.*?(\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{2})?)\s*EUR)"
            match_total_ht_global_end = re.search(total_ht_global_end_regex, full_text_cleaned, re.IGNORECASE | re.DOTALL)
            if match_total_ht_global_end:
                # Tronquer le texte nettoyé juste avant ce match pour éviter d'inclure des éléments post-tableau
                full_text_cleaned = full_text_cleaned[:match_total_ht_global_end.start()].strip()
                print("INFO: Document content truncated before global Total HT.")


            if not full_text_cleaned.strip():
                print("Texte PDF vide ou trop nettoyé, une logique d'OCR serait appliquée ici pour les PDF scannés.")

        except Exception as e:
            print(f"Erreur lors de la lecture du PDF avec pdfminer.six: {e}. Le document est peut-être scanné ou corrompu.")
            full_text_cleaned = "" # Réinitialiser le texte nettoyé en cas d'erreur de lecture
            full_text = "" # S'assurer que le full_text est vide aussi si la lecture échoue
        
        general_data = process_general_fields(full_text, extraction_rules) # Utilise le full_text original pour les champs généraux (souvent en en-tête/pied de page)
        line_items_data = process_table_fields(full_text_cleaned, extraction_rules) # Utilise le texte nettoyé pour le traitement du tableau

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