output "service_account_email" {
  description = "Service account email for the app"
  value       = google_service_account.app.email
}

output "gcs_bucket_name" {
  description = "GCS bucket for license documents"
  value       = google_storage_bucket.documents.name
}

output "env_file_hint" {
  description = "Environment variables to set in .env for local development"
  value       = <<-EOT
    GOOGLE_CLOUD_PROJECT=${var.project_id}
    GOOGLE_GENAI_USE_VERTEXAI=1
  EOT
}
