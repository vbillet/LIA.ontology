#!/usr/bin/env python3
"""installer_raccord.py — raccorde les skills du socle LIA à l'instance qui l'héberge.

POURQUOI CE SCRIPT EXISTE
    Claude Code ne découvre les skills que dans `.claude/skills/{nom}/`. Un `.claude/skills/`
    imbriqué dans un sous-dossier n'est jamais chargé — constaté, pas supposé (preuve H2 du
    2026-10-05). Le socle, récupéré en sous-module, est donc raccordé par des JONCTIONS Windows
    ou des LIENS SYMBOLIQUES POSIX, posés par ce script.

    Les jonctions ne voyagent pas avec git : c'est voulu. Elles sont ignorées par le dépôt
    d'instance et se recréent après chaque clone en relançant ce script.

OÙ IL S'ATTEND À ÊTRE
    Le socle s'accroche dans le `.claude/` de l'instance :

        {instance}/.claude/            <- le dossier parent du socle
        {instance}/.claude/skills/     <- les skills de l'instance, et les jonctions posées ici
        {instance}/.claude/{socle}/    <- ce dépôt-ci (dossier `lia` par défaut)
        {instance}/.claude/{socle}/.claude/skills/{nom}/   <- les skills du socle

    Noter l'asymétrie : le socle porte son propre `.claude/`, l'instance EST un `.claude/`.

CE QU'IL NE FAIT JAMAIS
    Il ne supprime rien. Devant un vrai dossier portant le nom d'un skill du socle, il REFUSE
    et le dit — il ne remplace pas, il ne fusionne pas.

Usage : python installer_raccord.py [--dry-run]
Code de sortie : 0 si aucun refus, 1 sinon.
"""

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

MARQUEUR_GITIGNORE = "# Jonctions vers le socle"


def chemins():
    """Rend (skills_du_socle, skills_de_l_instance, gitignore_de_l_instance)."""
    socle = Path(__file__).resolve().parent
    instance_claude = socle.parent
    return (
        socle / ".claude" / "skills",
        instance_claude / "skills",
        instance_claude / ".gitignore",
    )


def est_raccord(chemin):
    """Vrai si le chemin est une jonction ou un lien symbolique, pas un vrai dossier.

    ⛔ NE PAS SIMPLIFIER EN `return chemin.is_symlink()`.
    Sous Windows, `os.path.islink()` rend FALSE sur une JONCTION (`mklink /J`) — mesuré au banc
    du 2026-10-10. Avec ce seul test, une jonction déjà posée serait prise pour un vrai dossier
    et le script REFUSERAIT SON PROPRE TRAVAIL à la relance, perdant son idempotence.
    C'est `os.readlink()` qui sait lire une jonction (Python 3.8+), d'où le second test.
    """
    try:
        return chemin.is_symlink() or (chemin.is_dir() and os.readlink(str(chemin)) is not None)
    except (OSError, ValueError):
        return False


def pointe_vers(chemin, cible):
    """Vrai si le raccord existant mène bien à la cible attendue."""
    try:
        return Path(os.path.realpath(str(chemin))) == Path(os.path.realpath(str(cible)))
    except OSError:
        return False


def poser(source, destination):
    """Pose le raccord. Rend (True, '') ou (False, motif)."""
    if platform.system() == "Windows":
        # Une jonction (/J) ne demande aucun privilège particulier, contrairement à /D.
        resultat = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(destination), str(source)],
            capture_output=True,
            text=True,
        )
        if resultat.returncode != 0:
            return False, (resultat.stderr or resultat.stdout).strip()
        return True, ""
    # POSIX — NON CONSTATÉ sur ce poste (point ouvert O1 de la preuve H2).
    try:
        os.symlink(str(source), str(destination), target_is_directory=True)
        return True, ""
    except OSError as erreur:
        return False, str(erreur)


def majorer_gitignore(gitignore, noms, dry_run):
    """Ajoute une ligne d'exclusion par jonction, sous le marqueur. Rend le nombre ajouté."""
    if not noms or not gitignore.is_file():
        return 0
    contenu = gitignore.read_text(encoding="utf-8")
    manquants = [n for n in noms if "skills/{}/".format(n) not in contenu]
    if not manquants or dry_run:
        return len(manquants)
    lignes = ["skills/{}/".format(n) for n in manquants]
    if MARQUEUR_GITIGNORE in contenu:
        contenu = contenu.rstrip("\n") + "\n" + "\n".join(lignes) + "\n"
    else:
        contenu = contenu.rstrip("\n") + "\n\n" + MARQUEUR_GITIGNORE + "\n" + "\n".join(lignes) + "\n"
    gitignore.write_text(contenu, encoding="utf-8", newline="\n")
    return len(manquants)


def main():
    # Point ouvert O3 : sans ceci, les accents du compte rendu sont abîmés sous Windows.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    analyseur = argparse.ArgumentParser(description="Raccorde les skills du socle LIA à l'instance.")
    analyseur.add_argument("--dry-run", action="store_true", help="annonce sans rien poser")
    options = analyseur.parse_args()

    skills_socle, skills_instance, gitignore = chemins()

    print("=== Raccord du socle LIA ===")
    print("Socle    : {}".format(skills_socle))
    print("Instance : {}".format(skills_instance))
    print("Système  : {}{}".format(platform.system(), "  (branche POSIX non constatée)" if platform.system() != "Windows" else ""))
    if options.dry_run:
        print("Mode     : essai à blanc — rien ne sera écrit")
    print()

    if not skills_socle.is_dir():
        print("REFUS : le socle ne porte pas de dossier .claude/skills/ — rien à raccorder.")
        return 1
    if not skills_instance.is_dir():
        print("REFUS : l'instance ne porte pas de dossier skills/ à l'emplacement attendu :")
        print("        {}".format(skills_instance))
        return 1

    candidats = sorted(d.name for d in skills_socle.iterdir() if d.is_dir())
    if not candidats:
        print("Aucun skill dans le socle — rien à raccorder. Ce n'est pas une erreur :")
        print("les agents du socle n'y sont pas encore déposés.")
        return 0

    posees, deja, refus = [], [], []

    for nom in candidats:
        source = skills_socle / nom
        destination = skills_instance / nom

        if not destination.exists() and not destination.is_symlink():
            if options.dry_run:
                posees.append(nom)
                continue
            ok, motif = poser(source, destination)
            (posees if ok else refus).append(nom if ok else (nom, motif))
            continue

        if est_raccord(destination):
            if pointe_vers(destination, source):
                deja.append(nom)
            else:
                refus.append((nom, "raccord existant, mais il mène ailleurs : {}".format(
                    os.path.realpath(str(destination)))))
            continue

        refus.append((nom, "un vrai dossier porte déjà ce nom — rien n'a été touché"))

    ajoutes = majorer_gitignore(gitignore, posees + deja, options.dry_run)

    print("Skills du socle     : {}".format(len(candidats)))
    print("Raccords posés      : {}".format(len(posees)))
    for nom in posees:
        print("   + {}".format(nom))
    print("Déjà en place       : {}".format(len(deja)))
    for nom in deja:
        print("   = {}".format(nom))
    print("Refusés             : {}".format(len(refus)))
    for nom, motif in refus:
        print("   ! {} — {}".format(nom, motif))
    print("Lignes de .gitignore{} : {}".format(" à ajouter" if options.dry_run else " ajoutées", ajoutes))

    return 1 if refus else 0


if __name__ == "__main__":
    sys.exit(main())
