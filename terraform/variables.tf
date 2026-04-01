variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for regional resources"
  type        = string
  default     = "us-central1"
}

variable "gcs_bucket_name" {
  description = "Name of the GCS bucket for license document storage (batch mode)"
  type        = string
}

variable "gcs_bucket_location" {
  description = "Location for the GCS bucket"
  type        = string
  default     = "US"
}

variable "service_account_id" {
  description = "ID for the app service account"
  type        = string
  default     = "alcohol-license-verifier"
}
