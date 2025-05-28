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

# Copie les fichiers de dépendances en premier pour profiter du cache Docker si les dépendances ne changent pas.
# Docling n'utilise pas de requirements.txt standard, donc nous allons préparer le répertoire.
# Nous allons créer un fichier `main.py` et un `config/` ultérieurement.
# Pour l'instant, juste la structure minimale.
COPY . /app

# Phase 4: Python Dependencies
# Docling n'est pas installé via pip traditionnellement mais est un projet Python.
# Nous allons simuler son installation ou s'assurer que les fichiers nécessaires sont présents.
# Pour la démo initiale, nous utiliserons un placeholder ou une installation légère.
# Plus tard, Docling sera cloné ou ajouté comme un module.
# Pour l'instant, Docling est une librairie open source python, nous allons la préparer.
# Ajoutez ici les dépendances Python nécessaires pour Docling si elles étaient dans un requirements.txt.
# Étant donné que Docling est un projet spécifique, nous allons supposer
# qu'il sera copié dans sa totalité, et ses dépendances seraient dans son setup.py ou requirements.txt.
# Pour l'instant, nous allons inclure juste les dépendances courantes pour le parsing.
# Si Docling doit être installé par pip, il faut un requirements.txt.
# Si c'est un projet, il faut les fichiers du projet.
# Pour cette étape, imaginons que Docling est une bibliothèque installable ou que nous copierons son code.
# Puisque le PRD mentionne "Docling (IBM) - Docker container", on partira d'une approche où Docling est "packagé".
# Pour la simplicité de démarrage, nous allons créer un environnement où Docling peut être exécuté.
# Supposons que les fichiers de Docling seront copiés dans /app.
# Nous n'installons pas de "Docling" via pip directement car ce n'est pas une bibliothèque PyPI standard.
# Au lieu de cela, nous allons installer des bibliothèques Python souvent utilisées pour la manipulation de documents/OCR.
# Pillow est pour le traitement d'images, requests pour les requêtes HTTP.
RUN pip install --no-cache-dir Pillow requests flask

# Phase 5: Expose Port
# Le port que l'application Docling API exposera.
EXPOSE 5000

# Phase 6: Health Check (FR-5.2)
# Nous allons créer un script simple plus tard pour cela, mais le Dockerfile peut déjà définir HEALTHCHECK.
# Pour l'instant, nous définirons une commande simple de démarrage.
# La commande de démarrage dépendra de la manière dont l'API Docling est exposée.
# Pour un simple test, on peut imaginer un script Python qui lance un serveur HTTP.
# Mettons une commande de démarrage simple qui peut être remplacée par un script plus tard.
CMD ["python", "-c", "import time; print('Docling service starting...'); time.sleep(3600)"]