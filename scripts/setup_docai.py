#!/usr/bin/env python3
"""
Idempotent setup for Document AI Custom Extractor.

Creates a Custom Extraction processor, initializes its dataset,
configures the schema from docai_schema.json, and writes a config
file that the backend reads at runtime.

The pretrained Foundation Model uses the schema for zero-shot
extraction — no training required.

Usage:
    # Automatically via terraform apply, or manually:
    PROJECT_ID=my-project python3 scripts/setup_docai.py

    # Force schema update even if already configured:
    PROJECT_ID=my-project python3 scripts/setup_docai.py --force
"""

import argparse
import json
import os
import sys
import time

from google.api_core import exceptions as google_exceptions
from google.api_core.client_options import ClientOptions
from google.cloud import documentai
from google.cloud import documentai_v1beta3 as documentai_beta
from google.cloud.documentai_v1beta3.types.document_schema import EntityTypeMetadata

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "docai_schema.json")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "backend", "docai_config.json")

PROCESSOR_DISPLAY_NAME = "alcohol-license-extractor"
LOCATION = "us"

# Root entity type name required by Document AI Custom Extractors
ROOT_ENTITY_NAME = "custom_extraction_document_type"

# Maps the console-style dataType values to Document AI property valueType.
# Valid types per docs: string, number, money, datetime, address, boolean
DATA_TYPE_MAP = {
    "Plain text": "string",
    "Datetime": "datetime",
    "Address": "address",
    "Number": "number",
    "Currency": "money",
}

# Maps occurrence strings to the proto enum
OCCURRENCE_MAP = {
    "Optional once": "OPTIONAL_ONCE",
    "Optional multiple": "OPTIONAL_MULTIPLE",
    "Required once": "REQUIRED_ONCE",
    "Required multiple": "REQUIRED_MULTIPLE",
}


def get_processor_client(location: str) -> documentai.DocumentProcessorServiceClient:
    opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    return documentai.DocumentProcessorServiceClient(client_options=opts)


def get_document_client(location: str) -> documentai_beta.DocumentServiceClient:
    opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    return documentai_beta.DocumentServiceClient(client_options=opts)


