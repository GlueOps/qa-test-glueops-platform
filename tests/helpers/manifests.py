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
        targetRevision: 0.9.0-rc5
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


def generate_pullrequest_appset_yaml(
    namespace_name: str,
    tenant_github_org: str,
    deployment_config_repo: str,
    captain_domain: str
) -> str:
    """
    Generate an ArgoCD ApplicationSet manifest YAML for pull request preview environments.
    
    The ApplicationSet auto-discovers pull requests from repositories in the tenant's
    GitHub organization and creates preview environments for each PR.
    
    Uses a matrix generator combining:
    - scmProvider: Discovers all repositories in the organization
    - pullRequest: Monitors pull requests in each discovered repository
    
    Args:
        namespace_name: Name of the namespace/environment (e.g., 'nonprod')
        tenant_github_org: GitHub organization name (e.g., 'development-tenant-jupiter')
        deployment_config_repo: Name of the deployment configurations repo (e.g., 'deployment-configurations')
        captain_domain: Full captain domain (e.g., 'nonprod.jupiter.onglueops.rocks')
        
    Returns:
        str: YAML string for the pull request ApplicationSet resource
    """
    return f"""apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: pull-request-preview-environments
  namespace: glueops-core
spec:
  goTemplate: true
  generators:
  - matrix:
      generators:
      - scmProvider:
          cloneProtocol: https
          github:
            allBranches: false
            organization: {tenant_github_org}
            appSecretName: tenant-repo-creds
          filters:
            - repositoryMatch: demo.*
              pathsDoNotExist: [common/common-values.yaml]
            
      - pullRequest:
          github:
            owner: {tenant_github_org}
            appSecretName: tenant-repo-creds
            repo: '{{{{ .repository }}}}'
          requeueAfterSeconds: 30
  template:
    metadata:
      name: >-
        {{{{- $repo := .repository | replace "_" "-" | replace "." "-" | lower -}}}}
        {{{{- if gt (len $repo) 41 -}}}}
          {{{{- printf "%s-%s" ($repo | trunc 35 | trimSuffix "-") ($repo | sha1sum | trunc 5) -}}}}
        {{{{- else -}}}}
          {{{{- $repo -}}}}
        {{{{- end -}}}}-pr-{{{{- .number -}}}}
      namespace: {namespace_name}
      annotations:
        repository_organization: "{tenant_github_org}"
        repository_name: '{{{{ .repository }}}}'
        preview_environment: 'true'
        pull_request_number: '{{{{.number}}}}'
        branch: '{{{{.branch}}}}'
        branch_slug: '{{{{.branch_slug}}}}'
        head_sha: '{{{{.head_sha}}}}'
        head_short_sha: '{{{{.head_short_sha}}}}'
      finalizers:
      - resources-finalizer.argocd.argoproj.io
      labels:
        type: pull-request
    spec:
      sources:
        - chart: app
          helm:
            ignoreMissingValueFiles: true
            valueFiles:
            - '$configValues/common/common-values.yaml'
            - '$configValues/env-overlays/nonprod/env-values.yaml'
            - '$configValues/apps/{{{{ .repository }}}}/base/base-values.yaml'
            - '$configValues/apps/{{{{ .repository }}}}/envs/previews/common/values.yaml'
            - '$configValues/apps/{{{{ .repository }}}}/envs/previews/pull-request-number/{{{{ .number }}}}/values.yaml'
            values: |-
              image:
                tag: '{{{{.head_sha}}}}'
            
              captain_domain: {captain_domain}
            
          repoURL: https://helm.gpkg.io/project-template
          targetRevision: 0.9.0-rc5
        - repoURL: https://github.com/{tenant_github_org}/{{{{ .repository }}}}
          targetRevision: '{{{{ .head_sha }}}}'
          ref: values
        - repoURL: https://github.com/{tenant_github_org}/{deployment_config_repo}
          targetRevision: main
          ref: configValues
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

      project: {namespace_name}
      destination:
        server: https://kubernetes.default.svc
        namespace: {namespace_name}
"""
