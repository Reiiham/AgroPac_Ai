# 🌾 AgroPac_Ai HdF
 
> Application web de recommandation de cultures agricoles pour les Hauts-de-France, basée sur le Machine Learning et des données officielles françaises.
 
---
 
## 📌 Description GitHub
 
**AgroPac_Ai** — Système d'aide à la décision agricole pour les Hauts-de-France. Prédit la culture optimale parmi 6 grandes cultures (blé tendre, colza, betterave, orge, maïs, pomme de terre) à partir de données pédologiques, climatiques et économiques réelles. Génère une simulation de déclaration PAC téléchargeable en PDF. Stack : Flask · XGBoost · SQLite · ReportLab.
 
---
 
## 🗂 Stack technique
 
| Composant | Technologie |
|---|---|
| Backend | Flask 3.0 + SQLAlchemy |
| Machine Learning | XGBoost · Random Forest · LightGBM |
| Base de données | SQLite (PostgreSQL en production) |
| Authentification | Flask-Login · Flask-Bcrypt · itsdangerous |
| Email | Flask-Mail · Gmail SMTP |
| PDF | ReportLab |
| Sécurité | Flask-WTF (CSRF) · Flask-Limiter · Headers HTTP |
 
---
 
## 📊 Données officielles utilisées
 
| Source | Contenu | Statut |
|---|---|---|
| RPG IGN 2024 | 294 815 parcelles HdF, cultures déclarées | ✅ Réel |
| RPG IGN 2023 | Précédent cultural — 66.5% des parcelles | ✅ Réel |
| SGDBE INRAE | Type de sol réel par parcelle (jointure KDTree) | ✅ Réel |
| Open-Meteo 2023 | Météo réelle — 9 points de grille HdF | ✅ Réel |
| PAC data.gouv.fr 2022 | DPB 118€/ha — onglet Hypothèses | ✅ Sourcé |
| Agreste SAA 2023-2024 | Rendements nationaux × coeff régional HdF | ✅ Sourcé |
 
---
 
## 🤖 Performances du modèle
 
| Étape | Accuracy | Cultures |
|---|---|---|
| Baseline 8 cultures (sans leakage) | 52.2% | 8 |
| Suppression pois + lin (F1 < 0.15) | 55.0% | 6 |
| + Zone géographique GPS | 56.3% | 6 |
| + Météo réelle Open-Meteo 2023 | **57.5%** | 6 |
 
**Meilleur modèle : XGBoost — 57.5% accuracy — 3.4× mieux que le hasard (16.7%)**
 
### F1-score par culture (XGBoost)
 
| Culture | F1 |
|---|---|
| Blé tendre | 0.813 |
| Pomme de terre | 0.473 |
| Maïs grain | 0.461 |
| Colza | 0.367 |
| Orge | 0.360 |
| Betterave | 0.363 |
 
---
 
## 🔒 Sécurité implémentée
 
- **Mots de passe** : hachage bcrypt — jamais stockés en clair
- **Sessions** : signées avec SECRET_KEY, HttpOnly, SameSite=Lax
- **CSRF** : Flask-WTF sur tous les formulaires
- **Tokens email** : itsdangerous — expiration 1h (confirmation) / 30min (reset)
- **Rate limiting** : 10/min login · 5/h reset · 30/h prédictions
- **Headers HTTP** : X-Frame-Options · X-Content-Type-Options · CSP · Referrer-Policy
- **Validation** : mot de passe 8 chars min + majuscule + chiffre
 
---
 
## 🚀 Installation locale
 
```bash
# 1. Cloner le repo
git clone https://github.com/ton-username/AgroPac_Ai.git
cd AgroPac_Ai
 
# 2. Créer l'environnement virtuel
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
 
# 3. Installer les dépendances
pip install -r requirements.txt
 
# 4. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec vos valeurs
 
# 5. Copier les modèles ML dans models/
# (classifier.joblib, regressor.joblib, etc.)
 
# 6. Lancer
venv\Scripts\python.exe app.py
# → http://localhost:5000
```
 
---
 
## ⚙️ Configuration `.env`
 
```env
SECRET_KEY=générer-avec-python-secrets-token-hex-32
MAIL_USERNAME=votre@gmail.com
MAIL_PASSWORD=votre-app-password-gmail-16-chars
FLASK_ENV=development
```
 
Générer la SECRET_KEY :
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
 
Pour `MAIL_PASSWORD` : compte Google → Sécurité → Validation 2 étapes → Mots de passe des applications.
 
---
 
## 📁 Structure du projet
 
```
agro_v2/
├── app.py                  ← Backend Flask + API REST
├── config.py               ← Configuration (lit depuis .env)
├── requirements.txt
├── .env.example            ← Template variables d'environnement
├── .gitignore
│
├── models/                 ← Fichiers ML (non versionnés)
│   ├── classifier.joblib
│   ├── regressor.joblib
│   ├── label_encoder.joblib
│   ├── ordinal_encoder.joblib
│   ├── feature_config.joblib
│   ├── metrics.json
│   ├── pac_aides.json
│   └── rendements_hdf.json
│
├── database/               ← Créé automatiquement
│   └── users.db
│
└── templates/
    ├── base.html
    ├── index.html
    ├── prediction.html
    ├── dashboard.html
    ├── cultures.html
    ├── historique.html
    ├── profil.html
    └── auth/
        ├── login.html
        ├── register.html
        ├── reset_request.html
        └── reset_password.html
```
 
---
 
## 🌐 Routes principales
 
| Route | Description |
|---|---|
| `GET /` | Accueil — dernières prédictions |
| `GET /prediction` | Formulaire de prédiction ML |
| `GET /dashboard` | Dashboard PAC + métriques modèle |
| `GET /cultures` | Fiches cultures HdF |
| `GET /historique` | Historique des prédictions |
| `GET /profil` | Profil utilisateur + changement mot de passe |
| `POST /api/predict` | API prédiction ML (JSON) |
| `GET /api/pdf/<id>` | Génération PDF simulation Telepac |
| `GET /api/metrics` | Métriques des modèles |
 
---
 
## 📄 PDF — Simulation Telepac
 
Chaque prédiction génère un PDF téléchargeable contenant :
- Informations de l'exploitant
- Code Telepac de la culture recommandée (BTH, CZH, MIS...)
- Caractéristiques de la parcelle
- Détail des aides PAC 2024 avec sources officielles
- Estimation du revenu net
 
> ⚠️ Document pédagogique — ne remplace pas une déclaration officielle sur telepac.agriculture.gouv.fr
 
---
 
## 🚢 Déploiement Railway
 
```bash
# Procfile
web: gunicorn app:app --bind 0.0.0.0:$PORT
```
 
Variables à configurer sur Railway :
```
SECRET_KEY      → clé générée
MAIL_USERNAME   → gmail expéditeur
MAIL_PASSWORD   → app password gmail
FLASK_ENV       → production
DATABASE_URL    → injecté automatiquement par Railway PostgreSQL
```
 
---
 
## 📚 Sources PAC 2024
 
| Aide | Montant | Source |
|---|---|---|
| DPB | 118 €/ha | data.gouv.fr — Aides PAC 2022, onglet Hypothèses |
| Éco-régime supérieur | 62 €/ha | Arrêté JO 01/10/2024 |
| Éco-régime de base (pdt) | 45 €/ha | Arrêté JO 01/10/2024 |
| VBC pomme de terre | 130 €/ha | Telepac — Notice aides découplées PAC 2024 |
 
---
 
## 👥 Auteurs
 
Projet académique 