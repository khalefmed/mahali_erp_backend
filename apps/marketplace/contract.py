# ruff: noqa: RUF001  (French typographic apostrophes in the contract text)
"""Meysara's electronic contract: read, accepted (a ticked box) and kept before a pay-in-4 order.

1. `preview`: the contract for this cart and share. It has the parties, items, schedule and
   plain-language clauses in the shopper's language, the text `VERSION`, and a `digest` of
   everything that binds the shopper (identity, items, prices, amounts).
2. `sign`: when the order is placed, the app sends back the version and digest it showed.
   They must match the order as priced now. Otherwise the shopper reads the new contract
   first (`meysara_contract_outdated`). The contract is stored frozen, in the language shown,
   with when and from where it was accepted.

The clauses are legal text, reviewed outside the code (Sharia committee, lawyer). Any change
to them, in any language, needs a new `VERSION`.
"""

import hashlib
import json
from decimal import Decimal

from django.utils import timezone

from apps.core.exceptions import ApiError, Conflict
from apps.core.middleware import client_ip

from . import kyc, meysara
from .models import MeysaraContract

VERSION = "1.0"
LANGUAGES = ("fr", "ar", "en")

SELLER = {
    "fr": {
        "name": "Meysara, par Infinity Solutions",
        "role": "Achète l’article à la boutique et vous le revend",
        "city": "Nouakchott, Mauritanie",
    },
    "ar": {
        "name": "ميسرة، من إنفينيتي سوليوشنز",
        "role": "تشتري السلعة من المتجر ثم تبيعها لكم",
        "city": "نواكشوط، موريتانيا",
    },
    "en": {
        "name": "Meysara, by Infinity Solutions",
        "role": "Buys the item from the store and sells it to you",
        "city": "Nouakchott, Mauritania",
    },
}

TITLE = {
    "fr": "Contrat de paiement en 4 fois",
    "ar": "عقد الدفع على 4 أقساط",
    "en": "Pay-in-4 contract",
}

