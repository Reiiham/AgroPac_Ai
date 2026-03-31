import os, json, joblib, io, time
from datetime import datetime, date
from functools import wraps

from flask import (Flask, render_template, request, jsonify, redirect,
                   url_for, flash, session, send_file, abort)
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from flask_mail import Mail, Message
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import numpy as np
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from dotenv import load_dotenv
load_dotenv()  

from config import Config

# ── Init app ──────────────────────────────────────────────────
app = Flask(__name__)
app.config.from_object(Config)

db      = SQLAlchemy(app)
bcrypt  = Bcrypt(app)
mail    = Mail(app)
csrf    = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Connectez-vous pour accéder à cette page.'
login_manager.login_message_category = 'warning'

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=['200 per day', '50 per hour'],
    storage_uri='memory://',
)

s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# ── Headers sécurité ──────────────────────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers['X-Frame-Options']        = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection']       = '1; mode=block'
    response.headers['Referrer-Policy']        = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:;"
    )
    return response

# ══════════════════════════════════════════════════════════════
# MODÈLE UTILISATEUR
# ══════════════════════════════════════════════════════════════
class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    nom           = db.Column(db.String(100), nullable=False)
    prenom        = db.Column(db.String(100), nullable=False)
    email         = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    confirmed     = db.Column(db.Boolean, default=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_login    = db.Column(db.DateTime)
    predictions   = db.relationship('Prediction', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def get_confirm_token(self):
        return s.dumps(self.email, salt='email-confirm')

    def get_reset_token(self):
        return s.dumps(self.email, salt='password-reset')

    @staticmethod
    def verify_token(token, salt, max_age):
        try:
            email = s.loads(token, salt=salt, max_age=max_age)
        except (SignatureExpired, BadSignature):
            return None
        return User.query.filter_by(email=email).first()


class Prediction(db.Model):
    __tablename__   = 'predictions'
    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    culture_top1    = db.Column(db.String(50))
    score_top1      = db.Column(db.Float)
    revenu_estime   = db.Column(db.Float)
    sol_type        = db.Column(db.String(50))
    zone_geo        = db.Column(db.String(50))
    surf_parc       = db.Column(db.Float)
    inputs_json     = db.Column(db.Text)   # stockage JSON des inputs

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ══════════════════════════════════════════════════════════════
# FORMULAIRES
# ══════════════════════════════════════════════════════════════
class RegisterForm(FlaskForm):
    prenom   = StringField('Prénom',  validators=[DataRequired(), Length(2, 50)])
    nom      = StringField('Nom',     validators=[DataRequired(), Length(2, 50)])
    email    = StringField('Email',   validators=[DataRequired(), Email()])
    password = PasswordField('Mot de passe', validators=[
        DataRequired(),
        Length(min=8, message='Au moins 8 caractères requis'),
    ])
    confirm  = PasswordField('Confirmer', validators=[
        DataRequired(), EqualTo('password', message='Les mots de passe ne correspondent pas')
    ])
    submit   = SubmitField("S'inscrire")

    def validate_email(self, field):
        if User.query.filter_by(email=field.data.lower()).first():
            raise ValidationError('Cet email est déjà utilisé.')

    def validate_password(self, field):
        pwd = field.data
        if not any(c.isupper() for c in pwd):
            raise ValidationError('Le mot de passe doit contenir au moins une majuscule.')
        if not any(c.isdigit() for c in pwd):
            raise ValidationError('Le mot de passe doit contenir au moins un chiffre.')


class LoginForm(FlaskForm):
    email    = StringField('Email',          validators=[DataRequired(), Email()])
    password = PasswordField('Mot de passe', validators=[DataRequired()])
    remember = BooleanField('Se souvenir de moi')
    submit   = SubmitField('Se connecter')


class ResetRequestForm(FlaskForm):
    email  = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Envoyer le lien')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('Nouveau mot de passe', validators=[
        DataRequired(), Length(min=8)
    ])
    confirm  = PasswordField('Confirmer', validators=[
        DataRequired(), EqualTo('password')
    ])
    submit   = SubmitField('Réinitialiser')

    def validate_password(self, field):
        pwd = field.data
        if not any(c.isupper() for c in pwd):
            raise ValidationError('Le mot de passe doit contenir au moins une majuscule.')
        if not any(c.isdigit() for c in pwd):
            raise ValidationError('Le mot de passe doit contenir au moins un chiffre.')


