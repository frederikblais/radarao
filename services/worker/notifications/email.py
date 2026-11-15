"""Courriels (en français, désactivables, sans renseignement sensible : titres d'avis publics,
scores et liens vers RadarAO seulement)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from api.app.config import get_settings

log = logging.getLogger("radarao.email")
FOOTER = (
    "\n\n—\nRadarAO · Données SEAO : Secrétariat du Conseil du trésor (CC-BY 4.0).\n"
    "Pour ne plus recevoir ces courriels : {url}/parametres"
)


def send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.email_from, to, subject
    msg.set_content(body + FOOTER.format(url=s.web_base_url))
    if s.email_backend == "console":
        log.info("courriel (console)", extra={"to": to, "subject": subject})
        print(f"--- COURRIEL à {to} ---\n{subject}\n\n{msg.get_content()}")
        return
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        if s.smtp_user:
            smtp.starttls()
            smtp.login(s.smtp_user, s.smtp_password or "")
        smtp.send_message(msg)


def magic_link(to: str, link: str) -> None:
    send(
        to,
        "Votre lien de connexion RadarAO",
        f"Bonjour,\n\nVoici votre lien de connexion à RadarAO (valide 15 minutes) :\n{link}\n\n"
        "Si vous n'avez pas demandé ce lien, ignorez ce courriel.",
    )


def instant_alert(to: str, title: str, buyer: str | None, score: int, days_left: int | None, url: str) -> None:
    left = f" · il reste {days_left} jour(s)" if days_left is not None else ""
    send(
        to,
        f"Nouvel appel d'offres pertinent ({score}/100) : {title[:80]}",
        f"Un nouvel avis correspond à votre profil :\n\n{title}\n{buyer or ''}{left}\nScore : {score}/100\n\n"
        f"Voir l'avis : {url}",
    )


def weekly_digest(to: str, freshness: str, rows: list[tuple[str, str | None, int, int | None, str]]) -> None:
    lines = [
        f"• [{score}] {title} — {buyer or ''}" + (f" (⏱ {d} j)" if d is not None else "") + f"\n  {url}"
        for title, buyer, score, d, url in rows
    ]
    send(
        to,
        f"RadarAO — {len(rows)} appel(s) d'offres pour vous cette semaine",
        f"Données SEAO à jour au {freshness}.\n\n"
        + (
            "\n".join(lines)
            if lines
            else "Aucun avis pertinent cette semaine. Pensez à élargir votre profil (régions, codes UNSPSC)."
        )
        + "\n\nRappel : les données ouvertes ont jusqu'à une semaine de décalage sur le SEAO en direct.",
    )
