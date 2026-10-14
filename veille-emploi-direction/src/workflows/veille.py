"""Veille quotidienne d'offres de direction - Lyon & Annecy (<= 50 km).

Workflow Mistral automatisé :
1. Scanne les job boards via le connecteur web_search.
2. Fait sélectionner, dédoublonner et synthétiser les offres par un modèle Mistral.
3. Dépose un brouillon récapitulatif dans la boîte Outlook de Nelson.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import mistralai.workflows as workflows
from mistralai import Mistral
from pydantic import BaseModel

RECIPIENT = "nelson.lambert@outlook.com"
SEARCH_CONNECTOR = "web_search"
OUTLOOK_CONNECTOR = "outlook"
SYNTH_MODEL = "mistral-medium-latest"

CRITERIA = """
CIBLE : Nelson, ~12 ans d'expérience en postes de direction (niveau C-1), parcours ESN,
reconversion hors ESN.
GEOGRAPHIE : Lyon et périphérie <= 50 km ; Annecy et périphérie <= 50 km. Hybride/télétravail
partiel accepté UNIQUEMENT si présence régionale sur site. Tout le reste est hors périmètre.
POSTES : Directeur/Responsable Commercial, Directeur d'activité, Directeur de BU,
Directeur Général, Directeur de filiale, Directeur des opérations et équivalents
(Country Manager, Head of Business, Business Unit Manager...).
ASSOUPLISSEMENT ANNECY uniquement (bassin moins dense) : aussi responsable d'activité,
responsable commercial sénior, directeur d'agence avec équipe >= 5-10 personnes, head of...,
à partir de ~7-8 ans d'expérience. Marquer ces offres « filet élargi ».
EXPERIENCE : offres exigeant >= 10 ans d'expérience (noyau) ; Annecy élargi >= 7-8 ans.
ENTREPRISE : toute taille, tout secteur, y compris ESN côté client uniquement.
EXCLUSIONS explicites : offres trop junior, hors périmètre géographique, freelance/indépendant,
franchise à apport, intérim management indépendant.
FENETRE : uniquement les offres publiées ou encore actives dans les 7 derniers jours ;
dédoublonner les annonces identiques entre plateformes (garder la meilleure URL directe).
"""


def _queries() -> list[str]:
    return [
        '"directeur commercial" OR "directeur des ventes" Lyon offre emploi CDI',
        '"directeur des opérations" OR "directeur opérationnel" Lyon offre emploi CDI',
        '"directeur d\'activité" OR "directeur de BU" OR "business unit manager" Lyon offre emploi',
        '"directeur général" OR "directeur de filiale" Lyon offre emploi CDI',
        '"directeur commercial" OR "responsable commercial" OR "directeur des opérations" Annecy offre emploi',
        '"directeur d\'agence" OR "head of" OR "responsable d\'activité" Annecy Haute-Savoie offre emploi CDI',
        'site:uptoo.fr "directeur commercial" OR "directeur de business unit" Lyon OR Annecy',
        'site:apec.fr OR site:cadremploi.fr "directeur commercial" OR "directeur des opérations" Lyon OR Annecy',
        'site:fr.indeed.com OR site:hellowork.com OR site:regionsjob.com "directeur commercial" OR "directeur des opérations" Lyon OR Annecy',
    ]


async def _call_tool(client: Mistral, connector: str, tool: str, arguments: dict[str, Any]) -> str:
    result = await client.beta.connectors.call_tool_async(
        connector_id_or_name=connector,
        tool_name=tool,
        arguments=arguments,
    )
    texts = []
    for item in result.content or []:
        text = getattr(item, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts)


class VeilleInput(BaseModel):
    recipient: str = RECIPIENT
    days_window: int = 7


@workflows.activity()
async def scan_job_boards(days_window: int) -> str:
    client = Mistral()
    start_date = (date.today() - timedelta(days=days_window)).isoformat()
    chunks: list[str] = []
    for query in _queries():
        raw = await _call_tool(
            client,
            SEARCH_CONNECTOR,
            "web_search",
            {"query": query, "start_date": start_date, "limit": 15},
        )
        chunks.append(f"### REQUETE: {query}\n{raw}")
    return "\n\n".join(chunks)


@workflows.activity()
async def select_and_synthesize(raw_results: str) -> dict[str, Any]:
    client = Mistral()
    today = date.today().isoformat()
    system = (
        "Tu es un chasseur de têtes personnel rigoureux. Tu sélectionnes exclusivement les offres "
        "correspondant aux critères, tu dédoublonnes entre plateformes, et tu écartes explicitement "
        "les offres junior, hors périmètre géographique ou freelance. Réponds UNIQUEMENT en JSON valide."
    )
    user = f"""
DATE DU JOUR : {today}
CRITERES DE SELECTION :
{CRITERIA}

RESULTATS DE RECHERCHE BRUTS :
{raw_results}

