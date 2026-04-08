terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
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
# Document AI Processor — automated setup
# ---------------------------------------------------------------------------
# Creates the Custom Extractor processor, configures the schema from
# docai_schema.json using the Foundation Model, and writes
# backend/docai_config.json so the app can find the processor at runtime.
#
# Re-runs automatically when docai_schema.json changes.

# Allow time for the Document AI API to propagate after enablement
resource "time_sleep" "wait_for_docai_api" {
  depends_on      = [google_project_service.apis]
  create_duration = "60s"
}

resource "null_resource" "docai_setup" {
  depends_on = [time_sleep.wait_for_docai_api]

  triggers = {
    schema_hash = filesha256("${path.module}/../docai_schema.json")
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = "python3 scripts/setup_docai.py --force"

    environment = {
      PROJECT_ID = var.project_id
      GCS_BUCKET = var.gcs_bucket_name
    }
  }
}
