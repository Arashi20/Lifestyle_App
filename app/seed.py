import click

# A curated starter set of commonly-cited comedogenic/irritant ingredients
# (avoid/caution) and generally well-tolerated ones (good). This is a
# general-knowledge starting point, not personalized medical advice —
# reactions are individual, so treat every entry as freely editable/deletable
# rather than gospel. Names are written to match how they actually appear in
# INCI-style ingredient lists, since the watchlist match is a plain substring
# check.
DEFAULT_WATCHLIST_ITEMS = [
    # (ingredient_name, severity, reason)
    ("Coconut Oil", "avoid", "High comedogenicity rating; commonly clogs pores, especially for acne-prone skin"),
    ("Cocos Nucifera", "avoid", "INCI name for coconut oil — strict ingredient lists print this instead of 'Coconut Oil'"),
    ("Isopropyl Myristate", "avoid", "Known comedogenic emollient; frequently linked to breakouts"),
    ("Isopropyl Palmitate", "avoid", "Comedogenic thickener commonly flagged for clogging pores"),
    ("Cocoa Butter", "avoid", "High comedogenicity rating; heavy and pore-clogging for many skin types"),
    ("Theobroma Cacao", "avoid", "INCI name for cocoa butter — strict ingredient lists print this instead of 'Cocoa Butter'"),
    ("Wheat Germ Oil", "avoid", "Highly comedogenic oil, commonly flagged for acne-prone skin"),
    ("Triticum Vulgare", "avoid", "INCI name for wheat germ oil — strict ingredient lists print this instead of 'Wheat Germ Oil'"),
    ("Lanolin", "avoid", "Can be comedogenic and is a common contact allergen"),
    ("Sodium Lauryl Sulfate", "avoid", "Harsh surfactant that can strip the skin barrier and cause irritation"),
    ("Myristyl Myristate", "avoid", "Comedogenic wax ester, frequently linked to clogged pores"),
    ("Fragrance", "caution", "Common irritant and the top cause of contact sensitization; may also appear as 'Parfum'. Fine for some, triggers reactions for others"),
    ("Alcohol Denat", "caution", "Drying, volatile alcohol; can disrupt the skin barrier with frequent use"),
    ("Limonene", "caution", "Fragrance-derived compound and common contact allergen, especially once oxidized"),
    ("Linalool", "caution", "Fragrance-derived compound and common contact allergen, especially once oxidized"),
    ("Witch Hazel", "caution", "Tannin-rich; can be drying or irritating with frequent use"),
    ("Oxybenzone", "caution", "Chemical UV filter linked to irritation and sensitization in some users"),
    ("Aloe Vera", "good", "Soothing and hydrating; generally non-comedogenic and well-tolerated"),
    ("Aloe Barbadensis", "good", "INCI name for aloe vera — strict ingredient lists print this (e.g. 'Aloe Barbadensis Leaf Juice') instead of 'Aloe Vera'"),
    ("Niacinamide", "good", "Supports barrier function and evens texture/tone; well-tolerated at typical concentrations"),
    ("Hyaluronic Acid", "good", "Humectant that hydrates without clogging pores; suits nearly all skin types"),
    ("Sodium Hyaluronate", "good", "The salt form of hyaluronic acid — more commonly printed on ingredient lists than 'Hyaluronic Acid' itself"),
    ("Ceramide", "good", "Reinforces the skin's natural barrier; non-comedogenic and broadly well-tolerated"),
    ("Glycerin", "good", "Gentle, effective humectant with minimal irritation risk"),
    ("Panthenol", "good", "Soothing and hydrating; supports barrier repair (Pro-Vitamin B5)"),
    ("Centella Asiatica", "good", "Calming and reparative; low irritation potential"),
    ("Squalane", "good", "Lightweight, non-comedogenic emollient that mimics skin's natural oils"),
    ("Allantoin", "good", "Soothing, skin-conditioning agent with very low irritation risk"),
    ("Bisabolol", "good", "Anti-inflammatory and soothing; low sensitization risk"),
    ("Beta-Glucan", "good", "Soothing polysaccharide (oat/yeast-derived) that supports the skin barrier and holds water well; often recommended for sensitive/reactive skin"),
    ("Adenosine", "good", "Well-studied anti-aging active; recognized by Korea's cosmetic regulator (MFDS) as a functional anti-wrinkle ingredient requiring efficacy data to make that claim"),
    ("Zinc Oxide", "good", "Physical/mineral UV filter; broad-spectrum, minimal absorption, and commonly recommended for sensitive or rosacea-prone skin. Can leave a white cast, but that's a cosmetic/texture issue, not a skin-tolerability one"),
    ("Madecassoside", "good", "One of the primary active triterpenes in Centella Asiatica; well-studied for wound-healing and barrier repair"),
    ("Asiaticoside", "good", "Centella Asiatica triterpene; promotes collagen synthesis and wound healing"),
    ("Asiatic Acid", "good", "Centella Asiatica triterpene; anti-inflammatory and antioxidant"),
    ("Madecassic Acid", "good", "Centella Asiatica triterpene; anti-inflammatory, often studied alongside madecassoside"),
]


def register_cli(app):
    @app.cli.command("seed-watchlist")
    def seed_watchlist():
        """Add the curated starter ingredients to the watchlist.

        Safe to re-run: skips any ingredient name you already have (whether
        from a previous seed or one you added yourself), so it never
        overwrites your own entries.
        """
        from app import db
        from app.models import WatchlistItem

        existing = {item.ingredient_name.lower() for item in WatchlistItem.query.all()}
        added = 0
        for name, severity, reason in DEFAULT_WATCHLIST_ITEMS:
            if name.lower() in existing:
                continue
            db.session.add(WatchlistItem(ingredient_name=name, severity=severity, reason=reason))
            added += 1
        db.session.commit()
        skipped = len(DEFAULT_WATCHLIST_ITEMS) - added
        click.echo(f"Seeded {added} watchlist ingredients ({skipped} already present, skipped).")