# ══════════════════════════════════════════════════════════════
# CHARGEMENT DES MODÈLES ML
# ══════════════════════════════════════════════════════════════
models_ok = False
clf = reg = le = oe = feat_cfg = pac_aides = rendements = None

try:
    clf       = joblib.load('models/classifier.joblib')
    reg       = joblib.load('models/regressor.joblib')
    le        = joblib.load('models/label_encoder.joblib')
    oe        = joblib.load('models/ordinal_encoder.joblib')
    feat_cfg  = joblib.load('models/feature_config.joblib')
    with open('models/pac_aides.json')     as f: pac_aides  = json.load(f)
    with open('models/rendements_hdf.json') as f: rendements = json.load(f)
    with open('models/metrics.json')        as f: metrics    = json.load(f)
    models_ok = True
    print('✓ Modèles chargés')
except Exception as e:
    print(f'⚠ Modèles non chargés : {e}')
    metrics = {}

# ── Référentiels PAC et cultures ──────────────────────────────
PAC_AIDES = {
    'ble_tendre':     {'dpb':118,'eco':62,'vbc':0  },
    'colza':          {'dpb':118,'eco':62,'vbc':0  },
    'betterave':      {'dpb':118,'eco':62,'vbc':0  },
    'orge':           {'dpb':118,'eco':62,'vbc':0  },
    'mais_grain':     {'dpb':118,'eco':62,'vbc':0  },
    'pomme_de_terre': {'dpb':118,'eco':45,'vbc':130},
}
NOMS_CULTURES = {
    'ble_tendre':'Blé tendre','colza':'Colza','betterave':'Betterave sucrière',
    'orge':'Orge','mais_grain':'Maïs grain','pomme_de_terre':'Pomme de terre',
}
CODES_TELEPAC = {
    'ble_tendre':'BTH','colza':'CZH','betterave':'BTN',
    'orge':'ORH','mais_grain':'MIS','pomme_de_terre':'PTC',
}
SOL_IDX = {s:i for i,s in enumerate(
    ['limoneux','argilo_limoneux','sablo_limoneux','craie','tourbe','argileux_lourd'])}
SOL_COMPAT = {
    'ble_tendre':[10,8,5,6,4,6],'colza':[9,7,4,5,3,5],
    'betterave':[10,9,6,4,5,5],'pomme_de_terre':[9,6,9,4,7,3],
    'orge':[8,7,7,7,5,5],'mais_grain':[7,6,6,5,6,4],'lin_fibre':[10, 7, 5, 5, 4, 4], 
    'pois_proteine':[8, 7, 5, 6, 4, 5],   
}
PLUIE_MIN = {
    'ble_tendre':550,'colza':600,'betterave':600,'pomme_de_terre':550,
    'orge':480,'mais_grain':650,'lin_fibre':600,
    'pois_proteine':  500,  
}

def enrich_input(d):
    df = pd.DataFrame([d])
    si = df['sol_type'].map(lambda s: SOL_IDX.get(s, 0))
    for cult, scores in SOL_COMPAT.items():
        df[f'sol_score_{cult}'] = si.map(lambda i, s=scores: s[i]/10)
    for cult, pmin in PLUIE_MIN.items():
        df[f'pluie_ok_{cult}'] = (df['pluie_mm'] >= pmin).astype(float)
    df['pac_dpb_fixe']          = 118
    df['pac_eco_base']          = 45
    df['pac_eco_superieur']     = 62
    df['pac_vbc_pdt_possible']  = (df['budget_intrants_ha'] >= 900).astype(int)
    df['pac_vbc_pois_possible'] = (df['budget_intrants_ha'] >= 250).astype(int)
    df['pac_max_atteignable']   = (118 + 62
        + df['pac_vbc_pdt_possible']*130
        + df['pac_vbc_pois_possible']*(1-df['pac_vbc_pdt_possible'])*104)
    df['pac_attractivite']      = ((118+62)/df['budget_intrants_ha'].clip(lower=1)).round(4)
    df['prec_legumineuse'] = df['precedent_cultural'].isin(['pois_proteine','feveroles']).astype(int)
    df['prec_oleagineux']  = df['precedent_cultural'].isin(['colza','lin_fibre']).astype(int)
    df['prec_cereale']     = df['precedent_cultural'].isin(['ble_tendre','orge','mais_grain']).astype(int)
    df['prec_betterave']   = (df['precedent_cultural']=='betterave').astype(int)
    df['prec_pomme']       = (df['precedent_cultural']=='pomme_de_terre').astype(int)
    df['argile_norm']      = df['argile_pct_sol'] / 55.0
    df['ph_optimal']       = df['ph_sol_reel'].between(6.5, 7.2).astype(int)
    df['mo_haute']         = (df['mo_sol_reel'] > 3.0).astype(int)
    df['budget_serre']     = (df['budget_intrants_ha'] < 450).astype(int)
    df['budget_ample']     = (df['budget_intrants_ha'] > 800).astype(int)
    df['stress_hydrique']  = (df['pluie_mm'] < 550).astype(int)
    df['surf_relative']    = df['surf_parc'] / 4.8
    return df