Produis un JSON avec ce schéma exact :
{{
  "offres": [
    {{
      "titre": "",
      "entreprise": "",
      "localisation": "",
      "remuneration": "indiquée dans l'annonce, sinon 'non indiquée'",
      "contrat": "CDI/CDD...",
      "date_publication": "",
      "url": "URL DIRECTE de l'annonce (pas une page d'accueil ni une redirection interne)",
      "adequation": "une ligne de synthèse d'adéquation avec le profil (12 ans de direction, parcours ESN, reconversion hors ESN)",
      "filet_elargi": false
    }}
  ],
  "exclues": [
    {{"titre": "", "entreprise": "", "raison": "trop junior / hors périmètre géographique / freelance / hors fenêtre 7 jours"}}
  ],
  "top3": [
    {{"titre": "", "argumentaire": "une phrase d'argumentaire de candidature"}}
  ]
}}

Règles : ne garde que les offres publiées ou actives dans les 7 derniers jours ; vérifie que
l'URL est directe vers l'annonce ; si aucune offre ne matche, retourne des listes vides.
"""
    response = await client.chat.complete_async(
        model=SYNTH_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


@workflows.activity()
async def create_outlook_recap(synthesis: dict[str, Any], recipient: str) -> str:
    client = Mistral()
    today = date.today().strftime("%d/%m/%Y")
    subject = f"Veille offres direction — Lyon & Annecy — {today}"

    def esc(value: str) -> str:
        return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    rows = []
    for offre in synthesis.get("offres", []):
        rows.append(
            "<tr>"
            f"<td>{esc(str(offre.get('titre', '')))}{' (filet élargi)' if offre.get('filet_elargi') else ''}</td>"
            f"<td>{esc(str(offre.get('entreprise', '')))}</td>"
            f"<td>{esc(str(offre.get('localisation', '')))}</td>"
            f"<td>{esc(str(offre.get('remuneration', '')))}</td>"
            f"<td>{esc(str(offre.get('contrat', '')))}</td>"
            f"<td>{esc(str(offre.get('date_publication', '')))}</td>"
            f"<td><a href=\"{esc(str(offre.get('url', '')))}\">Voir l'annonce</a></td>"
            f"<td>{esc(str(offre.get('adequation', '')))}</td>"
            "</tr>"
        )
    excluded = "".join(
        f"<li>{esc(str(e.get('titre', '')))} — {esc(str(e.get('entreprise', '')))} : {esc(str(e.get('raison', '')))}</li>"
        for e in synthesis.get("exclues", [])
    )
    top3 = "".join(
        f"<li><b>{esc(str(t.get('titre', '')))}</b> : {esc(str(t.get('argumentaire', '')))}</li>"
        for t in synthesis.get("top3", [])
    )

    body = (
        '<div style="font-family:Arial,sans-serif;font-size:14px;color:#222">'
        '<p>Bonjour Nelson,</p>'
        '<p>Veille quotidienne automatique des offres de direction (Lyon &amp; Annecy, &le; 50 km), '
        'publiées ou actives sur les 7 derniers jours, dédoublonnées.</p>'
        '<h3 style="color:#1a5fb4">Offres présélectionnées</h3>'
        '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px">'
        '<tr style="background:#e8eefc"><th>Poste</th><th>Entreprise</th><th>Localisation</th>'
        '<th>Rémunération</th><th>Contrat</th><th>Publication</th><th>Lien</th><th>Adéquation</th></tr>'
        + ("".join(rows) if rows else '<tr><td colspan="8">Aucune nouvelle offre correspondant aux critères aujourd\'hui.</td></tr>')
        + '</table>'
        '<h3 style="color:#1a5fb4">Top 3 et argumentaires</h3><ol>'
        + (top3 or "<li>Aucun top 3 aujourd'hui.</li>")
        + '</ol>'
        '<h3 style="color:#1a5fb4">Offres écartées</h3><ul>'
        + (excluded or "<li>Aucune à signaler.</li>")
        + '</ul>'
        '<p>Repère salarial Directeur Commercial Lyon : 85 595 – 140 980 € (grille Robert Half).</p>'
        '<p>— Veille automatique Vibe</p></div>'
    )

    await _call_tool(
        client,
        OUTLOOK_CONNECTOR,
        "draft_outlook_email",
        {
            "message_subject": subject,
            "message_to": recipient,
            "message_body": body,
        },
    )
    return f"Brouillon Outlook créé : {subject} ({len(synthesis.get('offres', []))} offres retenues)"


@workflows.workflow.define(
    name="veille-emploi-direction",
    workflow_display_name="Veille Emploi Direction (Lyon/Annecy)",
    workflow_description=(
        "Veille quotidienne des offres de direction à Lyon et Annecy (<= 50 km, >= 10 ans "
        "d'expérience, filet élargi Annecy), dédoublonnée sur 7 jours, avec récap Outlook."
    ),
)
class VeilleWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, input: VeilleInput) -> str:
        raw = await scan_job_boards(input.days_window)
        synthesis = await select_and_synthesize(raw)
        return await create_outlook_recap(synthesis, input.recipient)