# (key, title, text) per language, in the order shown.
CLAUSES = {
    "fr": [
        (
            "no_interest",
            "Aucun intérêt, aucun frais",
            "Vous payez exactement le prix affiché, même en cas de retard. Meysara gagne "
            "une marge sur la vente, comprise dans ce prix et connue dès le départ.",
        ),
        (
            "sale",
            "Meysara vous vend l’article",
            "Meysara achète l’article à la boutique et vous le revend au prix affiché. "
            "L’article est à vous dès la livraison.",
        ),
        (
            "dates",
            "Les dates partent de la livraison",
            "La première échéance tombe 14 jours après la livraison, puis une toutes les "
            "2 semaines. Si la livraison arrive plus tard, les dates sont décalées d’autant.",
        ),
        (
            "payment",
            "Comment payer",
            "Par Bankily, Masrvi ou Sedad, ou en espèces chez un commerçant partenaire "
            "Mahali. Vous pouvez payer une ou toutes les échéances en avance, sans frais.",
        ),
        (
            "difficulty",
            "Si vous avez une difficulté",
            "Prévenez le service client avant la date : nous cherchons une solution avec "
            "vous, sans frais.",
        ),
        (
            "late",
            "En cas de retard de plus de 7 jours",
            "Votre compte Meysara est suspendu : plus de nouvel achat en 4 fois tant que "
            "l’échéance n’est pas réglée. Aucune pénalité. Vos achats payés à la livraison "
            "restent possibles.",
        ),
        (
            "cancel",
            "Si la commande est annulée ou refusée",
            "Le plan est annulé et rien ne vous est dû.",
        ),
        (
            "claim",
            "Un problème avec votre commande",
            "Contactez le service client Mahali. Nous examinons votre réclamation avant de "
            "vous relancer pour l’échéance concernée.",
        ),
        (
            "data",
            "Vos données",
            "Votre identité et vos paiements servent uniquement à Meysara. Ils ne sont "
            "jamais transmis aux boutiques.",
        ),
        (
            "law",
            "Cadre",
            "Contrat soumis au droit mauritanien et à l’Instruction de la BCM "
            "n°13/GR/2025. Cocher la case et confirmer la commande vaut signature.",
        ),
    ],
    "ar": [
        (
            "no_interest",
            "لا فوائد ولا رسوم",
            "تدفعون السعر المعروض بالضبط، حتى في حال التأخر. تربح ميسرة هامشًا من البيع، "
            "وهو مُدرج في هذا السعر ومعروف منذ البداية.",
        ),
        (
            "sale",
            "ميسرة تبيعكم السلعة",
            "تشتري ميسرة السلعة من المتجر ثم تبيعها لكم بالسعر المعروض. تصبح السلعة "
            "ملكًا لكم عند التسليم.",
        ),
        (
            "dates",
            "المواعيد تبدأ من يوم التسليم",
            "يحل القسط الأول بعد 14 يومًا من التسليم، ثم قسط كل أسبوعين. إذا تأخر "
            "التسليم، تتأخر المواعيد بالقدر نفسه.",
        ),
        (
            "payment",
            "طريقة الدفع",
            "عبر بنكيلي أو مصرفي أو سداد، أو نقدًا لدى تاجر شريك لمحلي. يمكنكم دفع قسط "
            "أو كل الأقساط مسبقًا دون أي رسوم.",
        ),
        (
            "difficulty",
            "إذا واجهتم صعوبة",
            "أخبروا خدمة العملاء قبل الموعد: نبحث معكم عن حل، دون أي رسوم.",
        ),
        (
            "late",
            "في حال التأخر أكثر من 7 أيام",
            "يُعلَّق حسابكم في ميسرة: لا شراء جديد على 4 أقساط حتى يُسدَّد القسط. لا "
            "غرامة. يبقى الشراء مع الدفع عند التسليم ممكنًا.",
        ),
        (
            "cancel",
            "إذا أُلغي الطلب أو رُفض",
            "تُلغى خطة الأقساط ولا يترتب عليكم شيء.",
        ),
        (
            "claim",
            "مشكلة في طلبكم",
            "اتصلوا بخدمة عملاء محلي. ندرس شكواكم قبل تذكيركم بالقسط المعني.",
        ),
        (
            "data",
            "بياناتكم",
            "تُستعمل هويتكم ومدفوعاتكم لميسرة فقط، ولا تُرسل أبدًا إلى المتاجر.",
        ),
        (
            "law",
            "الإطار",
            "يخضع هذا العقد للقانون الموريتاني ولتعليمة البنك المركزي الموريتاني رقم "
            "13/GR/2025. وضع العلامة في الخانة وتأكيد الطلب يُعدّ توقيعًا.",
        ),
    ],
    "en": [
        (
            "no_interest",
            "No interest, no fees",
            "You pay exactly the price shown, even if you are late. Meysara earns a margin "
            "on the sale, included in that price and known from the start.",
        ),
        (
            "sale",
            "Meysara sells you the item",
            "Meysara buys the item from the store and sells it to you at the price shown. "
            "The item is yours on delivery.",
        ),
        (
            "dates",
            "Dates start from delivery",
            "The first instalment falls due 14 days after delivery, then one every 2 weeks. "
            "If delivery comes later, the dates move by the same amount.",
        ),
        (
            "payment",
            "How to pay",
            "With Bankily, Masrvi or Sedad, or in cash at a Mahali partner store. You may "
            "pay one or all instalments early, at no cost.",
        ),
        (
            "difficulty",
            "If you have a difficulty",
            "Tell customer service before the date: we look for a solution with you, at no cost.",
        ),
        (
            "late",
            "More than 7 days late",
            "Your Meysara account is suspended: no new pay-in-4 purchase until the "
            "instalment is paid. No penalty. Orders paid on delivery remain possible.",
        ),
        (
            "cancel",
            "If the order is cancelled or refused",
            "The plan is cancelled and you owe nothing.",
        ),
        (
            "claim",
            "A problem with your order",
            "Contact Mahali customer service. We review your claim before reminding you of "
            "the instalment concerned.",
        ),
        (
            "data",
            "Your data",
            "Your identity and payments are used for Meysara only. They are never shared "
            "with stores.",
        ),
        (
            "law",
            "Legal framework",
            "This contract is governed by Mauritanian law and Central Bank of Mauritania "
            "Instruction no. 13/GR/2025. Ticking the box and confirming the order is your "
            "signature.",
        ),
    ],
}


def _quantity(value) -> str:
    """3 and 3.000 must give the same digest."""
    q = Decimal(str(value)).normalize()
    return f"{q:f}"