# ══════════════════════════════════════════════════════════════
# ROUTES AUTHENTIFICATION
# ══════════════════════════════════════════════════════════════
@app.route('/register', methods=['GET','POST'])
@limiter.limit('10 per hour')
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            prenom=form.prenom.data.strip(),
            nom=form.nom.data.strip(),
            email=form.email.data.lower().strip(),
        )
        user.set_password(form.password.data)
        #user.confirmed = True #désactivé la confirmation email pour faciliter les tests, à réactiver en prod
        db.session.add(user)
        db.session.commit()
        send_confirmation_email(user)
        flash('Compte créé. Vérifiez votre email pour confirmer votre inscription.', 'info')
        return redirect(url_for('login'))
    return render_template('auth/register.html', form=form)


@app.route('/confirm/<token>')
def confirm_email(token):
    user = User.verify_token(token, 'email-confirm',
                             app.config['TOKEN_EXPIRATION_CONFIRM'])
    if not user:
        flash('Lien de confirmation invalide ou expiré.', 'danger')
        return redirect(url_for('login'))
    if user.confirmed:
        flash('Compte déjà confirmé.', 'info')
    else:
        user.confirmed = True
        db.session.commit()
        flash('Email confirmé ! Vous pouvez maintenant vous connecter.', 'success')
    return redirect(url_for('login'))


@app.route('/login', methods=['GET','POST'])
@limiter.limit('10 per minute')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.check_password(form.password.data):
            if not user.confirmed:
                flash('Confirmez votre email avant de vous connecter.', 'warning')
                return redirect(url_for('login'))
            login_user(user, remember=form.remember.data)
            user.last_login = datetime.utcnow()
            db.session.commit()
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash('Email ou mot de passe incorrect.', 'danger')
    return render_template('auth/login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnexion réussie.', 'info')
    return redirect(url_for('login'))


@app.route('/reset-password', methods=['GET','POST'])
@limiter.limit('5 per hour')
def reset_request():
    form = ResetRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.confirmed:
            send_reset_email(user)
        flash('Si cet email existe, un lien de réinitialisation a été envoyé.', 'info')
        return redirect(url_for('login'))
    return render_template('auth/reset_request.html', form=form)


