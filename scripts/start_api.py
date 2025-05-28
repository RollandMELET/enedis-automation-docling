# /app/scripts/start_api.py (dans le conteneur)
# ou localement: /Users/rollandmelet/Développement/Projets/CommandeEnedisTraitement/enedis-automation-docling/scripts/start_api.py

from flask import Flask, request, jsonify
import os
import time

app = Flask(__name__)

# Ce serait l'endroit où Docling serait réellement initialisé et où ses fonctions d'extraction seraient appelées.
# Pour l'instant, c'est une API "mock" qui simule une réponse.
# Plus tard, nous intégrerons la logique Docling réelle ici.

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de vérification de santé (FR-5.2)."""
    return jsonify({"status": "healthy", "service": "Docling API Placeholder", "version": "0.1.0"}), 200

@app.route('/extract', methods=['POST'])
def extract_document():
    """Endpoint pour l'extraction de documents."""
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file:
        # Ici, tu traiterais le fichier PDF avec Docling.
        # Pour l'instant, on simule une extraction réussie.
        print(f"Received file: {file.filename}")
        
        # Simule un traitement et retourne des données structurées fictives
        mock_data = {
            "CMDRefEnedis": "SIMULATED_REF_12345",
            "CMDDateCommande": "2025-01-20",
            "TotalHT": "15000.00",
            "line_items": [
                {
                    "CMDCodetPosition": "1",
                    "CMDCodet": "7395078",
                    "CMDCodetNom": "Tableau monobloc extensible",
                    "CMDCodetQuantity": "1",
                    "CMDCodetUnitPrice": "10000.00",
                    "CMDCodetTotlaLinePrice": "10000.00"
                },
                {
                    "CMDCodetPosition": "2",
                    "CMDCodet": "6424704",
                    "CMDCodetNom": "TR 400 C 20 KV PR S27",
                    "CMDCodetQuantity": "1",
                    "CMDCodetUnitPrice": "5000.00",
                    "CMDCodetTotlaLinePrice": "5000.00"
                }
            ],
            "confidence_score": 0.85, # Score de confiance simulé
            "extracted_from": file.filename
        }
        return jsonify(mock_data), 200

if __name__ == '__main__':
    # Flask prend en compte FLASK_RUN_HOST défini dans docker-compose.yml
    # Ou par défaut il écoute sur 127.0.0.1. On s'assure qu'il écoute sur toutes les interfaces.
    app.run(host='0.0.0.0', port=5000)