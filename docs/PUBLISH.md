# Publicar GitHub Pages (sin 404)

## Requisitos

- Repositorio **público** (Pages gratuito), o plan de pago si el repo es privado.
- Rama **`main`** con la carpeta **`docs/`** en el remoto.

## Una sola vez en GitHub

1. **Settings** del repo → **Pages**.
2. En **Build and deployment**, **Source** debe ser **`GitHub Actions`** (no “Deploy from a branch”).
3. Haz **push** de `main` para que corra el workflow **Deploy GitHub Pages (Jekyll)** (`.github/workflows/pages-jekyll.yml`).
4. En **Actions**, comprueba que el job termine en verde. Si pide **aprobar** el entorno `github-pages`, acéptalo.

## URL del sitio

Patrón estándar:

`https://<usuario-u-org>.github.io/<nombre-del-repo>/`

Ejemplo si el repo es `Treevu-ai/pipeline-pro`:

`https://treevu-ai.github.io/pipeline-pro/`

Si tu repo tiene **otro nombre**, edita `baseurl` en **`docs/_config.yml`** (`/pipeline-pro` → `/tu-repo`) y haz push.

## Sigue apareciendo 404

| Causa | Qué hacer |
|-------|-----------|
| Source = “Deploy from branch” pero no configuraste carpeta `/docs` | Cambia Source a **GitHub Actions** o configura bien branch + `/docs`. |
| Repo **privado** sin plan para Pages | Haz el repo público o contrata función Pages para privados. |
| **Nombre del repo** distinto de `pipeline-pro` | Ajusta `baseurl` en `_config.yml` y la URL que abres en el navegador. |
| Workflow en rojo | Lee el log del job **build** (Ruby/Jekyll); suele ser `Gemfile` / tema. |

## Vista previa local

```bash
cd docs
bundle install
bundle exec jekyll serve --livereload --baseurl /pipeline-pro
```

Abre `http://localhost:4000/pipeline-pro/` (ajusta `pipeline-pro` al mismo `baseurl`).
