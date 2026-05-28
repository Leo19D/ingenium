# Setup u terminalu (VS Code + Claude Code)

Korak po korak da projekt otvoriš lokalno i radiš s Claude Code agentom.

## 1. Raspakiraj na pravo mjesto

```bash
# Premjesti arhivu gdje držiš projekte, npr:
mkdir -p ~/projekti && cd ~/projekti
tar -xzf ~/Downloads/ai-quote-platform.tar.gz
cd ai-quote-platform
```

## 2. Inicijaliziraj git (važno!)

Git ti daje rollback ako Claude Code nešto zabrlja.

```bash
git init
git add -A
git commit -m "Početni import: backend skeleton + frontend prototip"
```

## 3. Otvori u VS Code

```bash
code .
```

VS Code će ti ponuditi instalaciju preporučenih ekstenzija (Python, Pylance, Ruff, Docker) — prihvati. To je iz `.vscode/extensions.json`.

## 4. Instaliraj Claude Code

Treba ti **plaćeni Claude račun** (Pro $20/mj, Max, Teams/Enterprise ili Console API). Besplatni Claude.ai NE uključuje Claude Code.

**Mac / Linux** (preporučeno — native, bez Node.js ovisnosti):
```bash
curl -fsSL https://claude.ai/install.sh | bash
```

**Ili preko npm** (treba Node.js 18+):
```bash
npm install -g @anthropic-ai/claude-code
```

**Windows:** preporuča se WSL2 (Node mora biti instaliran *unutar* WSL-a, ne samo na Windowsu). Native PowerShell + Git Bash isto rade.

## 5. Pokreni Claude Code u folderu

```bash
cd ~/projekti/ai-quote-platform
claude
```

Prvi put: otvorit će browser za OAuth login. Nakon toga Claude Code automatski čita `CLAUDE.md` iz roota i zna sve o projektu (stack, komande, što je gotovo, što je TODO).

## 6. Provjeri da app radi

U zasebnom terminalu:
```bash
cp .env.example .env
# uredi .env: postavi SECRET_KEY na bilo koji random string (32+ znakova)
make up
```

Otvori http://localhost:8000 — badge gore lijevo treba pisati `● backend spojen`. Dodaj klijenta, osvježi stranicu, podatak je još tu (znači baza radi).

## Korisni Claude Code potezi

- `/init` — regenerira/dopuni CLAUDE.md ako želiš (već imaš dobar, pa nije nužno)
- `/clear` — očisti kontekst za novi task (Claude Code ponovo pročita CLAUDE.md)
- Budi specifičan: ne "popravi auth", nego "u app/api/v1/auth.py dodaj POST /login koji vraća JWT"
- Nakon svake gotove cjeline: `git add -A && git commit -m "..."` — Claude Code to može i sam ako tražiš

## Prvi zadatak za Claude Code (prijedlog)

Otvori `claude` i reci mu nešto poput:

> Pročitaj CLAUDE.md. Hoću implementirati auth (točka 1 u TODO). Prvo mi opiši plan: koji endpointi, koje schemas, kako mijenjaš get_current_org_id. Ne piši kod dok ne odobrim.
