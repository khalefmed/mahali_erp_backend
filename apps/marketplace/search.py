"""Shop-window search: accent-insensitive, with the words shoppers actually type.

DRF's SearchFilter needs the exact spelling: "frigo" or "refrigerateur" found nothing.
Here each word of `?search=` is folded (lower case, no accents, as Postgres `translate`
does on the columns, no extension needed) and expanded with everyday synonyms; a product
matches when every word matches one of its fields (name, Arabic name, brand, category,
barcode).
"""

import unicodedata
from functools import reduce
from operator import or_

from django.db.models import F, Func, Q, Value
from django.db.models.functions import Lower
from rest_framework.filters import SearchFilter

ACCENTED = "àâäáãåçéèêëíìîïñóòôöõúùûüýÿœæ"
PLAIN = "aaaaaaceeeeiiiinooooouuuuyyoa"

# Folded word → folded substrings that also count. Keep it short and concrete.
SYNONYMS = {
    "frigo": ["refrigerateur", "congelateur"],
    "frigidaire": ["refrigerateur"],
    "congelo": ["congelateur"],
    "clim": ["climatiseur"],
    "climatisation": ["climatiseur"],
    "tele": ["televiseur", "tv"],
    "television": ["televiseur", "tv"],
    "tv": ["televiseur", "tv"],
    "telephone": ["smartphone", "telephone"],
    "tel": ["smartphone", "telephone"],
    "portable": ["smartphone", "portable"],
    "mobile": ["smartphone", "telephone"],
    "ordi": ["ordinateur", "macbook", "ideapad"],
    "pc": ["ordinateur", "macbook", "ideapad"],
    "laptop": ["ordinateur", "macbook", "ideapad"],
    "tablette": ["tablette", "ipad", "tab"],
    "casque": ["ecouteurs", "tune"],
    "ecouteur": ["ecouteurs", "airpods", "buds", "freepods"],
    "airpods": ["airpods"],
    "chargeur": ["chargeur", "cable", "power bank"],
    "batterie": ["power bank"],
    "montre": ["montre", "watch"],
    "console": ["console", "playstation", "xbox", "switch"],
    "ps5": ["playstation 5"],
    "ps4": ["playstation 4"],
    "ventilo": ["ventilateur"],
    "micro-onde": ["micro-ondes"],
    "microonde": ["micro-ondes"],
    "lave-linge": ["lave-linge", "machine"],
    "machine": ["lave-linge", "machine"],
    "paracetamol": ["doliprane", "efferalgan", "paracetamol"],
    "fievre": ["doliprane", "efferalgan", "thermometre"],
    "douleur": ["doliprane", "efferalgan", "spasfon"],
    "tension": ["tensiometre"],
    "diabete": ["glucometre"],
    "bebe": ["bebe", "nan", "pampers", "couches", "enfant"],
    "couche": ["couches"],
    "lait": ["lait"],
    "creme": ["creme", "emulsion"],
    "solaire": ["anthelios", "spf"],
    "perceuse": ["perceuse", "visseuse"],
    "outil": ["outillage", "perceuse", "meuleuse", "marteau", "tournevis", "pince"],
    "lampe": ["ampoule"],
    "fil": ["cable"],
    "tuyau": ["tube", "pvc"],
    "fer": ["fer"],
}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def folded(field: str):
    return Func(Lower(F(field)), Value(ACCENTED), Value(PLAIN), function="translate")


class ShopSearchFilter(SearchFilter):
    """`?search=` on the shop window (see module docstring)."""

    folded_fields = ["name", "brand__name", "category__name", "category__parent__name"]
    raw_fields = ["name_ar", "variants__barcode"]

    def filter_queryset(self, request, queryset, view):
        terms = self.get_search_terms(request)
        if not terms:
            return queryset
        queryset = queryset.annotate(
            **{f"_s_{i}": folded(field) for i, field in enumerate(self.folded_fields)}
        )
        for term in terms:
            word = fold(term)
            needles = {word, *SYNONYMS.get(word, [])}
            if word.endswith("s") and len(word) > 3:
                needles.add(word[:-1])  # "frigos", "perceuses"
            matches = [
                Q(**{f"_s_{i}__contains": needle})
                for i in range(len(self.folded_fields))
                for needle in needles
            ]
            matches += [Q(**{f"{field}__icontains": term}) for field in self.raw_fields]
            queryset = queryset.filter(reduce(or_, matches))
        return queryset.distinct()
