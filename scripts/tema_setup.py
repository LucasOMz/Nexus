"""Rebaseia o tema do assistente de instalacao para o verde do Nexus.

O setup.css tem copia propria dos tokens (precisa funcionar antes de existir
banco), e ficou com o vermelho antigo. Aqui ele passa a bater com o sistema.
"""
from __future__ import annotations

import io
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "frontend" / "setup" / "setup.css"

TROCAS = [
    # --- tema claro: verde, igual ao sistema ---
    ("--md-sys-color-primary: #B3261E;", "--md-sys-color-primary: #2F6B4F;"),
    ("--md-sys-color-primary-container: #FFDAD6;", "--md-sys-color-primary-container: #B4F1CE;"),
    ("--md-sys-color-on-primary-container: #410002;", "--md-sys-color-on-primary-container: #00210F;"),
    ("--md-sys-color-secondary-container: #FFDAD4;", "--md-sys-color-secondary-container: #D3E8D6;"),
    ("--md-sys-color-on-secondary-container: #2C1512;", "--md-sys-color-on-secondary-container: #0D1F14;"),
    ("--md-sys-color-tertiary-container: #F6E3A1;", "--md-sys-color-tertiary-container: #BDEBF2;"),
    ("--md-sys-color-on-tertiary-container: #231B00;", "--md-sys-color-on-tertiary-container: #001F24;"),
    ("--md-sys-color-surface: #FFFFFF;", "--md-sys-color-surface: #F7FBF7;"),
    ("--md-sys-color-on-surface: #201A19;", "--md-sys-color-on-surface: #171D19;"),
    ("--md-sys-color-surface-container: #FDF6F5;", "--md-sys-color-surface-container: #EBF3EC;"),
    ("--md-sys-color-surface-container-high: #F9ECEA;", "--md-sys-color-surface-container-high: #E0EAE2;"),
    ("--md-sys-color-surface-container-highest: #F3E3E0;", "--md-sys-color-surface-container-highest: #DAE5DC;"),
    ("--md-sys-color-on-surface-variant: #534341;", "--md-sys-color-on-surface-variant: #414942;"),
    ("--md-sys-color-outline: #857370;", "--md-sys-color-outline: #717971;"),
    ("--md-sys-color-outline-variant: #E6D3D0;", "--md-sys-color-outline-variant: #C1C9C1;"),
    ("--cor-ok: #1E6B3A;", "--cor-ok: #1F6B3F;"),
    # --- tema escuro: verde CLARO (o escuro sumiria no fundo) ---
    ("--md-sys-color-primary: #FFB4AB;", "--md-sys-color-primary: #99D5B3;"),
    ("--md-sys-color-on-primary: #690005;", "--md-sys-color-on-primary: #00391F;"),
    ("--md-sys-color-primary-container: #93000A;", "--md-sys-color-primary-container: #14522F;"),
    ("--md-sys-color-on-primary-container: #FFDAD6;", "--md-sys-color-on-primary-container: #B4F1CE;"),
    ("--md-sys-color-secondary-container: #5D3F3C;", "--md-sys-color-secondary-container: #384B3D;"),
    ("--md-sys-color-on-secondary-container: #FFDAD4;", "--md-sys-color-on-secondary-container: #D3E8D6;"),
    ("--md-sys-color-tertiary-container: #54461A;", "--md-sys-color-tertiary-container: #1F4D54;"),
    ("--md-sys-color-on-tertiary-container: #F6E3A1;", "--md-sys-color-on-tertiary-container: #BDEBF2;"),
    ("--md-sys-color-surface: #201A19;", "--md-sys-color-surface: #111A13;"),
    ("--md-sys-color-on-surface: #EDE0DE;", "--md-sys-color-on-surface: #DFE4DE;"),
    ("--md-sys-color-surface-container-lowest: #1A1413;", "--md-sys-color-surface-container-lowest: #0C140E;"),
    ("--md-sys-color-surface-container: #251E1D;", "--md-sys-color-surface-container: #1D261F;"),
    ("--md-sys-color-surface-container-high: #302827;", "--md-sys-color-surface-container-high: #28312A;"),
    ("--md-sys-color-surface-container-highest: #3B3231;", "--md-sys-color-surface-container-highest: #333C35;"),
    ("--md-sys-color-on-surface-variant: #D8C2BF;", "--md-sys-color-on-surface-variant: #C1C9C1;"),
    ("--md-sys-color-outline: #A08C89;", "--md-sys-color-outline: #8B938C;"),
    ("--md-sys-color-outline-variant: #534341;", "--md-sys-color-outline-variant: #414942;"),
]


def main() -> None:
    c = io.open(P, encoding="utf-8", newline="").read()
    n = 0
    for de, para in TROCAS:
        if de in c:
            c = c.replace(de, para, 1)
            n += 1

    # `background` e a cor da PAGINA. Nao existia aqui, entao o assistente
    # herdava o branco do navegador — e o "fundo verdinho" nao aparecia.
    if "--md-sys-color-background" not in c:
        c = c.replace(
            ":root {\n",
            ":root {\n  --md-sys-color-background: #F1F7F1;\n",
            1,
        )
        c = c.replace(
            "    --md-sys-color-surface: #111A13;",
            "    --md-sys-color-surface: #111A13;\n    --md-sys-color-background: #0E1610;",
            1,
        )
        n += 2

    io.open(P, "w", encoding="utf-8", newline="").write(c)
    print(f"  {n} tokens ajustados no setup.css")
    print(f"  fundo claro: {'#F1F7F1' in c}")
    print(f"  marca verde: {'#2F6B4F' in c}")


if __name__ == "__main__":
    main()
