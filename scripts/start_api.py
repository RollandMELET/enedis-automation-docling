# start_api.py
#
# Version: 1.3.0
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
    Tente d'extraire les champs de tableau du texte en utilisant une logique simple.
    Ceci n'est PAS une extraction Docling complète de tableau mais une première tentative
    basée sur des expressions régulières pour valider le concept.
    """
    print("INFO: Tentative d'extraction de tableau basée sur le texte brut (non simulée).")
    
    table_data = []
    
    table_rules = rules.get("table_fields", {})
    start_keywords = table_rules.get("start_keywords", [])
    end_keywords = table_rules.get("end_keywords", [])
    columns_info = table_rules.get("columns", [])

    # Construire un pattern de début de tableau avec les mots-clés, insensible à la casse
    start_pattern = "|".join(re.escape(kw) for kw in start_keywords)
    # Construire un pattern de fin de tableau
    end_pattern = "|".join(re.escape(kw) for kw in end_keywords)

    # Trouver la section du tableau
    # Chercher la section entre le premier mot-clé de début (parmi start_keywords)
    # et le premier mot-clé de fin (parmi end_keywords) qui suit.
    # On utilise .*? pour une correspondance non gourmande.
    table_section_match = re.search(
        f"({start_pattern}.*?)(?={end_pattern})", 
        full_text,
        re.IGNORECASE | re.DOTALL
    )

    table_text = ""
    if table_section_match:
        table_text = table_section_match.group(1)
        # Après avoir trouvé la section du tableau, nous voulons enlever l'en-tête
        # Pour une détection plus robuste de l'en-tête, on pourrait chercher les header_patterns
        # Pour l'instant, on se base sur la première ligne contenant les mots-clés de début.
        
        # Trouver la ligne qui contient un des start_keywords pour identifier le début réel de la table
        # et commencer à extraire les lignes *après* cette en-tête.
        header_line_end_index = -1
        for kw in start_keywords:
            # Chercher la ligne qui contient le mot-clé d'en-tête (en insenssible à la casse)
            # Puis trouver l'index de la fin de cette ligne.
            match_header_line = re.search(f".*?{re.escape(kw)}.*?\n", table_text, re.IGNORECASE)
            if match_header_line:
                # Si un en-tête est trouvé, on prend la fin de cette ligne comme point de départ
                header_line_end_index = max(header_line_end_index, match_header_line.end())

        if header_line_end_index != -1:
            table_text = table_text[header_line_end_index:].strip()
            print(f"Texte du tableau identifié (après en-tête):\n{table_text[:500]}...") # Afficher les 500 premiers caractères pour débogage
        else:
            print("ATTENTION: En-tête de tableau non trouvée dans la section identifiée. Traitement du texte entier de la section.")
            # Si pas d'en-tête identifiable, on utilise toute la section trouvée initialement
    else:
        print("ATTENTION: Section de tableau non trouvée avec les mots-clés spécifiés.")
        return [] # Retourne vide si la section n'est pas trouvée

    # Ici, la logique de "Docling" devrait analyser la structure du tableau (lignes, colonnes)
    # Pour l'instant, nous allons tenter d'extraire chaque ligne et de parser les champs
    # en se basant sur des suppositions de format (ex: numéro de position au début, puis codet, etc.)

    # Simplification : Traiter chaque ligne non vide comme une ligne potentielle du tableau
    lines = [line.strip() for line in table_text.split('\n') if line.strip()]

    for line in lines:
        row_data = {}
        # Tentative d'extraction des champs pour chaque ligne
        # C'est ici que la complexité augmente considérablement pour une vraie robustesse.
        # Nous allons utiliser une regex simple pour extraire les nombres et descriptions.

        # Adjusted regex to specifically target patterns as seen in provided PDF.
        # This will be very specific and likely need iteration.
        # It attempts to capture:
        # 1. Position (5 digits, e.g., 00010)
        # 2. Codet (7-8 digits)
        # 3. Description (non-greedy, any character until quantity)
        # 4. Quantity (number with optional comma decimal, followed by optional unit like PC)
        # 5. Unit Price (number with optional comma decimal, followed by EUR)
        # 6. Total Line Price (number with optional comma decimal, followed by EUR, end of line)
        
        # The regex is improved to handle multi-line descriptions and units/EUR.
        # It's challenging due to the free-form text.
        # Regex components:
        # ^\s*(\d{5})\s*                  - Start of line, optional spaces, (Group 1: 5-digit position)
        # (\d{7,8})\s*                    - (Group 2: 7 or 8-digit Codet), optional spaces
        # (.+?)                           - (Group 3: Non-greedy match for Description)
        # (?:\s*\n?\s*PRIX BRUT)?\s*      - Optional "PRIX BRUT" over new lines, then spaces
        # (\d+(?:,\d+)?)\s*(?:PC|U|EUR|T|Kg|l|PC|UNITE|UNITES)?\s*  - (Group 4: Quantity), optional spaces, optional unit, optional spaces
        # (\d+(?:,\d+)?)\s*EUR\s*         - (Group 5: Unit Price), spaces, "EUR", spaces
        # (\d+(?:,\d+)?)\s*EUR$           - (Group 6: Total Line Price), spaces, "EUR", end of line
        
        # This regex is an *initial attempt* and will likely need significant refinement.
        # It assumes a fixed column order and structure.

        # Regex revised based on the provided PDF content and common patterns
        # It tries to be more flexible for description and units.
        line_pattern = re.compile(
            r"^\s*(\d{5})\s*" # Group 1: CMDCodetPosition (5 digits, start of line)
            r"(\d{7,8})\s*" # Group 2: CMDCodet (7 or 8 digits)
            r"(.+?)" # Group 3: CMDCodetNom (non-greedy match for description)
            r"(?:\s*\n?\s*Prix\s*brut)?" # Optional "Prix brut" that might break the line
            r"\s*(\d+(?:[.,]\d+)?)\s*(?:PC|U|EUR|T|Kg|l|UNITE|UNITES)?\s*" # Group 4: Quantity (number with . or , decimal, optional unit)
            r"(\d+(?:[.,]\d+)?)\s*EUR\s*" # Group 5: Unit Price (number with . or , decimal, EUR)
            r"(\d+(?:[.,]\d+)?)\s*EUR$" # Group 6: Total Line Price (number with . or , decimal, EUR, end of line)
            , re.IGNORECASE | re.DOTALL # DOTALL is crucial for multi-line descriptions
        )

        match = line_pattern.search(line)
        if match:
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

            try:
                row_data["CMDCodetPosition"] = match.group(1).strip()
                row_data["CMDCodet"] = match.group(2).strip()
                row_data["CMDCodetNom"] = match.group(3).strip()
                
                # Get separator from rules.json for quantity, unit price, total price
                # We'll use the 'decimal_separator' from the rules for parsing
                qty_rule = next((col for col in columns_info if col['field_name'] == 'CMDCodetQuantity'), {})
                unit_price_rule = next((col for col in columns_info if col['field_name'] == 'CMDCodetUnitPrice'), {})
                total_line_price_rule = next((col for col in columns_info if col['field_name'] == 'CMDCodetTotlaLinePrice'), {})
                
                row_data["CMDCodetQuantity"] = parse_numeric_value(match.group(4).strip(), qty_rule.get('decimal_separator', ','), qty_rule.get('thousands_separator', ' '))
                row_data["CMDCodetUnitPrice"] = parse_numeric_value(match.group(5).strip(), unit_price_rule.get('decimal_separator', ','), unit_price_rule.get('thousands_separator', ' '))
                row_data["CMDCodetTotlaLinePrice"] = parse_numeric_value(match.group(6).strip(), total_line_price_rule.get('decimal_separator', ','), total_line_price_rule.get('thousands_separator', ' '))

                table_data.append(row_data)
                print(f"Ligne extraite: {row_data}")
            except IndexError as ie:
                print(f"Erreur d'index dans le match pour la ligne: '{line}'. Erreur: {ie}")
            except Exception as e:
                print(f"Erreur inattendue lors du traitement de la ligne: '{line}'. Erreur: {e}")
        else:
            # print(f"Aucune correspondance trouvée pour la ligne: '{line}'") # Décommenter pour un débogage détaillé
            pass # Ignorer les lignes qui ne correspondent pas au pattern
    
    return table_data


# --- Routes de l'API (pas de changement) ---

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de vérification de santé (FR-5.2)."""
    # Note: La version ici est la version du script start_api.py.
    # Mettre à jour manuellement si vous modifiez la version du script.
    return jsonify({"status": "healthy", "service": "Docling API", "version": "1.3.0", "rules_loaded": bool(extraction_rules)}), 200

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
        # Maintenant, line_items_data appellera la nouvelle logique d'extraction
        line_items_data = process_table_fields(full_text, extraction_rules) 

        extracted_output = {
            "CMDRefEnedis": general_data.get("CMDRefEnedis"),
            "CMDDateCommande": general_data.get("CMDDateCommande"),
            "TotalHT": general_data.get("TotalHT"),
            "line_items": line_items_data,
            "confidence_score": 0.85, 
            "extracted_from": file.filename,
            "extraction_method": "Textual PDF processing (with basic table parsing)" if full_text.strip() else "Failed Text Extraction/OCR needed"
        }
        
        return jsonify(extracted_output), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)