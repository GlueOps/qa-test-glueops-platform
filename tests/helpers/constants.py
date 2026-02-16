"""Shared constants for GlueOps test suite.

Centralizes ingress class names, cluster issuer mappings, and other
configuration that is shared across multiple tests.

WARNING: Tests using captain_manifests are NOT safe for parallel execution
(e.g., pytest-xdist) because they share a deterministic namespace derived
from captain_domain. They must run sequentially.
"""

# Ingress class names to parametrize tests against.
# Each test decorated with @pytest.mark.parametrize("ingress_class_name", INGRESS_CLASS_NAMES)
# will run once per class.
INGRESS_CLASS_NAMES: list[str] = ["public", "public-traefik"]

# Mapping from ingress class name to the cert-manager ClusterIssuer name
# used for LetsEncrypt HTTP01 challenges.
CLUSTER_ISSUER_BY_INGRESS_CLASS: dict[str, str] = {
    "public": "letsencrypt",
    "public-traefik": "letsencrypt-public-traefik",
}

# Valid Traefik OAuth2 middleware annotations for platform-traefik ingresses.
VALID_OAUTH2_MIDDLEWARES: list[str] = [
    "glueops-core-oauth2-proxy-oauth2-with-redirect@kubernetescrd",
    "glueops-core-oauth2-proxy-oauth2-no-redirect@kubernetescrd",
]
