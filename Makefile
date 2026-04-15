.PHONY: scripts/test-apify

QUERY ?= Abogados en Lima
# Note: QUERY may contain spaces; it is always passed to the script wrapped in
# single quotes (see the docker run command below), so multi-word queries work
# correctly. Example: make scripts/test-apify QUERY="Ferreterías en Bogotá"

## scripts/test-apify: Ejecuta el diagnóstico de Apify en un contenedor Docker temporal.
##   Requiere: Docker instalado y APIFY_API_KEY exportada en el entorno.
##   Uso:
##     export APIFY_API_KEY="tu_token"
##     make scripts/test-apify
##     make scripts/test-apify QUERY="Ferreterías en Bogotá"
scripts/test-apify:
	@if [ -z "$$APIFY_API_KEY" ]; then \
		echo "ERROR: APIFY_API_KEY no está definida."; \
		echo "Exporta el token antes de ejecutar:"; \
		echo "  export APIFY_API_KEY=\"tu_token\""; \
		exit 1; \
	fi
	docker run --rm \
		-e APIFY_API_KEY \
		-v "$(CURDIR)/scripts:/scripts:ro" \
		python:3.11-slim \
		bash -c "pip install --quiet httpx && python /scripts/test_apify_call.py '$(QUERY)'"