def load_schema(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def build_document_schema(schema_fields: list[dict]) -> documentai_beta.DocumentSchema:
    """Convert the repo schema JSON into a Document AI DocumentSchema.

    Structure per docs (cloud.google.com/document-ai/docs/create-dataset):
      - Single root EntityType named "custom_extraction_document_type"
        with baseTypes=["document"]
      - Each extraction field is a Property on that root entity with
        valueType set to the data type (string, datetime, address, etc.)
    """
    Property = documentai_beta.DocumentSchema.EntityType.Property
    EntityType = documentai_beta.DocumentSchema.EntityType

    properties = []
    for field in schema_fields:
        if not field.get("enabled", True):
            continue

        value_type = DATA_TYPE_MAP.get(field["dataType"], "string")
        occurrence = OCCURRENCE_MAP.get(field.get("occurrence", ""), "OPTIONAL_ONCE")
        method = "EXTRACT" if field.get("method") == "Extract" else "METHOD_UNSPECIFIED"

        properties.append(Property(
            name=field["name"],
            description=field.get("description", ""),
            value_type=value_type,
            occurrence_type=occurrence,
            method=method,
        ))

    root_entity = EntityType(
        name=ROOT_ENTITY_NAME,
        base_types=["document"],
        properties=properties,
        entity_type_metadata=EntityTypeMetadata(inactive=False),
    )

    return documentai_beta.DocumentSchema(
        display_name="Alcohol License Schema",
        entity_types=[root_entity],
    )


def find_processor(client, parent: str, display_name: str):
    """Find an existing processor by display name (for idempotency)."""
    for processor in client.list_processors(parent=parent):
        if processor.display_name == display_name:
            return processor
    return None


def initialize_dataset(doc_client, processor_name: str, gcs_bucket: str) -> None:
    """Initialize the processor's dataset with a GCS-managed folder."""
    dataset_name = f"{processor_name}/dataset"
    processor_id = processor_name.split("/")[-1]
    gcs_prefix = f"gs://{gcs_bucket}/docai-dataset/{processor_id}/"

    print(f"  Initializing dataset (GCS: {gcs_prefix})...")
    try:
        doc_client.update_dataset(
            request=documentai_beta.UpdateDatasetRequest(
                dataset=documentai_beta.Dataset(
                    name=dataset_name,
                    gcs_managed_config=documentai_beta.Dataset.GCSManagedConfig(
                        gcs_prefix=documentai_beta.GcsPrefix(gcs_uri_prefix=gcs_prefix),
                    ),
                ),
                update_mask={"paths": ["gcs_managed_config"]},
            )
        )
    except google_exceptions.FailedPrecondition:
        print("  Dataset already initialized.")
        return

    # Wait for dataset to be initialized
    for i in range(60):
        schema_name = f"{processor_name}/dataset/datasetSchema"
        try:
            doc_client.get_dataset_schema(name=schema_name)
            print("  Dataset initialized.")
            return
        except Exception:
            time.sleep(2)

    print("  Warning: dataset initialization may still be in progress.")


def update_schema(doc_client, processor_name: str,
                  doc_schema: documentai_beta.DocumentSchema) -> None:
    """Set the extraction schema on the processor's dataset."""
    schema_name = f"{processor_name}/dataset/datasetSchema"

    dataset_schema = documentai_beta.DatasetSchema(
        name=schema_name,
        document_schema=doc_schema,
    )

    doc_client.update_dataset_schema(
        request=documentai_beta.UpdateDatasetSchemaRequest(
            dataset_schema=dataset_schema,
        )
    )
    print("  Schema configured.")


def write_config(project_id: str, location: str, processor_name: str,
                 expected_fields: list[str]) -> None:
    """Write the generated config file for the backend."""
    # processor_name format: projects/{project}/locations/{loc}/processors/{id}
    processor_id = processor_name.split("/")[-1]

    config = {
        "project_id": project_id,
        "location": location,
        "processor_id": processor_id,
        "processor_name": processor_name,
        "expected_fields": expected_fields,
    }

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"  Config written to {CONFIG_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Set up Document AI processor")
    parser.add_argument("--force", action="store_true",
                        help="Force schema update even if already configured")
    args = parser.parse_args()

    # Resolve project ID from env (Terraform passes this via environment block)
    project_id = (
        os.environ.get("PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("TF_VAR_project_id")
    )
    if not project_id:
        print("ERROR: Set PROJECT_ID or GOOGLE_CLOUD_PROJECT", file=sys.stderr)
        sys.exit(1)

    location = os.environ.get("DOCAI_LOCATION", LOCATION)
    gcs_bucket = os.environ.get("GCS_BUCKET")
    if not gcs_bucket:
        print("ERROR: Set GCS_BUCKET env var (for dataset storage)", file=sys.stderr)
        sys.exit(1)

    print(f"Project:  {project_id}")
    print(f"Location: {location}")
    print(f"Bucket:   {gcs_bucket}")

    # ---- Load schema --------------------------------------------------------
    schema_fields = load_schema(SCHEMA_PATH)
    doc_schema = build_document_schema(schema_fields)
    expected_fields = [f["name"] for f in schema_fields if f.get("enabled", True)]
    print(f"Schema:   {len(expected_fields)} fields")

    # ---- Clients ------------------------------------------------------------
    proc_client = get_processor_client(location)
    doc_client = get_document_client(location)
    parent = proc_client.common_location_path(project_id, location)

    # ---- Processor (create if not exists) -----------------------------------
    processor = find_processor(proc_client, parent, PROCESSOR_DISPLAY_NAME)
    if processor:
        print(f"Processor already exists: {processor.name}")
    else:
        print("Creating Custom Extractor processor...")
        processor = proc_client.create_processor(
            parent=parent,
            processor=documentai.Processor(
                display_name=PROCESSOR_DISPLAY_NAME,
                type_="CUSTOM_EXTRACTION_PROCESSOR",
            ),
        )
        print(f"  Created: {processor.name}")

    # ---- Ensure dataset is initialized ---------------------------------------
    # Always call initialize — it's idempotent (no-op if already initialized).
    # The dataset must be initialized with a GCS folder before the processor
    # can be used for inference.
    initialize_dataset(doc_client, processor.name, gcs_bucket)

    # Check if schema is already configured
    schema_name = f"{processor.name}/dataset/datasetSchema"
    try:
        existing_schema = doc_client.get_dataset_schema(name=schema_name)
        existing_types = {et.name for et in existing_schema.document_schema.entity_types}
        if ROOT_ENTITY_NAME in existing_types and not args.force:
            print("Schema already configured — skipping (use --force to update).")
            write_config(project_id, location, processor.name, expected_fields)
            print("Done!")
            return
    except Exception:
        pass

    # ---- Set schema ---------------------------------------------------------
    print("Configuring extraction schema...")
    update_schema(doc_client, processor.name, doc_schema)

    # Note: The pretrained Foundation Model uses schema_override in the
    # ProcessRequest at inference time (see backend/document_ai.py).
    # No need to train a custom version for zero-shot extraction.

    # ---- Write config -------------------------------------------------------
    write_config(project_id, location, processor.name, expected_fields)

    print("Done!")


if __name__ == "__main__":
    main()
