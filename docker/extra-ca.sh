#!/bin/sh
# Optional: zusätzliche Stammzertifikate während des Builds (z. B. hinter einem TLS-inspizierenden Proxy).
# Aufruf im Dockerfile per "source"; ohne das Build-Secret "extra_ca" geschieht nichts.
#   docker compose build --secret id=extra_ca,src=/pfad/zum/ca-bundle.crt   (bzw. docker build --secret …)
# Das Zertifikat landet nicht im Image (Secret-Mount), nur die Umgebungsvariablen dieses Build-Schritts zeigen darauf.
if [ -s /run/secrets/extra_ca ]; then
    cat /etc/ssl/certs/ca-certificates.crt /run/secrets/extra_ca > /tmp/build-ca-bundle.crt 2>/dev/null || cp /run/secrets/extra_ca /tmp/build-ca-bundle.crt
    export SSL_CERT_FILE=/tmp/build-ca-bundle.crt REQUESTS_CA_BUNDLE=/tmp/build-ca-bundle.crt CURL_CA_BUNDLE=/tmp/build-ca-bundle.crt \
           NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca UV_NATIVE_TLS=1 PIP_CERT=/tmp/build-ca-bundle.crt
    printf 'Acquire::https::CaInfo "/tmp/build-ca-bundle.crt";\n' > /etc/apt/apt.conf.d/99extra-ca 2>/dev/null || true
    trap 'rm -f /etc/apt/apt.conf.d/99extra-ca /tmp/build-ca-bundle.crt' EXIT
fi
