{{/*
Expand the name of the chart.
*/}}
{{- define "agenticrag.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "agenticrag.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart label value.
*/}}
{{- define "agenticrag.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "agenticrag.labels" -}}
helm.sh/chart: {{ include "agenticrag.chart" . }}
{{ include "agenticrag.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (name + instance only).
*/}}
{{- define "agenticrag.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agenticrag.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Image reference: digest takes precedence over tag for content-addressed deploys.
Falls back to tag, then Chart.AppVersion, for backwards compatibility.
*/}}
{{- define "agenticrag.apiImage" -}}
{{- if .Values.api.image.digest -}}
{{ .Values.api.image.repository }}@{{ .Values.api.image.digest }}
{{- else -}}
{{ .Values.api.image.repository }}:{{ .Values.api.image.tag | default .Chart.AppVersion }}
{{- end -}}
{{- end }}

{{- define "agenticrag.frontendImage" -}}
{{- if .Values.frontend.image.digest -}}
{{ .Values.frontend.image.repository }}@{{ .Values.frontend.image.digest }}
{{- else -}}
{{ .Values.frontend.image.repository }}:{{ .Values.frontend.image.tag | default .Chart.AppVersion }}
{{- end -}}
{{- end }}

{{/* ------------------------------------------------------------------- */}}
{{/* Conditional host/port helpers for stateful services                  */}}
{{/* ------------------------------------------------------------------- */}}

{{/*
PostgreSQL host — internal service name if enabled, else external.
*/}}
{{- define "agenticrag.dbHost" -}}
{{- if .Values.postgres.enabled }}
{{- printf "%s-postgres" (include "agenticrag.fullname" .) }}
{{- else }}
{{- required "postgres.external.host is required when postgres.enabled=false" .Values.postgres.external.host }}
{{- end }}
{{- end }}

{{- define "agenticrag.dbPort" -}}
{{- if .Values.postgres.enabled }}
{{- "5432" }}
{{- else }}
{{- .Values.postgres.external.port | default "5432" }}
{{- end }}
{{- end }}

{{/*
Redis host/port.
*/}}
{{- define "agenticrag.redisHost" -}}
{{- if .Values.redis.enabled }}
{{- printf "%s-redis" (include "agenticrag.fullname" .) }}
{{- else }}
{{- required "redis.external.host is required when redis.enabled=false" .Values.redis.external.host }}
{{- end }}
{{- end }}

{{- define "agenticrag.redisPort" -}}
{{- if .Values.redis.enabled }}
{{- "6379" }}
{{- else }}
{{- .Values.redis.external.port | default "6379" }}
{{- end }}
{{- end }}

{{/*
MinIO endpoint.
*/}}
{{- define "agenticrag.minioEndpoint" -}}
{{- if .Values.minio.enabled }}
{{- printf "%s-minio:9000" (include "agenticrag.fullname" .) }}
{{- else }}
{{- required "minio.external.endpoint is required when minio.enabled=false" .Values.minio.external.endpoint }}
{{- end }}
{{- end }}

{{- define "agenticrag.minioSecure" -}}
{{- if .Values.minio.enabled }}
{{- "false" }}
{{- else }}
{{- .Values.minio.external.secure | default false | toString }}
{{- end }}
{{- end }}

{{/*
OTEL endpoint — use tempo service if monitoring enabled, else config value.
*/}}
{{- define "agenticrag.otelEndpoint" -}}
{{- if .Values.config.otelExporterEndpoint }}
{{- .Values.config.otelExporterEndpoint }}
{{- else if and .Values.monitoring.enabled .Values.monitoring.tempo.enabled }}
{{- printf "http://%s-tempo:4318" (include "agenticrag.fullname" .) }}
{{- end }}
{{- end }}

{{/*
CORS allowed origins — auto-compute from ingress host if not set.
*/}}
{{- define "agenticrag.corsAllowedOrigins" -}}
{{- if .Values.config.corsAllowedOrigins }}
{{- .Values.config.corsAllowedOrigins }}
{{- else if and .Values.ingress.enabled .Values.ingress.hosts }}
{{- $host := (index .Values.ingress.hosts 0).host }}
{{- if .Values.ingress.tls }}
{{- printf "https://%s" $host }}
{{- else }}
{{- printf "http://%s" $host }}
{{- end }}
{{- else }}
{{- "http://localhost:3000" }}
{{- end }}
{{- end }}

{{/*
Frontend URL — auto-compute from ingress host.
*/}}
{{- define "agenticrag.frontendUrl" -}}
{{- if .Values.config.frontendUrl }}
{{- .Values.config.frontendUrl }}
{{- else if and .Values.ingress.enabled .Values.ingress.hosts }}
{{- $host := (index .Values.ingress.hosts 0).host }}
{{- if .Values.ingress.tls }}
{{- printf "https://%s" $host }}
{{- else }}
{{- printf "http://%s" $host }}
{{- end }}
{{- else }}
{{- "http://localhost:3000" }}
{{- end }}
{{- end }}

{{/*
Public API URL — browser-facing URL for the API (used as NEXT_PUBLIC_API_URL).
*/}}
{{- define "agenticrag.apiPublicUrl" -}}
{{- if .Values.config.apiPublicUrl }}
{{- .Values.config.apiPublicUrl }}
{{- else if and .Values.ingress.enabled .Values.ingress.hosts }}
{{- $host := (index .Values.ingress.hosts 0).host }}
{{- if .Values.ingress.tls }}
{{- printf "https://%s/api" $host }}
{{- else }}
{{- printf "http://%s/api" $host }}
{{- end }}
{{- else }}
{{- "http://localhost:8000" }}
{{- end }}
{{- end }}

{{/*
MinIO public base URL — used for browser-facing presigned URLs.
Priority: explicit config > auto-computed from MinIO ingress > empty (dev fallback).
*/}}
{{- define "agenticrag.minioPublicBaseUrl" -}}
{{- if .Values.config.minioPublicBaseUrl }}
{{- .Values.config.minioPublicBaseUrl }}
{{- else if and .Values.minio.enabled .Values.minio.ingress.enabled }}
{{- $host := .Values.minio.ingress.host }}
{{- if .Values.minio.ingress.tls }}
{{- printf "https://%s" $host }}
{{- else }}
{{- printf "http://%s" $host }}
{{- end }}
{{- else }}
{{- "" }}
{{- end }}
{{- end }}

{{/*
Secret name — pre-existing or chart-managed.
*/}}
{{- define "agenticrag.secretName" -}}
{{- if .Values.secrets.externalSecret }}
{{- required "secrets.secretName is required when secrets.externalSecret=true" .Values.secrets.secretName }}
{{- else }}
{{- printf "%s-secrets" (include "agenticrag.fullname" .) }}
{{- end }}
{{- end }}

{{/*
ConfigMap name.
*/}}
{{- define "agenticrag.configMapName" -}}
{{- printf "%s-config" (include "agenticrag.fullname" .) }}
{{- end }}
