{{- define "agentberth.name" -}}
{{- printf "%s-agentberth" .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- define "agentberth.sandbox" -}}
{{- default (printf "%s-sandbox" .Release.Namespace) .Values.sandboxNamespace -}}
{{- end -}}
{{- define "agentberth.security" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}
{{- define "agentberth.containerSecurity" -}}
readOnlyRootFilesystem: true
allowPrivilegeEscalation: false
capabilities:
  drop: [ALL]
{{- end -}}
