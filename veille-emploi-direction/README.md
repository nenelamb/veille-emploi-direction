# Veille Emploi Direction (Lyon/Annecy)

Workflow Mistral exécuté chaque jour à 08h00 (Europe/Paris).

1. Scan des job boards via le connecteur web_search (Indeed, HelloWork, RegionsJob, APEC, Cadremploi, Uptoo, LinkedIn Jobs, Welcome to the Jungle...).
2. Sélection et dédoublonnage par un modèle Mistral selon les critères de Nelson : postes de direction, >= 10 ans d'expérience, Lyon/Annecy <= 50 km, 7 derniers jours, filet élargi Annecy (7-8 ans, marqué comme tel). Exclusions : junior, hors périmètre, freelance.
3. Dépôt d'un brouillon récapitulatif Outlook (tableau + top 3 + argumentaires + offres écartées).

## Structure
- worker.py — point d'entrée du worker
- src/workflows/veille.py — définition du workflow veille-emploi-direction
- Dockerfile — image du déploiement managé

## Connecteurs requis
- web_search
- outlook (on-behalf-of, déploiement durci)

## Déclenchement manuel
{"recipient": "nelson.lambert@outlook.com", "days_window": 7}
