#!/usr/bin/env bash
# Installe la commande « chess-review » et l'entrée du menu d'applications.
#
#     bash scripts/install.sh
#
# Le projet reste où il est : on installe en mode éditable, et le lanceur
# pointe vers le venv. Modifier le code prend effet immédiatement, sans
# réinstaller.

set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$RACINE/.venv"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"

if [ ! -x "$VENV/bin/python" ]; then
    echo "Environnement virtuel introuvable dans $VENV" >&2
    echo "Crée-le d'abord :  python3 -m venv .venv" >&2
    exit 1
fi

echo "Installation des dépendances…"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e "$RACINE"

mkdir -p "$BIN" "$APPS"

# Icône : générée si absente, puis installée dans le thème de l'utilisateur.
# Un chemin absolu dans le .desktop suffirait à l'afficher, mais pas à ce que
# la barre des tâches retrouve l'icône de la fenêtre — d'où hicolor.
if [ ! -f "$RACINE/assets/icon-256.png" ]; then
    echo "Génération de l'icône…"
    "$VENV/bin/python" "$RACINE/scripts/make_icon.py" >/dev/null
fi

for TAILLE in 16 24 32 48 64 128 256 512; do
    CIBLE="$HOME/.local/share/icons/hicolor/${TAILLE}x${TAILLE}/apps"
    if [ -f "$RACINE/assets/icon-$TAILLE.png" ]; then
        mkdir -p "$CIBLE"
        cp "$RACINE/assets/icon-$TAILLE.png" "$CIBLE/chess-review.png"
    fi
done

CIBLE_SVG="$HOME/.local/share/icons/hicolor/scalable/apps"
if [ -f "$RACINE/assets/icon.svg" ]; then
    mkdir -p "$CIBLE_SVG"
    cp "$RACINE/assets/icon.svg" "$CIBLE_SVG/chess-review.svg"
fi

gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

# Un lanceur plutôt qu'un lien symbolique vers le script du venv : il
# fonctionne même si le venv n'est pas activé, et transmet les arguments.
cat > "$BIN/chess-review" <<LAUNCHER
#!/usr/bin/env bash
exec "$VENV/bin/python" -m src.cli "\$@"
LAUNCHER
chmod +x "$BIN/chess-review"

cat > "$APPS/chess-review.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Chess Review
Comment=Analyse tes parties d'échecs avec Stockfish
Exec=$BIN/chess-review %f
Icon=chess-review
Path=$RACINE
Terminal=false
StartupWMClass=chess-review
Categories=Game;BoardGame;
MimeType=application/x-chess-pgn;
DESKTOP

update-desktop-database "$APPS" 2>/dev/null || true

echo
echo "Installé : $BIN/chess-review"
echo "Icône    : $HOME/.local/share/icons/hicolor/*/apps/chess-review.png"
echo "Menu     : $APPS/chess-review.desktop"

case ":$PATH:" in
    *":$BIN:"*) ;;
    *)
        echo
        echo "⚠  $BIN n'est pas dans ton PATH. Ajoute cette ligne à ~/.zshrc :"
        echo "     export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

echo
"$BIN/chess-review" --check || true