def masked_nni(nni: str) -> str:
    return f"•••• {nni[-4:]}"


def _identity(customer):
    identity = kyc.verified_identity(customer)
    if identity is None:  # the offer already requires it; never reached in practice
        raise Conflict(
            "meysara_not_allowed",
            "Meysara is not available for this order.",
            extra={"reason": meysara.Reason.IDENTITY, "choices": []},
        )
    return identity


def digest(identity, lines: list[dict], total: int, percent: int) -> str:
    """What binds the shopper; the language only changes how it reads."""
    payload = {
        "version": VERSION,
        "nni": identity.nni,
        "lines": [
            [str(line["variant"]), _quantity(line["quantity"]), line["unit_price"]]
            for line in sorted(lines, key=lambda line: str(line["variant"]))
        ],
        "total": total,
        "percent": percent,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def terms(identity, lines: list[dict], total: int, percent: int, language: str) -> dict:
    """The contract as shown and as stored. `lines`: variant, description, quantity,
    unit_price, line_total."""
    financed = meysara.financed(total, percent)
    return {
        "version": VERSION,
        "language": language,
        "title": TITLE[language],
        "digest": digest(identity, lines, total, percent),
        "buyer": {
            "full_name": f"{identity.first_name} {identity.last_name}",
            "nni": masked_nni(identity.nni),
            "phone": identity.phone,
        },
        "seller": SELLER[language],
        "lines": [
            {
                "description": line["description"],
                "quantity": _quantity(line["quantity"]),
                "line_total": line["line_total"],
            }
            for line in lines
        ],
        "total": total,
        "percent": percent,
        "on_delivery": total - financed,
        "financed": financed,
        "instalments": [
            {
                "number": n,
                "amount": amount,
                "days_after_delivery": n * meysara.INTERVAL_DAYS,
            }
            for n, amount in enumerate(meysara.split(financed), start=1)
        ],
        "interest": 0,
        "fees": 0,
        "late_fees": 0,
        "clauses": [
            {"key": key, "title": title, "text": text} for key, title, text in CLAUSES[language]
        ],
    }


def _check_offer(customer, total: int, percent: int) -> None:
    current = meysara.offer(customer, total)
    if not current.eligible or percent not in current.choices:
        raise Conflict(
            "meysara_not_allowed",
            "Meysara is not available for this order.",
            extra={
                "field": "meysara_percent",
                "reason": current.reason,
                "choices": current.choices,
            },
        )


def preview(customer, *, lines: list[dict], percent: int, language: str) -> dict:
    from .services import price_lines  # services imports this module

    priced, total = price_lines(lines, strict=True)
    _check_offer(customer, total, percent)
    identity = _identity(customer)
    return terms(
        identity,
        [
            {
                "variant": line.variant_id,
                "description": line.description,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "line_total": line.line_total,
            }
            for line in priced
        ],
        total,
        percent,
        language,
    )


def sign(order, plan, acceptance: dict | None, request=None) -> MeysaraContract:
    """Inside the order transaction, right after the plan is reserved."""
    if not acceptance or not acceptance.get("accepted"):
        raise ApiError(
            "meysara_contract_required",
            "Read and accept the Meysara contract first.",
            extra={"field": "meysara_contract"},
        )
    identity = _identity(order.customer)
    lines = [
        {
            "variant": line.variant_id,
            "description": line.description,
            "quantity": line.quantity,
            "unit_price": line.unit_price,
            "line_total": line.line_total,
        }
        for line in order.lines.all()
    ]
    language = acceptance.get("language") or "fr"
    signed = terms(identity, lines, order.total, plan.percent, language)
    if acceptance.get("version") != VERSION or acceptance.get("digest") != signed["digest"]:
        raise Conflict(
            "meysara_contract_outdated",
            "The contract changed since it was read: read it again.",
            extra={"field": "meysara_contract", "version": VERSION},
        )
    return MeysaraContract.objects.create(
        plan=plan,
        number=f"MEY-{order.number.removeprefix('MP-')}",
        version=VERSION,
        language=language,
        digest=signed["digest"],
        terms=signed,
        accepted_at=timezone.now(),
        ip=client_ip(request) if request else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:255] if request else ""),
    )
