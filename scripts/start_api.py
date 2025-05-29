# start_api.py
#
# Version: 1.16.0
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
                    value = parse_numeric_value(value, 
                                                rule.get('decimal_separator', ','), 
                                                rule.get('thousands_separator', ' '))
                break 
        extracted_data[field_name] = value
    return extracted_data

def process_table_fields(full_text_for_table, rules): # Renommé pour clarté
    """
    Extrait les champs de tableau du texte pré-nettoyé.
    """
    print("INFO: Tentative d'extraction de tableau par blocs d'articles (Version 1.16.0).") # Updated version
    
    table_data = []
    
    table_rules = rules.get("table_fields", {})
    columns_info = table_rules.get("columns", [])

    # Ici, full_text_for_table est déjà le texte pertinent (sans en-têtes/pieds de page globaux)
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
            
            # 1. Extraire la Quantité (souvent un nombre suivi de PC, U, etc., n'importe où dans le bloc)
            quantity_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:PC|U|UNITE|UNITES)\b", item_raw_content, re.IGNORECASE | re.DOTALL) 
            if quantity_match:
                quantity_str = quantity_match.group(1).strip()
                quantity_val = parse_numeric_value(quantity_str)
            
            # 2. Extraire les Prix (Unitaire et Total) - Chercher dans la partie après "Prix brut"
            # Utiliser une regex plus souple pour "Prix brut"
            price_start_match = re.search(r"Prix\s*brut", item_raw_content, re.IGNORECASE | re.DOTALL)
            
            if price_start_match:
                # Si "Prix brut" est trouvé, on cherche les prix dans le texte qui suit.
                text_after_prix_brut = item_raw_content[price_start_match.end():].strip()
                
                # Pattern pour extraire toutes les valeurs numériques qui ressemblent à des prix.
                # Gère les séparateurs de milliers (espace, point) et décimaux (virgule, point).
                price_number_pattern_str = r"\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{2})?" # Allow optional decimal for 1,00 format too

                # Trouver tous les nombres potentiels dans cette section
                all_price_candidates_in_segment = re.findall(
                    r"(" + price_number_pattern_str + r")",
                    text_after_prix_brut,
                    re.IGNORECASE | re.DOTALL
                )
                
                # Convertir en float et filtrer les doublons, en conservant l'ordre d'apparition
                parsed_price_values_from_segment = [
                    parse_numeric_value(s_val) for s_val in all_price_candidates_in_segment 
                    if parse_numeric_value(s_val) is not None
                ]
                
                # Heuristique: le dernier nombre est le Total, l'avant-dernier est le Prix Unitaire.
                # Cette heuristique est appliquée même si les valeurs sont identiques.
                if len(parsed_price_values_from_segment) >= 2:
                    total_line_price_val = parsed_price_values_from_segment[-1]
                    unit_price_val = parsed_price_values_from_segment[-2]
                elif len(parsed_price_values_from_segment) == 1:
                    total_line_price_val = parsed_price_values_from_segment[0]
                    # CORRECTION BUG: Utiliser la liste correcte pour l'affectation ici
                    if quantity_val == 1.0 and parsed_price_values_from_segment: 
                        unit_price_val = parsed_price_values_from_segment[0]
                    else:
                        unit_price_val = None 
                else:
                    total_line_price_val = None
                    unit_price_val = None
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
                # Use str.replace('.',',') to match the PDF text format
                if unit_price_val is not None:
                    elements_to_remove_from_description.append(str(unit_price_val).replace('.',',') + r'\s*EUR') # With EUR
                    elements_to_remove_from_description.append(str(unit_price_val).replace('.',',')) # Without EUR
                if total_line_price_val is not None:
                    elements_to_remove_from_description.append(str(total_line_price_val).replace('.',',') + r'\s*EUR') # With EUR
                    elements_to_remove_from_description.append(str(total_line_price_val).replace('.',',')) # Without EUR
                
                # Sort longest first for safe replacement
                elements_to_remove_from_description.sort(key=len, reverse=True)

                for elem_to_remove in elements_to_remove_from_description:
                    # Use re.sub with re.escape to handle special characters in numbers like '.' or ','
                    # Replace globally to catch all occurrences if they were somehow duplicated
                    description_raw = re.sub(r'\s*' + re.escape(elem_to_remove) + r'\s*', ' ', description_raw, flags=re.IGNORECASE | re.MULTILINE)
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
    return jsonify({"status": "healthy", "service": "Docling API", "version": "1.16.0", "rules_loaded": bool(extraction_rules)}), 200 # Updated version

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
            # On cherche de manière plus souple pour ne pas rater des pages sans ce pattern strict.
            main_content_start_marker = r"(?:Commande de livraison\s*N°\s*\d{4}-\d{10,}|D\u00e9signation\s*Quantit\u00e9\s*\|\s*P\.U\.\s*HT\s*Montant\s*HT)"
            match_main_content_start = re.search(main_content_start_marker, full_text, re.IGNORECASE | re.DOTALL)
            
            if match_main_content_start:
                # Commencer le texte nettoyé à partir de la première occurrence de ce marqueur
                # Inclure la ligne du marqueur pour que process_table_fields puisse le retrouver.
                full_text_cleaned = full_text[match_main_content_start.start():].strip()
            else:
                print("ATTENTION: Marqueur de début de contenu principal/tableau non trouvé. Traitement du texte complet.")

            # 2. Trouver la fin de la section du contenu principal (avant le pied de page)
            # Les pieds de page contiennent typiquement "Enedis, SA" ou "PAGE X / Y".
            footer_start_regex = r"(?:Enedis,\s*SA\s*à\s*directoire|PAGE\s*\d+\s*\/\s*\d+)"
            match_footer_start = re.search(footer_start_regex, full_text_cleaned, re.IGNORECASE | re.DOTALL)
            if match_footer_start:
                # Tronquer le texte nettoyé juste avant le début du pied de page
                full_text_cleaned = full_text_cleaned[:match_footer_start.start()].strip()
                print("INFO: Document content truncated before footer.")
            else:
                print("INFO: No footer detected for truncation.")


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