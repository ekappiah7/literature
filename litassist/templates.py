"""Starter projects. These are drafts to edit, not final strategies."""

SSA_COUNTRIES = [
    "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi", "Cameroon", "Cape Verde", "Cabo Verde",
    "Central African Republic", "Chad", "Comoros", "Congo", "Cote d'Ivoire", "Ivory Coast", "Djibouti",
    "Equatorial Guinea", "Eritrea", "Eswatini", "Swaziland", "Ethiopia", "Gabon", "Gambia", "Ghana",
    "Guinea-Bissau", "Conakry", "Kenya", "Lesotho", "Liberia", "Madagascar", "Malawi", "Mali",
    "Mauritania", "Mauritius", "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda", "Sao Tome",
    "Senegal", "Seychelles", "Sierra Leone", "Somalia", "South Africa", "South Sudan", "Sudan",
    "Tanzania", "Togo", "Uganda", "Zambia", "Zimbabwe",
]

ART_BLOCK = (
    '"Reproductive Techniques, Assisted"[Mesh] OR "Fertilization in Vitro"[Mesh] '
    'OR "Sperm Injections, Intracytoplasmic"[Mesh] OR "Embryo Transfer"[Mesh] '
    'OR "in vitro fertilization"[tiab] OR "in vitro fertilisation"[tiab] OR IVF[tiab] '
    'OR ICSI[tiab] OR "intracytoplasmic sperm injection"[tiab] '
    'OR "assisted reproductive technology"[tiab] OR "assisted reproductive technologies"[tiab] '
    'OR "assisted reproduction"[tiab] OR "embryo transfer"[tiab]'
)

SSA_BLOCK = (
    '"Africa South of the Sahara"[Mesh] OR "sub-Saharan"[tiab] OR "sub Saharan"[tiab] OR Africa[tiab] OR '
    + " OR ".join(f'"{c}"[tiab]' if " " in c or "'" in c else f"{c}[tiab]" for c in SSA_COUNTRIES)
)

# Removes records indexed as animal-only studies. Records not yet MeSH indexed are kept.
ANIMAL_FILTER = 'NOT ("Animals"[Mesh] NOT "Humans"[Mesh])'

OBJECTIVE_1_STRATEGY = f"({ART_BLOCK})\nAND\n({SSA_BLOCK})\n{ANIMAL_FILTER}"

TEMPLATES = {
    "PhD Obj 1: ART outcomes in SSA (scoping review)": {
        "question": (
            "What outcomes of IVF and ICSI have been reported in sub-Saharan Africa, how were they "
            "defined and with what denominators, and which statistical methods were used to analyse them?"
        ),
        "review_type": "Scoping review",
        "population": "Women or couples undergoing IVF or ICSI in any setting in sub-Saharan Africa.",
        "concept": (
            "Reported treatment outcomes (biochemical, clinical and ongoing pregnancy, live birth, cumulative "
            "live birth), their definitions and denominators, the unit of analysis, and the statistical methods used."
        ),
        "context": "Clinics and populations in the 48 countries of sub-Saharan Africa. Any date, any language.",
        "inclusion": (
            "Primary studies of any design reporting at least one IVF or ICSI outcome for patients treated in "
            "sub-Saharan Africa. Conference abstracts and theses included if outcome data are reported."
        ),
        "exclusion": (
            "Animal or laboratory-only studies. Studies of IUI or ovulation induction only. Reviews, editorials "
            "and commentaries (kept for reference searching). Studies of African patients treated outside Africa."
        ),
        "strategy": OBJECTIVE_1_STRATEGY,
    },
}
