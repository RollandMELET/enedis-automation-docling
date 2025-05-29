# Phase 1: Base Image
# Utilise une image Python légère basée sur Debian Buster pour un environnement stable et de petite taille.
FROM python:3.9-slim-buster

# Phase 2: System Dependencies
# Installe les outils nécessaires pour le traitement d'images et OCR (Tesseract).
# libgl1-mesa-glx est souvent nécessaire pour les bibliothèques d'imagerie Python comme OpenCV (utilisée par Docling pour le traitement PDF).
# tesseract-ocr et tesseract-ocr-fra sont les moteurs Tesseract et le pack de langue française.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    tesseract-ocr \
    tesseract-ocr-fra \
    # Nettoyage pour réduire la taille de l'image
    && rm -rf /var/lib/apt/lists/*

# Phase 3: Application Setup
# Définit le répertoire de travail dans le conteneur.
WORKDIR /app

# Copie tous les fichiers du répertoire courant de ton projet local vers le répertoire /app dans le conteneur.
# Cela inclura ton dossier 'scripts' avec 'start_api.py'.
COPY . /app

# Phase 4: Python Dependencies
# Installe les bibliothèques Python nécessaires pour notre API Flask, l'OCR et la lecture de PDF.
RUN pip install --no-cache-dir Pillow requests flask pytesseract pdfminer.six

# Phase 5: Expose Port
# Le port que l'application Docling API exposera.
EXPOSE 5000

# Phase 6: Démarrage de l'API Flask (FR-5.2)
# Cette commande lance notre script start_api.py qui exécute l'application Flask.
CMD ["python", "/app/scripts/start_api.py"]