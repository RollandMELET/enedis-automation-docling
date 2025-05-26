# enedis-automation-docling

Ce dépôt contient la configuration et le code nécessaires au déploiement du moteur d'extraction de documents **Docling (IBM)** via Docker. Il est la pièce maîtresse de la reconnaissance optique de caractères (OCR) pour les commandes ENEDIS, permettant l'extraction de données structurées à partir des fichiers PDF.

Ce service expose une API HTTP pour recevoir des documents PDF et retourner les données extraites au format JSON.

## Contexte du Projet

Ce dépôt fait partie du projet global d'automatisation du traitement des commandes ENEDIS, visant à réduire la saisie manuelle et à améliorer la précision des données intégrées dans Google Sheets. L'orchestration principale est gérée par des workflows n8n.

## Contenu

-   `Dockerfile`: Définit l'image Docker pour Docling et ses dépendances.
-   `docker-compose.yml`: Fichier de composition Docker pour le développement local et le déploiement facilité.
-   `config/`: Contient les fichiers de configuration spécifiques à Docling, incluant les règles d'extraction (`extraction-rules.json`) adaptées aux formats de commandes ENEDIS.
-   `scripts/`: Scripts utilitaires pour les tests et le déploiement.
-   `tests/`: Échantillons de PDF (anonymisés) et cas de test pour valider l'extraction.

## Démarrage Rapide (Développement Local)

1.  Assurez-vous d'avoir Docker et Docker Compose installés.
2.  Clonez ce dépôt: `git clone https://github.com/RollandMELET/enedis-automation-docling.git`
3.  Accédez au répertoire: `cd enedis-automation-docling`
4.  Démarrez le service Docling: `docker-compose up -d`
5.  Testez l'extraction avec `python scripts/extract-test.py <chemin_vers_votre_pdf>`.

## Déploiement

Ce service est conçu pour être déployé sur un VPS via **Coolify**, qui automatise la construction et le déploiement de l'image Docker depuis ce dépôt GitHub.

## Liens Utiles

-   [enedis-automation-workflows](https://github.com/RollandMELET/enedis-automation-workflows) - Workflows n8n qui interagissent avec cette API Docling.
-   [enedis-automation-docs](https://github.com/RollandMELET/enedis-automation-docs) - Documentation générale du projet.
-   [Product Requirements Document (PRD)](https://github.com/RollandMELET/enedis-automation-docs/blob/main/ParsingCommandeEnedis-prd.md) - Description complète du projet.

---
