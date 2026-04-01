terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# Enable required APIs
# ---------------------------------------------------------------------------

resource "google_project_service" "apis" {
  for_each = toset([
    "documentai.googleapis.com",
    "aiplatform.googleapis.com",
    "storage.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Service Account
# ---------------------------------------------------------------------------

resource "google_service_account" "app" {
  account_id   = var.service_account_id
  display_name = "Alcohol License Verification App"
  project      = var.project_id
}

# IAM roles required by the app
resource "google_project_iam_member" "roles" {
  for_each = toset([
    "roles/documentai.apiUser",    # Document AI extraction
    "roles/aiplatform.user",       # Vertex AI / Gemini
    "roles/storage.objectViewer",  # GCS file access (batch mode)
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.app.email}"
}

# ---------------------------------------------------------------------------
# GCS Bucket — license document storage for batch mode
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "documents" {
  name     = var.gcs_bucket_name
  location = var.gcs_bucket_location
  project  = var.project_id

  uniform_bucket_level_access = true

  # Prevent accidental deletion
  force_destroy = false
}

# ---------------------------------------------------------------------------
# Note: Document AI Processor
# ---------------------------------------------------------------------------
# The Document AI custom extractor (processor d426bbd65fc4de7d in project
# 757654702990) is pre-trained and configured outside of Terraform.
# It is referenced by ID in backend/document_ai.py.
