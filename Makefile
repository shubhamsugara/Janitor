PY := .venv/bin/python
# On macOS, downloads trust the certificates in the system keychain (as Safari and curl do), so they
# also work behind a TLS-inspecting proxy. Verification stays on. An SSL_CERT_FILE you set wins.
ifeq ($(shell uname),Darwin)
WITH_TRUSTED_CERTS = security find-certificate -a -p /Library/Keychains/System.keychain \
	/System/Library/Keychains/SystemRootCertificates.keychain > .venv/trusted-certs.pem && \
	SSL_CERT_FILE=$${SSL_CERT_FILE:-.venv/trusted-certs.pem}
endif

.PHONY: setup backend frontend dev test seed build run prices icons

setup:
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -e "./backend[dev]"
	cd frontend && npm install
	git config core.hooksPath .githooks

backend:
	$(PY) -m uvicorn janitor.main:create_app --factory --reload --host 127.0.0.1 --port 8080

frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 backend frontend

test:
	$(PY) -m pytest backend -q
	$(PY) -m ruff check backend scripts
	$(PY) scripts/check_private.py
	cd frontend && npm run typecheck
	cd frontend && npm test

seed:
	$(PY) scripts/make_seed.py

build:
	cd frontend && npm run build

run: build
	$(PY) -m uvicorn janitor.main:create_app --factory --host 127.0.0.1 --port 8080

prices:
	$(WITH_TRUSTED_CERTS) $(PY) scripts/fetch_prices.py

icons:
	$(WITH_TRUSTED_CERTS) $(PY) scripts/fetch_icons.py
