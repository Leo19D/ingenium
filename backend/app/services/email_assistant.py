"""
Email asistent — generira draft poruke uz ponudu.

Tri tipa: cover (uz ponudu), follow_up (podsjetnik), thank_you (nakon dobivene).
Ako je ANTHROPIC_API_KEY postavljen → Claude personalizira draft koristeći
kontekst (klijent, iznos, marža povijest). Inače → kvalitetan template.

Asistent NIKAD ne šalje — samo predlaže draft koji čovjek pregleda i pošalje.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

VALID_TYPES = {"cover", "follow_up", "thank_you"}


def _template_draft(
    *, draft_type: str, client_name: str, project_name: str,
    total: str, currency: str, version: int, org_name: str,
) -> dict:
    """Deterministički template kad LLM nije dostupan."""
    greeting = f"Poštovani{(' ' + client_name) if client_name else ''},"
    sign = f"Srdačan pozdrav,\n{org_name}"

    if draft_type == "follow_up":
        subject = f"Podsjetnik — ponuda za {project_name}"
        body = (
            f"{greeting}\n\n"
            f"javljamo se u vezi ponude V{version} za projekt „{project_name}“ "
            f"u iznosu od {total} {currency}, koju smo Vam poslali ranije.\n\n"
            f"Stojimo Vam na raspolaganju za sva pitanja ili eventualne prilagodbe. "
            f"Rado ćemo dogovoriti kratak poziv ako Vam to odgovara.\n\n"
            f"{sign}"
        )
    elif draft_type == "thank_you":
        subject = f"Hvala na povjerenju — {project_name}"
        body = (
            f"{greeting}\n\n"
            f"zahvaljujemo na ukazanom povjerenju i prihvaćanju ponude za projekt "
            f"„{project_name}“. Veselimo se suradnji.\n\n"
            f"Uskoro ćemo Vam javiti sljedeće korake oko realizacije i isporuke.\n\n"
            f"{sign}"
        )
    else:  # cover
        subject = f"Ponuda za {project_name}"
        body = (
            f"{greeting}\n\n"
            f"u privitku Vam šaljemo ponudu V{version} za projekt „{project_name}“ "
            f"u ukupnom iznosu od {total} {currency}.\n\n"
            f"Ponuda uključuje sve dogovorene stavke. Ukoliko imate pitanja ili "
            f"želite prilagodbe, slobodno nam se javite — rado ćemo izaći ususret.\n\n"
            f"{sign}"
        )
    return {"subject": subject, "body": body, "generated_by": "template"}


async def generate_email_draft(
    *,
    draft_type: str,
    client_name: str,
    project_name: str,
    total: str,
    currency: str,
    version: int,
    org_name: str = "Ingenium",
    history_note: str | None = None,
) -> dict:
    """
    Vrati {subject, body, generated_by}. LLM ako je dostupan, inače template.
    history_note: opcionalni kontekst (npr. "klijent prije kupovao, win rate 60%").
    """
    if draft_type not in VALID_TYPES:
        draft_type = "cover"

    from app.config import settings

    # Bez API ključa → template
    if not settings.ANTHROPIC_API_KEY:
        return _template_draft(
            draft_type=draft_type, client_name=client_name, project_name=project_name,
            total=total, currency=currency, version=version, org_name=org_name,
        )

    # S ključem → Claude personalizira
    try:
        from app.services.llm.claude import ClaudeProvider
        from app.services.llm.provider import LLMMessage

        type_hr = {
            "cover": "propratna poruka uz ponudu koju šaljemo",
            "follow_up": "ljubazan podsjetnik na ranije poslanu ponudu",
            "thank_you": "zahvala nakon što je klijent prihvatio ponudu",
        }[draft_type]

        ctx = (
            f"Tvrtka koja šalje: {org_name}\n"
            f"Klijent: {client_name or 'nepoznat'}\n"
            f"Projekt: {project_name}\n"
            f"Ponuda: V{version}, iznos {total} {currency}\n"
        )
        if history_note:
            ctx += f"Kontekst: {history_note}\n"

        system = (
            "Ti si profesionalni B2B prodajni asistent u tvrtki za rasvjetu/elektromaterijal. "
            "Pišeš kratke, ljubazne i profesionalne poslovne emailove na hrvatskom. "
            "Ton: srdačan ali poslovni, bez pretjeranog marketinga. "
            "NE izmišljaj cijene, rokove ni tehničke detalje koji nisu dani. "
            "Vrati TOČNO u formatu:\nSUBJECT: <predmet>\nBODY:\n<tijelo emaila>"
        )
        user = f"Napiši {type_hr}.\n\nPodaci:\n{ctx}"

        provider = ClaudeProvider()
        resp = await provider.complete(
            [LLMMessage(role="system", content=system),
             LLMMessage(role="user", content=user)],
            max_tokens=600, temperature=0.4,
        )
        text = resp.text.strip()

        # Parse SUBJECT/BODY
        subject, body = project_name, text
        if "SUBJECT:" in text and "BODY:" in text:
            subj_part = text.split("SUBJECT:", 1)[1]
            subject = subj_part.split("BODY:", 1)[0].strip()
            body = subj_part.split("BODY:", 1)[1].strip()
        return {"subject": subject, "body": body, "generated_by": "claude"}
    except Exception as e:
        logger.warning("email_draft_llm_failed", extra={"error": str(e)})
        return _template_draft(
            draft_type=draft_type, client_name=client_name, project_name=project_name,
            total=total, currency=currency, version=version, org_name=org_name,
        )