@app.route('/reset-password/<token>', methods=['GET','POST'])
def reset_password(token):
    user = User.verify_token(token, 'password-reset',
                             app.config['TOKEN_EXPIRATION_RESET'])
    if not user:
        flash('Lien invalide ou expiré (30 minutes maximum).', 'danger')
        return redirect(url_for('reset_request'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Mot de passe mis à jour. Connectez-vous.', 'success')
        return redirect(url_for('login'))
    return render_template('auth/reset_password.html', form=form)


# ══════════════════════════════════════════════════════════════
# ROUTES PRINCIPALES
# ══════════════════════════════════════════════════════════════
@app.route('/')
@login_required
def index():
    predictions = Prediction.query.filter_by(user_id=current_user.id)\
                                  .order_by(Prediction.created_at.desc())\
                                  .limit(5).all()
    return render_template('index.html', predictions=predictions, metrics=metrics)


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', pac_aides=PAC_AIDES,
                           noms=NOMS_CULTURES, metrics=metrics)


@app.route('/prediction')
@login_required
def prediction():
    return render_template('prediction.html', metrics=metrics,
                           pac_aides=PAC_AIDES, noms=NOMS_CULTURES)


@app.route('/cultures')
@login_required
def cultures():
    return render_template('cultures.html', pac_aides=PAC_AIDES,
                           noms=NOMS_CULTURES)


@app.route('/historique')
@login_required
def historique():
    preds = Prediction.query.filter_by(user_id=current_user.id)\
                            .order_by(Prediction.created_at.desc()).all()
    return render_template('historique.html', predictions=preds,
                           noms=NOMS_CULTURES)

@app.route('/profil', methods=['GET', 'POST'])
@login_required
def profil():
    # Changement mot de passe
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'change_password':
            ancien = request.form.get('ancien_mdp')
            nouveau = request.form.get('nouveau_mdp')
            confirm = request.form.get('confirm_mdp')

            if not current_user.check_password(ancien):
                flash('Mot de passe actuel incorrect.', 'danger')
            elif len(nouveau) < 8:
                flash('Le nouveau mot de passe doit faire au moins 8 caractères.', 'danger')
            elif not any(c.isupper() for c in nouveau):
                flash('Le nouveau mot de passe doit contenir une majuscule.', 'danger')
            elif not any(c.isdigit() for c in nouveau):
                flash('Le nouveau mot de passe doit contenir un chiffre.', 'danger')
            elif nouveau != confirm:
                flash('Les mots de passe ne correspondent pas.', 'danger')
            else:
                current_user.set_password(nouveau)
                db.session.commit()
                flash('Mot de passe mis à jour avec succès.', 'success')

        elif action == 'change_info':
            prenom = request.form.get('prenom', '').strip()
            nom    = request.form.get('nom', '').strip()
            if len(prenom) < 2 or len(nom) < 2:
                flash('Prénom et nom doivent faire au moins 2 caractères.', 'danger')
            else:
                current_user.prenom = prenom
                current_user.nom    = nom
                db.session.commit()
                flash('Informations mises à jour.', 'success')

    stats = {
        'total':    Prediction.query.filter_by(user_id=current_user.id).count(),
        'derniere': Prediction.query.filter_by(user_id=current_user.id)
                              .order_by(Prediction.created_at.desc()).first(),
    }
    return render_template('profil.html', stats=stats)
#----------TEST----------
@app.route('/test-token')
def test_token():
    """Route de test — à supprimer en production"""
    user = User.query.first()
    if not user:
        return 'Aucun utilisateur en base'
    token_confirm = user.get_confirm_token()
    token_reset   = user.get_reset_token()
    return f'''
    <h2>Test tokens — {user.email}</h2>
    <p><b>Token confirmation (1h) :</b><br>
    <a href="/confirm/{token_confirm}">Cliquer pour confirmer</a></p>
    <p><b>Token reset (30min) :</b><br>
    <a href="/reset-password/{token_reset}">Cliquer pour reset</a></p>
    <p><small>Page de test — supprimer avant déploiement</small></p>
    '''
# ══════════════════════════════════════════════════════════════
# API PRÉDICTION
# ══════════════════════════════════════════════════════════════
@app.route('/api/predict', methods=['POST'])
@login_required
@limiter.limit('30 per hour')
def api_predict():
    if not models_ok:
        return jsonify({'error': 'Modèles non disponibles'}), 503
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Données manquantes'}), 400

    required = ['sol_type','zone_geo','pluie_mm','temp_moy_c','gel_jours',
                'surf_parc','precedent_cultural','budget_intrants_ha',
                'argile_pct_sol','ph_sol_reel','mo_sol_reel']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({'error': f'Champs manquants : {missing}'}), 400

    try:
        df = enrich_input(data)
        FEAT_CAT = feat_cfg['feat_cat']
        FEAT_NUM = feat_cfg['feat_num']
        X = df[FEAT_CAT + FEAT_NUM].copy()
        X[FEAT_CAT] = oe.transform(X[FEAT_CAT])

        probs  = clf.predict_proba(X)[0]
        revenu = float(reg.predict(X)[0])
        ranked = sorted(zip(le.classes_, probs), key=lambda x: -x[1])

        top4 = [{'culture':c, 'nom':NOMS_CULTURES.get(c,c),
                 'score_pct':round(p*100,1)} for c,p in ranked[:4]]
        top1 = ranked[0][0]
        pac  = PAC_AIDES.get(top1, {})

        # Sauvegarder en base
        pred = Prediction(
            user_id=current_user.id,
            culture_top1=top1,
            score_top1=round(ranked[0][1]*100,1),
            revenu_estime=round(revenu),
            sol_type=data.get('sol_type'),
            zone_geo=data.get('zone_geo'),
            surf_parc=data.get('surf_parc'),
            inputs_json=json.dumps(data),
        )
        db.session.add(pred)
        db.session.commit()

        return jsonify({
            'top4':         top4,
            'revenu_ha':    round(revenu),
            'pac_detail':   pac,
            'pac_total':    sum(pac.values()),
            'code_telepac': CODES_TELEPAC.get(top1,''),
            'prediction_id':pred.id,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/metrics')
@login_required
def api_metrics():
    return jsonify(metrics)


# ══════════════════════════════════════════════════════════════
# GÉNÉRATION PDF — SIMULATION DÉCLARATION TELEPAC
# ══════════════════════════════════════════════════════════════
@app.route('/api/pdf/<int:pred_id>')
@login_required
def generate_pdf(pred_id):
    pred = Prediction.query.get_or_404(pred_id)
    if pred.user_id != current_user.id:
        abort(403)

    inputs = json.loads(pred.inputs_json) if pred.inputs_json else {}
    pac    = PAC_AIDES.get(pred.culture_top1, {})

    buffer = io.BytesIO()
    doc    = SimpleDocTemplate(buffer, pagesize=A4,
                               topMargin=1.5*cm, bottomMargin=1.5*cm,
                               leftMargin=2*cm, rightMargin=2*cm)

    styles = getSampleStyleSheet()
    VERT   = colors.HexColor('#1a5c1a')
    JAUNE  = colors.HexColor('#f5c518')
    GRIS   = colors.HexColor('#f5f5f5')

    style_titre = ParagraphStyle('titre', parent=styles['Heading1'],
        fontSize=16, textColor=VERT, spaceAfter=6, alignment=TA_CENTER)
    style_sous  = ParagraphStyle('sous', parent=styles['Normal'],
        fontSize=10, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=12)
    style_h2    = ParagraphStyle('h2', parent=styles['Heading2'],
        fontSize=12, textColor=VERT, spaceBefore=12, spaceAfter=6)
    style_body  = ParagraphStyle('body', parent=styles['Normal'],
        fontSize=10, spaceAfter=4)
    style_note  = ParagraphStyle('note', parent=styles['Normal'],
        fontSize=8, textColor=colors.grey, spaceAfter=4, leftIndent=10)

    elements = []

    # ── En-tête ──
    elements.append(Paragraph('🌾 AgroPac AI HdF', style_titre))
    elements.append(Paragraph(
        'Simulation de déclaration PAC — Document non officiel',
        style_sous))
    elements.append(HRFlowable(width='100%', thickness=2, color=VERT))
    elements.append(Spacer(1, 0.4*cm))

    # ── Bandeau avertissement ──
    avert = Table([[Paragraph(
        '⚠ Ce document est une <b>simulation pédagogique</b> générée par AgroPac AI HdF. '
        'Il ne remplace pas une déclaration officielle sur Telepac. '
        'Consultez votre DDT ou chambre d\'agriculture pour toute démarche officielle.',
        ParagraphStyle('avert', fontSize=8, textColor=colors.HexColor('#7c4700'))
    )]], colWidths=[17*cm])
    avert.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#fff3cd')),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#f59e0b')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.HexColor('#fff3cd')]),
    ]))
    elements.append(avert)
    elements.append(Spacer(1, 0.5*cm))

    # ── Infos agriculteur ──
    elements.append(Paragraph('1. Informations de l\'exploitant', style_h2))
    infos_agri = [
        ['Nom & Prénom', f'{current_user.prenom} {current_user.nom}'],
        ['Email', current_user.email],
        ['Date de génération', pred.created_at.strftime('%d/%m/%Y à %H:%M')],
        ['Numéro PACAGE', '(non renseigné — simulation)'],
        ['Département', inputs.get('zone_geo','').replace('_',' ').title()],
    ]
    t = Table(infos_agri, colWidths=[5*cm, 12*cm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BACKGROUND', (0,0), (0,-1), GRIS),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('BOX', (0,0), (-1,-1), 0.5, colors.grey),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.lightgrey),
        ('PADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, GRIS]),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.4*cm))

    # ── Déclaration parcelle ──
    elements.append(Paragraph('2. Déclaration de la parcelle (S2 simplifié)', style_h2))
    elements.append(Paragraph(
        'Culture recommandée par le modèle AgroPac AI :', style_body))

    culture_data = [
        ['Code Telepac', 'Libellé culture', 'Surface (ha)', 'Score modèle'],
        [
            CODES_TELEPAC.get(pred.culture_top1, '—'),
            NOMS_CULTURES.get(pred.culture_top1, pred.culture_top1),
            f'{inputs.get("surf_parc", "—")} ha',
            f'{pred.score_top1:.1f}%',
        ]
    ]
    tc = Table(culture_data, colWidths=[3.5*cm, 6*cm, 4*cm, 3.5*cm])
    tc.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), VERT),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOX', (0,0), (-1,-1), 0.5, colors.grey),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.lightgrey),
        ('PADDING', (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#e8f5e9')]),
    ]))
    elements.append(tc)
    elements.append(Spacer(1, 0.4*cm))

    # ── Caractéristiques de la parcelle ──
    elements.append(Paragraph('3. Caractéristiques de la parcelle', style_h2))
    caract = [
        ['Type de sol',        inputs.get('sol_type','—').replace('_',' ')],
        ['Zone géographique',  inputs.get('zone_geo','—').replace('_',' ')],
        ['Précédent cultural', NOMS_CULTURES.get(inputs.get('precedent_cultural',''),'—')],
        ['Surface',            f'{inputs.get("surf_parc","—")} ha'],
        ['Pluviométrie 2023',  f'{inputs.get("pluie_mm","—")} mm'],
        ['Température moy.',   f'{inputs.get("temp_moy_c","—")} °C'],
        ['pH sol',             inputs.get('ph_sol_reel','—')],
        ['Argile',             f'{inputs.get("argile_pct_sol","—")} %'],
        ['Matières organiques',f'{inputs.get("mo_sol_reel","—")} %'],
        ['Budget intrants',    f'{inputs.get("budget_intrants_ha","—")} €/ha'],
    ]
    tp = Table(caract, colWidths=[6*cm, 11*cm])
    tp.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BACKGROUND', (0,0), (0,-1), GRIS),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('BOX', (0,0), (-1,-1), 0.5, colors.grey),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.lightgrey),
        ('PADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, GRIS]),
    ]))
    elements.append(tp)
    elements.append(Spacer(1, 0.4*cm))

    # ── Aides PAC estimées ──
    elements.append(Paragraph('4. Aides PAC 2024 estimées', style_h2))
    pac_data = [
        ['Aide', 'Montant (€/ha)', 'Source'],
        ['DPB — Aide de Base au Revenu', f'{pac.get("dpb",118)} €/ha',
         'data.gouv.fr PAC 2022'],
        ['Éco-régime', f'{pac.get("eco",62)} €/ha',
         'Arrêté JO 01/10/2024'],
        ['VBC — Aide couplée végétale', f'{pac.get("vbc",0)} €/ha',
         'SMAG / Telepac 2024'],
        ['TOTAL PAC estimé', f'{sum(pac.values())} €/ha', '—'],
    ]
    tpac = Table(pac_data, colWidths=[7*cm, 4*cm, 6*cm])
    tpac.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), VERT),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e8f5e9')),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ALIGN', (1,0), (1,-1), 'CENTER'),
        ('BOX', (0,0), (-1,-1), 0.5, colors.grey),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.lightgrey),
        ('PADDING', (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, GRIS]),
    ]))
    elements.append(tpac)
    elements.append(Spacer(1, 0.4*cm))

    # ── Revenu estimé ──
    elements.append(Paragraph('5. Estimation du revenu net', style_h2))
    rev_data = [
        ['Revenu net estimé', f'{pred.revenu_estime:,.0f} €/ha'],
        ['Dont aides PAC', f'{sum(pac.values())} €/ha'],
        ['Surface déclarée', f'{inputs.get("surf_parc","—")} ha'],
        ['Revenu total estimé',
         f'{pred.revenu_estime * inputs.get("surf_parc",1):,.0f} €'],
    ]
    trev = Table(rev_data, colWidths=[8*cm, 9*cm])
    trev.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BACKGROUND', (0,0), (0,-1), GRIS),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e8f5e9')),
        ('BOX', (0,0), (-1,-1), 0.5, colors.grey),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.lightgrey),
        ('PADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,0), (-1,-2), [colors.white, GRIS]),
    ]))
    elements.append(trev)
    elements.append(Spacer(1, 0.6*cm))

    # ── Pied de page ──
    elements.append(HRFlowable(width='100%', thickness=1, color=colors.lightgrey))
    elements.append(Spacer(1, 0.2*cm))
    elements.append(Paragraph(
        f'Document généré par AgroPac AI HdF le {date.today().strftime("%d/%m/%Y")} — '
        'Pour une déclaration officielle, rendez-vous sur telepac.agriculture.gouv.fr',
        ParagraphStyle('footer', fontSize=7, textColor=colors.grey, alignment=TA_CENTER)
    ))

    doc.build(elements)
    buffer.seek(0)
    filename = f'simulation_pac_{pred.culture_top1}_{pred.created_at.strftime("%Y%m%d")}.pdf'
    return send_file(buffer, mimetype='application/pdf',
                     as_attachment=True, download_name=filename)


