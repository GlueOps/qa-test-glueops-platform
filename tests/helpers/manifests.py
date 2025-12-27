"""
Manifest generation helpers for dynamic ArgoCD resources.

This module provides functions to generate Kubernetes and ArgoCD manifests
dynamically for test environments based on captain domain and tenant configuration.
"""
import logging

logger = logging.getLogger(__name__)


def extract_namespace_from_captain_domain(captain_domain: str) -> str:
    """
    Extract the namespace/environment name from a captain domain.
    
    The namespace is the first part of the captain domain before the first dot.
    For example:
    - 'nonprod.jupiter.onglueops.rocks' -> 'nonprod'
    - 'staging.saturn.onglueops.com' -> 'staging'
    - 'prod.mars.onglueops.io' -> 'prod'
    
    Args:
        captain_domain: The full captain domain (e.g., 'nonprod.jupiter.onglueops.rocks')
        
    Returns:
        str: The namespace/environment name (e.g., 'nonprod')
    """
    return captain_domain.split('.')[0]


def generate_namespace_yaml(namespace_name: str) -> str:
    """
    Generate a Kubernetes Namespace manifest YAML.
    
    Args:
        namespace_name: Name of the namespace (e.g., 'nonprod')
        
    Returns:
        str: YAML string for the Namespace resource
    """
    return f"""apiVersion: v1
kind: Namespace
metadata:
  labels:
    kubernetes.io/metadata.name: {namespace_name}
  name: {namespace_name}
"""


def generate_appproject_yaml(namespace_name: str, tenant_github_org: str) -> str:
    """
    Generate an ArgoCD AppProject manifest YAML.
    
    The AppProject defines RBAC, source repos, and destinations for a tenant environment.
    Groups are hardcoded to use 'developers' role pattern.
    
    Args:
        namespace_name: Name of the namespace/project (e.g., 'nonprod')
        tenant_github_org: GitHub organization name for the tenant (e.g., 'development-tenant-jupiter')
        
    Returns:
        str: YAML string for the AppProject resource
    """
    return f"""apiVersion: argoproj.io/v1alpha1
kind: AppProject   
metadata:
  name: {namespace_name}
spec:      
  sourceNamespaces:
  - '{namespace_name}'                  
  clusterResourceBlacklist:
  - group: '*'
    kind: '*'   
  namespaceResourceBlacklist:
  - group: '*'
    kind: 'Namespace'  
  - group: '*'
    kind: 'CustomResourceDefinition'
  destinations:
  - name: '*'
    namespace: '{namespace_name}'
    server: '*'
  - name: '*'
    namespace: 'glueops-core'
    server: '*'
  roles:
  - description: {tenant_github_org}:developers
    groups:
    - "{tenant_github_org}:developers"
    policies:
    - p, proj:{namespace_name}:read-only, applications, get, {namespace_name}/*, allow
    - p, proj:{namespace_name}:read-only, applications, action/batch/CronJob/create-job, {namespace_name}/*, allow
    - p, proj:{namespace_name}:read-only, logs, *, {namespace_name}/*, allow
    - p, proj:{namespace_name}:read-only, applications, action/external-secrets.io/ExternalSecret/refresh, {namespace_name}/*, allow
    name: read-only
  - description: {tenant_github_org}:developers
    groups:
    - "{tenant_github_org}:developers"
    policies:
    - p, proj:{namespace_name}:read-only, applications, get, {namespace_name}/*, allow   
    - p, proj:{namespace_name}:read-only, applications, sync, {namespace_name}/*, allow   
    - p, proj:{namespace_name}:read-only, logs, *, {namespace_name}/*, allow
    - p, proj:{namespace_name}:read-only, applications, action/external-secrets.io/ExternalSecret/refresh, {namespace_name}/*, allow
    - p, proj:{namespace_name}:read-only, exec, *, {namespace_name}/*, allow   
    - p, proj:{namespace_name}:read-only, applications, action/apps/Deployment/restart, {namespace_name}/*, allow   
    - p, proj:{namespace_name}:read-only, applications, delete/*/Pod/*/*, {namespace_name}/*, allow   
    - p, proj:{namespace_name}:read-only, applications, delete/*/Deployment/*/*, {namespace_name}/*, allow 
    - p, proj:{namespace_name}:read-only, applications, delete/*/ReplicaSet/*/*, {namespace_name}/*, allow 
    - p, proj:{namespace_name}:read-only, applications, action/batch/CronJob/create-job, {namespace_name}/*, allow
    - p, proj:{namespace_name}:read-only, applications, action/batch/Job/terminate, {namespace_name}/*, allow
    name: admins
  sourceRepos:
  - https://helm.gpkg.io/project-template
  - https://helm.gpkg.io/service
  - https://incubating-helm.gpkg.io/project-template
  - https://incubating-helm.gpkg.io/service
  - https://incubating-helm.gpkg.io/platform
  - https://github.com/{tenant_github_org}/*
"""


def generate_appset_yaml(
    namespace_name: str,
    tenant_github_org: str,
    deployment_config_repo: str,
    captain_domain: str
) -> str:
    """
    Generate an ArgoCD ApplicationSet manifest YAML.
    
    The ApplicationSet auto-discovers and deploys applications from the
    deployment-configurations repository based on directory structure.
    
    Args:
        namespace_name: Name of the namespace/environment (e.g., 'nonprod')
        tenant_github_org: GitHub organization name (e.g., 'development-tenant-jupiter')
        deployment_config_repo: Name of the deployment configurations repo (e.g., 'deployment-configurations')
        captain_domain: Full captain domain (e.g., 'nonprod.jupiter.onglueops.rocks')
        
    Returns:
        str: YAML string for the ApplicationSet resource
    """
    repo_url = f"https://github.com/{tenant_github_org}/{deployment_config_repo}"
    
    return f"""apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: {namespace_name}-application-set
  namespace: glueops-core
spec:
  goTemplate: true
  generators:
  - git:
      repoURL: {repo_url}
      revision: main
      directories:
      - path: 'apps/*/envs/*'
      - path: 'apps/*/envs/stage'
      - path: 'apps/*/envs/prod'
      - path: 'apps/*/envs/previews'
        exclude: true

  template:
    metadata:
      name: '{{{{ index .path.segments 1 | replace "." "-"  | replace "_" "-" }}}}-{{{{ .path.basenameNormalized }}}}'
      namespace: {namespace_name}
      annotations:
        preview_environment: 'false'
    spec:
      destination:
        namespace: {namespace_name}
        server: https://kubernetes.default.svc
      project: {namespace_name}
      sources:
      - chart: app
        helm:
          ignoreMissingValueFiles: true
          valueFiles:
          - '$values/common/common-values.yaml'
          - '$values/env-overlays/{namespace_name}/env-values.yaml'
          - '$values/apps/{{{{ index .path.segments 1 }}}}/base/base-values.yaml'
          - '$values/{{{{ .path.path }}}}/values.yaml'
          values: |-
            captain_domain: {captain_domain}
            glueops_app_name: '{{{{ index .path.segments 1 | replace "." "-"  | replace "_" "-" }}}}-{{{{ .path.basenameNormalized }}}}'

        repoURL: https://helm.gpkg.io/project-template
        targetRevision: 0.9.0-rc4
      - repoURL: {repo_url}
        targetRevision: main
        ref: values
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        retry:
          backoff:
            duration: 5s
            factor: 2
            maxDuration: 3m0s
          limit: 2
        syncOptions:
        - CreateNamespace=true
"""
