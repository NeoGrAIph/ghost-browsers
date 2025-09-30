{{- define "camofleet.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "camofleet.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "camofleet.labels" -}}
helm.sh/chart: {{ include "camofleet.chart" . }}
{{ include "camofleet.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "camofleet.selectorLabels" -}}
app.kubernetes.io/name: {{ include "camofleet.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "camofleet.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" -}}
{{- end -}}

{{- define "camofleet.control.fullname" -}}
{{- printf "%s-control" (include "camofleet.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "camofleet.ui.fullname" -}}
{{- printf "%s-ui" (include "camofleet.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "camofleet.worker.fullname" -}}
{{- printf "%s-worker" (include "camofleet.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "camofleet.workerVnc.fullname" -}}
{{- printf "%s-worker-vnc" (include "camofleet.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "camofleet.image" -}}
{{- $registry := trimSuffix "/" (default "" .Values.global.imageRegistry) -}}
{{- $repository := .repository -}}
{{- $tag := default .tag "latest" -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repository $tag -}}
{{- else -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}
{{- end -}}

{{- define "camofleet.imagePullSecrets" -}}
{{- if .Values.global.imagePullSecrets }}
imagePullSecrets:
{{- range .Values.global.imagePullSecrets }}
  - name: {{ . | quote }}
{{- end }}
{{- end }}
{{- end -}}