# ══════════════════════════════════════════════════════════════
# FONCTIONS EMAIL
# ══════════════════════════════════════════════════════════════
def send_confirmation_email(user):
    token = user.get_confirm_token()
    link  = url_for('confirm_email', token=token, _external=True)
    msg   = Message('Confirmez votre inscription — AgroPac AI HdF',
                    recipients=[user.email])
    msg.html = f'''
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:auto">
      <div style="background:#1a5c1a;padding:20px;text-align:center">
        <h1 style="color:white;margin:0">🌾 AgroPac AI HdF</h1>
      </div>
      <div style="padding:30px;background:#f9f9f9">
        <h2>Bonjour {user.prenom},</h2>
        <p>Merci de votre inscription. Cliquez sur le bouton ci-dessous pour confirmer votre email :</p>
        <div style="text-align:center;margin:30px 0">
          <a href="{link}" style="background:#1a5c1a;color:white;padding:14px 28px;
             border-radius:6px;text-decoration:none;font-weight:bold">
            Confirmer mon email
          </a>
        </div>
        <p style="color:#888;font-size:12px">Ce lien expire dans 1 heure.</p>
        <p style="color:#888;font-size:12px">Si vous n'avez pas créé de compte, ignorez cet email.</p>
      </div>
    </div>'''
    mail.send(msg)


