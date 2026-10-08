PY := .venv/bin/python
# On macOS, downloads trust the certificates in the system keychain (as Safari and curl do), so they
# also work behind a TLS-inspecting proxy. Verification stays on. An SSL_CERT_FILE you set wins.
ifeq ($(shell uname),Darwin)
WITH_TRUSTED_CERTS = security find-certificate -a -p /Library/Keychains/System.keychain \
	/System/Library/Keychains/SystemRootCertificates.keychain > .venv/trusted-certs.pem && \
	SSL_CERT_FILE=$${SSL_CERT_FILE:-.venv/trusted-certs.pem}
# boto3 ignores SSL_CERT_FILE and reads AWS_CA_BUNDLE instead. An AWS_CA_BUNDLE you set wins.
AWS_TRUSTED_CERTS = security find-certificate -a -p /Library/Keychains/System.keychain \
	/System/Library/Keychains/SystemRootCertificates.keychain > .venv/trusted-certs.pem && \
	export AWS_CA_BUNDLE=$${AWS_CA_BUNDLE:-$(CURDIR)/.venv/trusted-certs.pem} &&
endif

.PHONY: setup doctor backend frontend dev test seed build run run-aws prices icons

setup:
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -e "./backend[dev]"
	cd frontend && npm install
	git config core.hooksPath .githooks

# Says what isn't ready on this machine and how to fix it. System python3: .venv may be broken.
doctor:
	@python3 scripts/doctor.py

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

# Reads the accounts in config/janitor.yaml through their AWS profiles (read-only).
run-aws: build
	$(AWS_TRUSTED_CERTS) JANITOR_PROVIDER=aws $(PY) -m uvicorn janitor.main:create_app --factory \
		--host 127.0.0.1 --port 8080

prices:
	$(WITH_TRUSTED_CERTS) $(PY) scripts/fetch_prices.py

icons:
	$(WITH_TRUSTED_CERTS) $(PY) scripts/fetch_icons.py