def send_reset_email(user):
    token = user.get_reset_token()
    link  = url_for('reset_password', token=token, _external=True)
    msg   = Message('Réinitialisation de mot de passe — AgroPac AI HdF',
                    recipients=[user.email])
    msg.html = f'''
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:auto">
      <div style="background:#1a5c1a;padding:20px;text-align:center">
        <h1 style="color:white;margin:0">🌾 AgroPac AI HdF</h1>
      </div>
      <div style="padding:30px;background:#f9f9f9">
        <h2>Réinitialisation de mot de passe</h2>
        <p>Bonjour {user.prenom}, vous avez demandé à réinitialiser votre mot de passe.</p>
        <div style="text-align:center;margin:30px 0">
          <a href="{link}" style="background:#c0392b;color:white;padding:14px 28px;
             border-radius:6px;text-decoration:none;font-weight:bold">
            Réinitialiser mon mot de passe
          </a>
        </div>
        <p style="color:#888;font-size:12px">⚠ Ce lien expire dans <b>30 minutes</b>.</p>
        <p style="color:#888;font-size:12px">Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.</p>
      </div>
    </div>'''
    mail.send(msg)


# ══════════════════════════════════════════════════════════════
# LANCEMENT
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    with app.app_context():
        os.makedirs('database', exist_ok=True)
        db.create_all()
    print('=' * 55)
    print('  AgroPac AI HdF — Flask v2')
    print('=' * 55)
    print(f'  Modèles    : {"✓" if models_ok else "✗"}')
    print(f'  URL        : http://localhost:5000')
    print('=' * 55)
    app.run(debug=True, host='0.0.0.0', port=5000)
